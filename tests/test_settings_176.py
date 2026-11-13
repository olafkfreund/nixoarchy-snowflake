"""#176 step 2: the voice-engine settings keys, their refusals (400 {"error"}), and state_info."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from test_speakable import _ServerEnv

VOICE = "abcdefghij1234"
KEY = "sk-fake-key-VALUE-12345"


class VoiceSettingsTest(_ServerEnv):
    def setUp(self):
        s = self.server
        saved = dict(s.CFG)
        self.addCleanup(lambda: (s.CFG.clear(), s.CFG.update(saved)))
        for p in (mock.patch.object(s.quick, "projects", return_value={}),
                  mock.patch.object(s.eleven, "has_key", return_value=True),
                  mock.patch.object(s.eleven, "_key", return_value=KEY),
                  mock.patch.object(s.eleven, "voices", return_value=[{"id": VOICE, "name": "V"}])):
            p.start()
            self.addCleanup(p.stop)
        self.srv = s.ThreadingHTTPServer(("127.0.0.1", 0), s.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def post(self, body):
        s = self.server
        req = urllib.request.Request(f"http://127.0.0.1:{self.srv.server_port}/api/settings", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "X-Nixi-Token": s.TOKEN})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_defaults(self):
        d = self.server.DEFAULTS
        self.assertEqual((d["tts_fallback"], d["eleven_on"], d["eleven_voice"], d["eleven_daily_chars"]), ("auto", False, "", 20000))

    def test_size_accepts_125_percent_and_clamps_above_it(self):
        self.assertEqual(self.server.DEFAULTS["size"], 0.75)
        for requested in (1.25, 1.5):
            code, response = self.post({"size": requested})
            self.assertEqual(code, 200)
            self.assertEqual(response["size"], 1.25)
            self.assertEqual(self.server.CFG["size"], 1.25)

    def test_bad_values_are_refused_with_a_sentence(self):
        for body in ({"tts": "nope"}, {"tts_fallback": "elevenlabs"}, {"eleven_voice": "short"}, {"eleven_voice": "a b" * 5},
                     {"eleven_daily_chars": 999}, {"eleven_daily_chars": 500001}, {"eleven_daily_chars": "5000"}):
            code, r = self.post(body)
            self.assertEqual(code, 400, body)
            self.assertIsInstance(r["error"], str)
        self.assertEqual(self.server.CFG["tts"], "auto")

    def test_on_needs_confirm_and_elevenlabs_needs_on(self):
        s = self.server
        self.assertEqual(self.post({"eleven_on": True})[0], 400)
        self.assertIs(s.CFG["eleven_on"], False)
        self.assertEqual(self.post({"tts": "elevenlabs"})[0], 400)
        self.assertEqual(self.post({"eleven_on": True, "confirm": "cloud", "tts": "elevenlabs"})[0], 400)   # no voice yet
        code, r = self.post({"eleven_on": True, "confirm": "cloud", "eleven_voice": VOICE, "tts": "elevenlabs"})
        self.assertEqual(code, 200)
        self.assertEqual((s.CFG["tts"], r["tts_choice"], r["tts"]), ("elevenlabs", "elevenlabs", "elevenlabs"))
        self.assertEqual(self.post({"eleven_on": False})[0], 200)

    def test_keys_persist_in_bridged_mode(self):
        s = self.server
        with mock.patch.object(s, "BRIDGED", True):
            code, r = self.post({"tts_fallback": "espeak", "eleven_daily_chars": 5000})
        self.assertEqual(code, 200)
        self.assertEqual((s.CFG["tts_fallback"], s.CFG["eleven_daily_chars"]), ("espeak", 5000))

    def test_phone_on_is_a_bool_setting_that_starts_and_resets_the_client(self):
        s = self.server
        self.assertIs(s.DEFAULTS["phone_on"], False)
        with mock.patch.object(s.Phone, "start") as start, mock.patch.object(s.Phone, "stop") as stop:
            code, r = self.post({"phone_on": 1})
            self.assertEqual((code, r["phone_on"], s.CFG["phone_on"]), (200, True, True))
            self.assertEqual(json.loads(s.CONF_PATH.read_text())["phone_on"], True)
            start.assert_called_once()
            gen = s.PHONE_GEN
            code, r = self.post({"phone_on": False})
            self.assertEqual((code, r["phone_on"], r["phone_status"], s.CFG["phone_on"]), (200, False, "", False))
            stop.assert_called_once()
            self.assertEqual(s.PHONE_GEN, gen + 1)
            self.post({"phone_on": False})                       # (no change: no second reset)
            stop.assert_called_once()

    def test_phone_status_line_is_names_and_fixed_words(self):
        s = self.server
        s.CFG["phone_on"] = True
        with mock.patch.object(type(s.Phone), "connected", False):
            self.assertEqual(s.phone_status(), "Flux isn't running")
        dev = {"id": "p", "name": "Pixel", "can": {"dnd"}, "dnd": {"on": None}}
        with mock.patch.object(type(s.Phone), "connected", True), mock.patch.object(s.Phone, "devices", return_value=[dev]):
            with mock.patch.object(type(s.Phone), "modern", False):
                self.assertEqual(s.phone_status(), "Update Flux for calls and meeting silence")
            with mock.patch.object(type(s.Phone), "modern", True):
                self.assertIn("Sync Do Not Disturb on the Pixel", s.phone_status())
                dev["dnd"] = {"on": False}
                self.assertEqual(s.phone_status(), "Connected: Pixel")

    def test_state_has_engines_with_reasons_and_never_the_key(self):
        s = self.server
        s.CFG.update(eleven_on=True, eleven_voice=VOICE)
        st = s.state_info()
        engines = {e["id"]: e for e in st["engines"]}
        self.assertEqual(set(engines), {"auto", "kokoro", "piper", "espeak", "elevenlabs", "off"})
        with mock.patch.object(s, "kokoro_ready", return_value=False):
            e = {e["id"]: e for e in s.state_info()["engines"]}["kokoro"]
        self.assertFalse(e["ready"])
        self.assertTrue(e["reason"])
        self.assertEqual(st["eleven"]["voices"], [{"id": VOICE, "name": "V"}])
        self.assertEqual(st["eleven"]["cap"], 20000)
        self.assertNotIn(KEY, json.dumps(st))
        self.assertNotIn(KEY, self.server.diagnostics() if hasattr(self.server, "diagnostics") else "")

    def test_unavailable_cloud_reports_the_fallback_as_speaking(self):
        s = self.server
        s.CFG.update(tts="elevenlabs", eleven_on=False, tts_fallback="espeak")
        with mock.patch.object(s.shutil, "which", return_value="/bin/espeak-ng"):
            self.assertEqual(s.state_info()["tts"], "espeak")

    def test_robot_and_espeak_readiness(self):
        s = self.server
        def ready(mode):
            s.CFG["tts"] = mode
            return {v["id"]: v["ready"] for v in s.state_info()["voices"]}
        with mock.patch.object(s.shutil, "which", return_value="/bin/espeak-ng"):
            r = ready("kokoro")
            self.assertFalse(r["robot"])
            r = ready("espeak")
            self.assertTrue(r["robot"] and r["girl"] and r["deep"])


if __name__ == "__main__":
    unittest.main()
