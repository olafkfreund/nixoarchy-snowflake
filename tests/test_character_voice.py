"""A character's preset resolves at speech time without changing the user's saved voice."""
from unittest import mock

from test_speakable import _ServerEnv


class CharacterVoiceTest(_ServerEnv):
    def setUp(self):
        s = self.server
        self.addCleanup(setattr, s.lang, "active", s.lang.active)
        for patcher in (
            mock.patch.dict(s.CFG, {"voice": "girl", "voice_by_lang": {}, "voice_by_character": {},
                                    "look": {"character": "snowflake"}, "tts": "auto", "piper_voice": "", "kokoro_voice": ""}),
            mock.patch.object(s, "piper_bin", return_value="piper"),
            mock.patch.object(s, "kokoro_ready", return_value=False),
            mock.patch.object(s.shutil, "which", return_value=None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        s.lang.active = "en"

    def test_no_entry_keeps_current_choices(self):
        s = self.server
        s.CFG["voice_by_lang"] = {"pl": "guy"}
        self.assertEqual(s.voice_preset()["label"], "Girl")
        self.assertEqual(s.lang_voice_name("pl"), "pl_PL-darkman-medium")
        self.assertEqual(s.lang_voice_name("en"), "en_US-amy-medium")

    def test_character_wins_and_others_use_their_own(self):
        s = self.server
        s.CFG.update(voice="girl", voice_by_lang={"pl": "guy"},
                     voice_by_character={"snowflake": "deep", "devil": "british"})
        self.assertEqual(s.voice_preset()["label"], "Deep")
        self.assertEqual(s.lang_voice_name("en"), s.VOICES["deep"]["piper"])
        self.assertEqual(s.lang_voice_name("pl"), "pl_PL-darkman-medium")
        s.CFG["look"] = {"character": "devil"}
        self.assertEqual(s.voice_preset()["label"], "British")
        self.assertEqual(s.lang_voice_name("pl"), "pl_PL-mc_speech-medium")
        s.CFG["look"] = {"character": "terminal"}
        self.assertEqual(s.voice_preset()["label"], "Girl")
        self.assertEqual(s.lang_voice_name("pl"), "pl_PL-darkman-medium")

    def test_character_and_language_changes_do_not_write_user_choices(self):
        s = self.server
        s.CFG.update(voice="cute", voice_by_lang={"pl": "guy"}, voice_by_character={"robot": "deep"})
        before = (s.CFG["voice"], s.CFG["voice_by_lang"].copy())
        s.CFG["look"] = {"character": "robot"}
        for code in ("en", "pl", "nb"):
            s.lang.active = code
            s.voice_preset()
            s.lang_voice_name(code)
        self.assertEqual((s.CFG["voice"], s.CFG["voice_by_lang"]), before)

    def test_localizes_polish_and_norwegian(self):
        s = self.server
        s.CFG["voice_by_character"] = {"snowflake": "british"}
        for code, name in (("pl", "pl_PL-mc_speech-medium"), ("nb", "no_NO-talesyntese-medium")):
            s.lang.active = code
            self.assertEqual(s.voice_preset()["piper"], name)
            self.assertEqual(s.lang_voice_name(code), name)

    def test_robot_needs_espeak_and_ignores_pins(self):
        s = self.server
        s.CFG.update(voice="girl", voice_by_character={"snowflake": "robot"})
        for mode in ("auto", "kokoro", "piper", "espeak"):
            s.CFG["tts"] = mode
            for espeak in (None, "/bin/espeak-ng"):
                with self.subTest(mode=mode, espeak=espeak), mock.patch.object(s.shutil, "which", return_value=espeak):
                    robot = bool(espeak) and mode in ("auto", "espeak")
                    self.assertEqual(s.voice_key(), "robot" if robot else "girl")
                    self.assertEqual(s.voice_preset()["label"], "Robot" if robot else "Girl")
                    expected = "en_US-amy-medium" if mode in ("auto", "piper") and not robot else None
                    self.assertEqual(s.lang_voice_name("en"), expected)
                    self.assertEqual(s.voice_ready(s.VOICES["robot"]), robot)
        s.CFG.update(tts="auto", kokoro_voice="pinned", piper_voice="/pinned.onnx")
        with mock.patch.object(s.shutil, "which", return_value="/bin/espeak-ng"):
            self.assertEqual(s.voice_key(), "robot")
            self.assertEqual(s.voice_preset()["label"], "Robot")
            self.assertIsNone(s.lang_voice_name("en"))

    def test_bad_maps_and_values_are_ignored(self):
        s = self.server
        for value in (None, [], "robot", {"snowflake": "missing"}, {"snowflake": ["robot"]}):
            with self.subTest(value=value):
                s.CFG["voice_by_character"] = value
                self.assertEqual(s.voice_key(), "girl")
                self.assertEqual(s.voice_preset()["label"], "Girl")
                self.assertEqual(s.lang_voice_name("en"), "en_US-amy-medium")

    def test_state_reports_speaking_pin_and_only_valid_entries(self):
        s = self.server
        s.CFG["voice_by_character"] = {"snowflake": "deep", "devil": "missing", "bogus": "girl", "robot": ["girl"]}
        with mock.patch.object(s, "piper_voice", return_value="/pinned.onnx"), \
             mock.patch.object(s.eleven, "voices", return_value=[]), mock.patch.object(s.quick, "projects", return_value={}):
            s.CFG.update(tts="piper", kokoro_voice="pinned")
            info = s.state_info()
            self.assertEqual((info["voice"], info["voice_speaking"]), ("girl", "deep"))
            self.assertFalse(info["voice_pinned"])
            self.assertEqual(info["voice_by_character"], {"snowflake": "deep"})
            s.CFG["piper_voice"] = "/pinned.onnx"
            self.assertTrue(s.state_info()["voice_pinned"])
            s.lang.active = "pl"
            self.assertFalse(s.state_info()["voice_pinned"])
            s.lang.active = "en"
            s.CFG["tts"] = "kokoro"
            with mock.patch.object(s, "kokoro_ready", return_value=True):
                self.assertTrue(s.state_info()["voice_pinned"])
            s.CFG["voice_by_character"] = []
            self.assertEqual(s.state_info()["voice_by_character"], {})

    def test_diagnostics_names_both_voices_only_when_different(self):
        s = self.server
        with mock.patch.object(s, "claude_bin", return_value=None):
            s.CFG["voice_by_character"] = {"snowflake": "deep"}
            self.assertIn("(voice: girl, speaking: deep)", s.diagnostics())
            s.CFG["voice_by_character"] = {}
            self.assertIn("(voice: girl)", s.diagnostics())
            self.assertNotIn("speaking:", s.diagnostics())
