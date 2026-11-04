"""#176 step 3: cloud fallback, generation cuts, and reply boundaries."""
import unittest
import io
import json
import wave
from unittest import mock

from test_speakable import _ServerEnv


class ElevenSpeakerTest(_ServerEnv):
    def setUp(self):
        s = self.server
        saved = dict(s.CFG)
        self.addCleanup(lambda: (s.CFG.clear(), s.CFG.update(saved)))
        s.CFG.update(tts="elevenlabs", eleven_on=True, eleven_voice="abcdefghij1234", tts_fallback="espeak")
        s.Speaker.stop()
        s._eleven_noted.clear()
        s.clear_eleven_error()
        self.events = []
        p = mock.patch.object(s.BUS, "pub", side_effect=lambda **e: self.events.append(e))
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(s.eleven, "has_key", return_value=True)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(s.shutil, "which", return_value="/bin/espeak-ng")
        p.start()
        self.addCleanup(p.stop)

    def test_fallback_once_and_sticky_until_new_reply(self):
        s = self.server
        with mock.patch.object(s.eleven, "reserve"), mock.patch.object(s.eleven, "settle"), \
                mock.patch.object(s.eleven, "speak", side_effect=s.eleven.ElevenError("auth")) as cloud, \
                mock.patch.object(s, "synth", return_value=(b"local", 1.0)) as local:
            self.assertEqual(s.speak_sentence("Hello.", s.Speaker.gen, "one"), (b"local", 1.0, "espeak"))
            self.assertEqual(s.speak_sentence("Again.", s.Speaker.gen, "one"), (b"local", 1.0, "espeak"))
            self.assertEqual(cloud.call_count, 1)
            self.assertEqual(local.call_count, 2)
            self.assertEqual(len([e for e in self.events if e["t"] == "note"]), 1)
            s.speak_sentence("New.", s.Speaker.gen, "two")
            self.assertEqual(cloud.call_count, 2)

    def test_stale_cloud_does_not_send_and_local_item_survives(self):
        s = self.server
        old = s.Speaker.gen
        s.Speaker.cut_cloud()
        with mock.patch.object(s.eleven, "speak") as cloud, mock.patch.object(s, "synth", return_value=(b"local", 1.0)) as local:
            self.assertIsNone(s.speak_sentence("Old.", old, "one", "elevenlabs"))
            self.assertEqual(s.speak_sentence("Local.", old, "one", "espeak"), (b"local", 1.0, "espeak"))
            cloud.assert_not_called()
            local.assert_called_once()

    def test_cut_cloud_drops_only_cloud_items_and_publishes_done(self):
        s = self.server
        S = s.Speaker
        with S.cv:
            S.todo = [(S.gen, 1, "cloud", True, "elevenlabs", "a", False),
                      (S.gen, 2, "local", True, "espeak", "a", True)]
            S.ready = [(S.gen, 3, "cloud", b"", 22050, None, None, 1, True, "elevenlabs", "a"),
                       (S.gen, 4, "ready local", b"old", 22050, None, None, 1, True, "espeak", "a")]
        S.cut_cloud()
        self.assertEqual([x[1] for x in S.todo], [4, 2])
        self.assertEqual(S.ready, [])
        self.assertEqual([e["id"] for e in self.events if e["t"] == "spk_done"], [1, 3])
        self.assertTrue(any(e["t"] == "tts_gen" for e in self.events))

    def test_off_during_in_flight_cloud_discards_audio(self):
        s = self.server
        def speak(*args):
            s.CFG["eleven_on"] = False
            s.Speaker.cut_cloud()
            return b"cloud"
        with mock.patch.object(s.eleven, "reserve"), mock.patch.object(s.eleven, "settle"), \
                mock.patch.object(s.eleven, "speak", side_effect=speak) as cloud:
            self.assertIsNone(s.speak_sentence("Hello.", s.Speaker.gen, "one", "elevenlabs"))
            self.assertIsNone(s.speak_sentence("Again.", s.Speaker.gen - 1, "one", "elevenlabs"))
            cloud.assert_called_once()

    def test_off_never_reaches_cloud(self):
        s = self.server
        s.CFG["eleven_on"] = False
        with mock.patch.object(s.eleven, "speak") as cloud, mock.patch.object(s, "synth", return_value=(b"local", 1.0)):
            self.assertEqual(s.speak_sentence("Local.", s.Speaker.gen, "one", "elevenlabs"),
                             (b"local", 1.0, "espeak"))
            cloud.assert_not_called()

    def test_deleted_voice_releases_reservation_before_send(self):
        s = self.server
        with mock.patch.object(s.eleven, "reserve"), mock.patch.object(s.eleven, "settle") as settle, \
                mock.patch.object(s.eleven, "speak", side_effect=s.eleven.ElevenError("bad_voice")), \
                mock.patch.object(s, "synth", return_value=(b"local", 1.0)):
            s.speak_sentence("Hello.", s.Speaker.gen, "one", "elevenlabs")
        settle.assert_called_once_with(len("Hello."), False, False)

    def test_stress_say_loop_is_local(self):
        import inspect
        self.assertIn("Speaker.say(line, n * 100 + i + 1, local=True)", inspect.getsource(self.server.stress_voice))

    def test_page_tts_uses_the_same_fallback(self):
        s = self.server
        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(b"\0\0" * 2205)
        h = object.__new__(s.Handler)
        h.path = "/api/tts"
        h.headers = {"X-Nixi-Token": s.TOKEN}
        h.wfile = io.BytesIO()
        h._host_ok = lambda: True
        h._body = lambda: json.dumps({"text": "Hello.", "reply": "r1"}).encode()
        h.send_response = mock.Mock()
        h.send_header = mock.Mock()
        h.end_headers = mock.Mock()
        with mock.patch.object(s.eleven, "reserve"), mock.patch.object(s.eleven, "settle"), \
                mock.patch.object(s.eleven, "speak", side_effect=s.eleven.ElevenError("bad_voice")), \
                mock.patch.object(s, "synth", return_value=(out.getvalue(), 1.0)), \
                mock.patch.object(s, "tidy_and_time", return_value=(out.getvalue(), None)), \
                mock.patch.object(s.PAGE_FLOOR, "served"):
            h.do_POST()
        h.send_response.assert_called_with(200)
        self.assertEqual(h.wfile.getvalue(), out.getvalue())
        self.assertTrue(any("voice no longer on your account" in e.get("text", "") for e in self.events))

    def test_preview_requires_token(self):
        s = self.server
        h = object.__new__(s.Handler)
        h.path = "/api/eleven/preview/abcdefghij1234"
        h.headers = {}
        h.wfile = io.BytesIO()
        h._host_ok = lambda: True
        h._json = mock.Mock()
        h.send_response = mock.Mock()
        h.send_header = mock.Mock()
        h.end_headers = mock.Mock()
        with mock.patch.object(s.eleven, "preview", return_value=b"ID3audio") as preview:
            h.do_GET()
            h._json.assert_called_with({"error": "forbidden"}, 403)
            preview.assert_not_called()
            h.headers = {"X-Nixi-Token": s.TOKEN}
            h.do_GET()
            preview.assert_called_once_with("abcdefghij1234")
            h.send_response.assert_called_with(200)
            self.assertEqual(h.wfile.getvalue(), b"ID3audio")


if __name__ == "__main__":
    unittest.main()
