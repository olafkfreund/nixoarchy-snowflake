"""Step 1: strict agent speech never changes to a local voice."""
import io
import json
import time
import unittest
from unittest import mock

from test_speakable import _ServerEnv


class AgentVoiceTest(_ServerEnv):
    def setUp(self):
        s = self.server
        saved = dict(s.CFG)
        self.addCleanup(lambda: (s.CFG.clear(), s.CFG.update(saved)))
        s.CFG.update(tts="elevenlabs", eleven_on=True, eleven_voice="fake-voice", tts_fallback="espeak")
        s.Speaker.stop()
        self.addCleanup(s.Speaker.stop)
        with s.Speaker.cv:
            s._eleven_sticky.update(reply=None, kind="")
        self.events = []
        p = mock.patch.object(s.BUS, "pub", side_effect=lambda **event: self.events.append(event))
        p.start()
        self.addCleanup(p.stop)
        for obj, name, value in ((s.eleven, "has_key", True), (s.eleven, "voices", [{"id": "fake-voice"}]),
                                 (s.shutil, "which", "/bin/espeak-ng")):
            p = mock.patch.object(obj, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def test_strict_rejects_every_local_path_without_synth(self):
        s = self.server
        with mock.patch.object(s, "synth") as synth:
            self.assertIsNone(s.speak_sentence("Local.", s.Speaker.gen, engine="espeak", strict=True))
            self.assertIsNone(s.speak_sentence("Local flag.", s.Speaker.gen, local=True, strict=True))
            s.CFG["eleven_on"] = False
            self.assertIsNone(s.speak_sentence("Off.", s.Speaker.gen, engine="elevenlabs", strict=True))
            s.CFG["eleven_on"] = True
            with s.Speaker.cv:
                s._eleven_sticky.update(reply="same", kind="cap")
            self.assertIsNone(s.speak_sentence("Sticky.", s.Speaker.gen, "same", "elevenlabs", strict=True))
            with s.Speaker.cv:
                s._eleven_sticky.update(reply=None, kind="")
            old = s.Speaker.gen
            s.Speaker.cut_cloud()
            self.assertIsNone(s.speak_sentence("Stale.", old, engine="elevenlabs", strict=True))
            self.assertIsNone(s.speak_sentence("Requeued.", old, engine="espeak", strict=True))
            synth.assert_not_called()
        self.assertFalse(any(e["t"] == "spk_skip" for e in self.events))

    def test_strict_cloud_error_keeps_sticky_without_local_synth(self):
        s = self.server
        with mock.patch.object(s.eleven, "reserve"), mock.patch.object(s.eleven, "settle"), \
             mock.patch.object(s.eleven, "speak", side_effect=s.eleven.ElevenError("cap", 429, True)), \
             mock.patch.object(s, "synth") as synth:
            self.assertIsNone(s.speak_sentence("Cap.", s.Speaker.gen, "r1", "elevenlabs", strict=True))
            synth.assert_not_called()
        self.assertEqual(s._eleven_sticky["kind"], "cap")
        self.assertFalse(self.events)

    def test_non_strict_and_non_eleven_modes_still_synth(self):
        s = self.server
        with mock.patch.object(s, "synth", return_value=(b"audio", 1.0)) as synth:
            self.assertEqual(s.speak_sentence("Normal.", s.Speaker.gen, engine="espeak"), (b"audio", 1.0, "espeak"))
            s.CFG["tts"] = "espeak"
            self.assertEqual(s.speak_sentence("Strict local mode.", s.Speaker.gen, engine="espeak", strict=True),
                             (b"audio", 1.0, "espeak"))
            self.assertEqual(synth.call_count, 2)

    def test_maker_skips_strict_rewritten_item_once(self):
        s = self.server
        S = s.Speaker
        with S.cv:
            S.strict.add(41)
            S.todo = [(S.gen, 41, "Rewritten.", False, "espeak", "r1", True)]
        with mock.patch.object(S.cv, "wait", side_effect=StopIteration), mock.patch.object(s, "synth") as synth:
            with self.assertRaises(StopIteration):
                S._maker()
            synth.assert_not_called()
        self.assertEqual([e["id"] for e in self.events if e["t"] == "spk_skip"], [41])
        self.assertNotIn(41, S.strict)

    def test_cut_cloud_skips_strict_drops_and_keeps_rewritten_strict(self):
        s = self.server
        S = s.Speaker
        with S.cv:
            S.strict.update((1, 2, 3, 4, 5))
            S.todo = [(S.gen, 1, "cloud", False, "elevenlabs", "r1", False),
                      (S.gen, 5, "local", False, "espeak", "r1", True)]
            S.ready = [(S.gen, 2, "cloud", b"", 22050, None, None, 1, False, "elevenlabs", "r1")]
            S.making_item = (S.gen, 3, "cloud", False, "elevenlabs", "r1", False)
            S.current_engine, S.current_sid = "elevenlabs", 4
        S.cut_cloud()
        skips = [e["id"] for e in self.events if e["t"] == "spk_skip"]
        self.assertEqual(skips, [1, 2, 3, 4])
        self.assertFalse(any(e["t"] == "spk_done" for e in self.events))
        self.assertEqual([x[1] for x in S.todo], [5])
        self.assertIn(5, S.strict)
        with mock.patch.object(s, "synth") as synth:
            self.assertIsNone(s.speak_sentence("local", S.gen, "r1", S.todo[0][4], S.todo[0][6], strict=True))
            synth.assert_not_called()
        S.cut_cloud()
        self.assertEqual([e["id"] for e in self.events if e["t"] == "spk_skip"], skips)

    def test_epoch_drop_skips_and_stop_clears_strict(self):
        s = self.server
        S = s.Speaker
        with mock.patch.object(S, "_start"):
            S.stop(epoch=10)
            S.say("Old.", 9, epoch=9, strict=True)
            self.assertEqual([e["id"] for e in self.events if e["t"] == "spk_skip"], [9])
            self.assertNotIn(9, S.strict)
            S.say("New.", 10, epoch=10, strict=True)
            self.assertIn(10, S.strict)
            S.stop()
            self.assertFalse(S.strict)

    def test_strict_tts_returns_no_voice_and_does_not_open_follow_window(self):
        s = self.server
        h = object.__new__(s.Handler)
        h.path = "/api/tts"
        h.headers = {"X-Nixi-Token": s.TOKEN}
        h.wfile = io.BytesIO()
        h._host_ok = lambda: True
        h._body = lambda: json.dumps({"text": "Hello.", "strict": True}).encode()
        h.send_response = mock.Mock()
        h.send_header = mock.Mock()
        h.end_headers = mock.Mock()
        with mock.patch.object(s, "synth") as synth:
            s.CFG["eleven_on"] = False
            h.do_POST()
            synth.assert_not_called()
        h.send_response.assert_called_with(204)
        s.Wake.talking_until(time.monotonic() - 1, False)
        self.assertFalse(s.Wake.window_open())

    def test_say_endpoint_passes_strict_to_speaker(self):
        s = self.server
        h = object.__new__(s.Handler)
        h.path = "/api/say"
        h.headers = {"X-Nixi-Token": s.TOKEN}
        h._host_ok = lambda: True
        h._body = lambda: json.dumps({"text": "Hello.", "id": 17, "strict": True}).encode()
        h._json = mock.Mock()
        with mock.patch.object(s.Speaker, "say") as say:
            h.do_POST()
        say.assert_called_once_with("Hello.", 17, None, True, None, strict=True)


if __name__ == "__main__":
    unittest.main()
