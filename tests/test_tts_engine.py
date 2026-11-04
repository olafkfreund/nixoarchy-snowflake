"""#176 step 2: an explicit engine never swaps; auto keeps its swaps; the cloud voice needs on + key + voice."""
import inspect
import unittest
from unittest import mock

from test_speakable import _ServerEnv


class EngineChoiceTest(_ServerEnv):
    def setUp(self):
        s = self.server
        saved = dict(s.CFG)
        self.addCleanup(lambda: (s.CFG.clear(), s.CFG.update(saved)))
        for p in (mock.patch.object(s, "kokoro_ready", return_value=True),
                  mock.patch.object(s, "piper_bin", return_value="/bin/piper"),
                  mock.patch.object(s, "piper_voice", return_value=None),
                  mock.patch.object(s.shutil, "which", return_value="/bin/espeak-ng"),
                  mock.patch.object(s.eleven, "has_key", return_value=True)):
            p.start()
            self.addCleanup(p.stop)

    def test_explicit_engine_does_not_swap(self):
        s = self.server
        s.CFG.update(tts="piper")
        self.assertIsNone(s.tts_engine())                       # no piper voice → none, not espeak
        s.CFG.update(tts="auto")
        self.assertEqual(s.tts_engine(), "kokoro")
        with mock.patch.object(s, "kokoro_ready", return_value=False):
            self.assertEqual(s.tts_engine(), "espeak")          # auto still falls through

    def test_robot_is_refused_under_explicit_kokoro_and_piper(self):
        s = self.server
        s.CFG.update(tts="kokoro", voice="robot")
        with self.assertRaises(s.NoVoice):
            s.synth("hi")
        s.CFG.update(tts="piper")
        with mock.patch.object(s, "piper_voice", return_value="/x.onnx"), self.assertRaises(s.NoVoice):
            s.synth("hi")

    def test_explicit_piper_without_a_model_raises(self):
        s = self.server
        s.CFG.update(tts="piper", voice="girl")
        with mock.patch.object(s, "piper_voice", return_value="/x.onnx"), mock.patch.object(s, "voice_file") as vf, \
                mock.patch.object(s, "fetch_voice"):
            vf.return_value.exists.return_value = False
            with mock.patch.object(s, "piper_inproc", return_value=b"W") as pi:
                self.assertEqual(s.synth("hi"), (b"W", 1.0))      # piper_voice set → that file is used
                self.assertEqual(pi.call_args[0][0], "/x.onnx")
        with self.assertRaises(s.NoVoice):                       # piper_bin but no voice at all → engine is None
            s.synth("hi")

    def test_elevenlabs_needs_on_key_and_voice(self):
        s = self.server
        s.CFG.update(tts="elevenlabs", eleven_on=False, eleven_voice="")
        self.assertIsNone(s.tts_engine())
        s.CFG["eleven_on"] = True
        self.assertIsNone(s.tts_engine())                       # no voice yet
        s.CFG["eleven_voice"] = "abcdefghij1234"
        self.assertEqual(s.tts_engine(), "elevenlabs")
        with mock.patch.object(s.eleven, "has_key", return_value=False):
            self.assertIsNone(s.tts_engine())
        s.CFG["tts_fallback"] = "espeak"
        self.assertEqual(s.tts_engine(local=True), "espeak")    # local = what speaks when the cloud can't

    def test_warm_up_and_stress_stay_local(self):
        s = self.server
        for fn in (s.warm_tts, s.stress_voice):
            src = inspect.getsource(fn)
            self.assertNotIn("eleven.speak", src)
            self.assertNotIn("synth(\"Hi.\")", src)             # every synth there says local=True
        s.CFG.update(tts="elevenlabs", eleven_on=True, eleven_voice="abcdefghij1234", tts_fallback="kokoro")
        with mock.patch.object(s, "fetch_kokoro"), mock.patch.object(s, "synth") as sy, \
                mock.patch.object(s.eleven, "speak") as sp:
            s.warm_tts()
        sy.assert_called_once_with("Hi.", local=True)
        sp.assert_not_called()


class EnvTest(_ServerEnv):
    def test_agent_environments_carry_no_eleven_variable(self):
        src = (self.server.Path(self.server.__file__)).read_text()
        self.assertNotIn("ELEVEN", src.replace("ELEVENLABS_DOC", ""))


if __name__ == "__main__":
    unittest.main()
