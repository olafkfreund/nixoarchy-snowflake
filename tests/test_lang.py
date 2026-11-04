"""#177 step 1: LANGS, t(), the first-run default, the language setting, and lang_clause in the four agent paths."""
import json
import sys
import threading
import urllib.request
import unittest
from unittest import mock

from test_speakable import REPO_ROOT, _ServerEnv

sys.path.insert(0, str(REPO_ROOT / "app"))


class LangModuleTest(unittest.TestCase):
    def setUp(self):
        import lang
        self.lang = lang
        self.addCleanup(setattr, lang, "active", lang.active)

    def test_table(self):
        L = self.lang.LANGS
        self.assertEqual({k: (v["whisper"], v["locale"], v["date"]) for k, v in L.items()},
                         {"en": ("en", "en", "en-GB"), "nb": ("no", "nb", "nb-NO"), "pl": ("pl", "pl", "pl-PL")})

    def test_first_run_precedence(self):
        d = self.lang.detect
        self.assertEqual(d({"LC_ALL": "pl_PL.UTF-8", "LANG": "nb_NO.UTF-8"}), "pl")
        self.assertEqual(d({"LC_MESSAGES": "nb_NO.UTF-8", "LANG": "pl_PL.UTF-8"}), "nb")
        self.assertEqual(d({"LANG": "nn_NO.UTF-8"}), "nb")
        self.assertEqual(d({"LANG": "no_NO"}), "nb")
        self.assertEqual(d({"LC_ALL": "C", "LANG": "pl_PL.UTF-8"}), "en")    # the first one set wins, even when it is C
        self.assertEqual(d({"LANG": "de_DE.UTF-8"}), "en")
        self.assertEqual(d({}), "en")

    def test_t_falls_back_to_english_then_the_key(self):
        t = self.lang.t
        self.lang.active = "pl"                       # pl.json has no lines yet
        self.assertIn("Switching to Polski", t("lang.switching", language="Polski"))
        self.assertEqual(t("no.such.key"), "no.such.key")
        self.assertEqual(self.lang.norm("de"), "en")

    def test_clause(self):
        self.assertEqual(self.lang.clause("en"), "")
        self.assertIn("Norwegian", self.lang.clause("nb"))
        self.assertIn("Polish", self.lang.clause("pl"))


class LangServerTest(_ServerEnv):
    def setUp(self):
        s = self.server
        saved = dict(s.CFG)
        self.addCleanup(lambda: (s.CFG.clear(), s.CFG.update(saved)))
        self.addCleanup(setattr, s.lang, "active", s.lang.active)

    def test_first_run_writes_the_detected_language_and_an_existing_config_is_kept(self):
        s = self.server
        tmp = s.CONF_PATH.parent / "x"
        with mock.patch.object(s, "CONF_PATH", tmp / "config.json"), mock.patch.dict(s.os.environ, {"LC_ALL": "pl_PL.UTF-8"}):
            self.assertEqual(s.load_config()["language"], "pl")
            self.assertEqual(json.loads((tmp / "config.json").read_text())["language"], "pl")   # written at once
            (tmp / "config.json").write_text(json.dumps({"language": "en"}))
            with mock.patch.dict(s.os.environ, {"LC_ALL": "nb_NO.UTF-8"}):
                self.assertEqual(s.load_config()["language"], "en")

    def test_language_is_saved_but_active_stays(self):
        s = self.server
        s.lang.active = "en"
        with mock.patch.object(s.quick, "projects", return_value={}), mock.patch.object(s, "save_config", side_effect=lambda **kw: s.CFG.update(kw)):
            srv = s.ThreadingHTTPServer(("127.0.0.1", 0), s.Handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.addCleanup(srv.server_close)
            self.addCleanup(srv.shutdown)
            for lg in ("de", "pl"):             # an unknown language is ignored, a known one saved
                req = urllib.request.Request(f"http://127.0.0.1:{srv.server_port}/api/settings", data=json.dumps({"language": lg}).encode(),
                                             headers={"Content-Type": "application/json", "X-Nixi-Token": s.TOKEN})
                info = json.load(urllib.request.urlopen(req))
                self.assertEqual((info["language"], info["lang_active"]), ("en" if lg == "de" else "pl", "en"))
        self.assertIn("lines", info)

    def _fake_bridge(self, emit):
        s = self.server
        sent = []
        proc = mock.Mock(stdout=iter([]))
        with mock.patch.object(s.BRIDGE, "start", return_value=proc), mock.patch.object(s.BRIDGE, "send", side_effect=sent.append), \
                mock.patch.object(s, "location", return_value={"chosen": False}):
            try:
                s.run_bridge("hello", emit)
            except Exception:       # (the turn after the send needs a real bridge; the prompt is already out)
                pass
        return [m for m in sent if m.get("type") == "prompt"]

    def test_clause_in_the_four_paths(self):
        s = self.server
        for code, word in (("en", None), ("nb", "Norwegian"), ("pl", "Polish")):
            s.lang.active = code
            checks = {
                "bridge": (self._fake_bridge(lambda **k: None) or [{"text": ""}])[0]["text"],
                "follow": s.follow_prompt("hei"),
                "run_claude": " ".join(s.build_cmd("claude", False)),
            }
            with mock.patch.object(s, "claude_bin", return_value="claude"), mock.patch.object(s.subprocess, "run") as run:
                run.return_value.stdout = "x"
                s.summarize_command("ls")
                checks["summarize"] = run.call_args.kwargs["input"]
            for path, text in checks.items():
                if word:
                    self.assertIn(word, text, (code, path))
                else:
                    self.assertNotIn("Reply in", text, (code, path))


class LangVoiceTest(_ServerEnv):
    def setUp(self):
        s = self.server
        saved = dict(s.CFG)
        self.addCleanup(lambda: (s.CFG.clear(), s.CFG.update(saved)))
        self.addCleanup(setattr, s.lang, "active", s.lang.active)
        s.CFG.update(tts="auto", voice="girl", voice_by_lang={}, piper_voice="")

    def test_preset_voices_per_language(self):
        s = self.server
        s.lang.active = "pl"
        self.assertEqual(s.voice_preset()["piper"], "pl_PL-gosia-medium")
        s.CFG["voice"] = "guy"
        self.assertEqual(s.voice_preset()["piper"], "pl_PL-darkman-medium")
        s.CFG["voice"] = "robot"
        self.assertEqual(s.voice_preset()["espeak"], "pl+m3")
        s.lang.active = "nb"
        s.CFG["voice"] = "deep"
        self.assertEqual(s.voice_preset()["piper"], "no_NO-talesyntese-medium")
        s.CFG["voice"] = "robot"
        self.assertEqual(s.voice_preset()["espeak"], "nb+m3")
        s.lang.active = "en"
        s.CFG["voice"] = "girl"
        self.assertEqual(s.voice_preset()["piper"], "en_US-amy-medium")

    def test_auto_skips_kokoro_and_explicit_kokoro_says_why(self):
        s = self.server
        with mock.patch.object(s, "kokoro_ready", return_value=True), mock.patch.object(s, "piper_bin", return_value="p"), \
                mock.patch.object(s, "piper_voice", return_value="/v.onnx"):
            s.lang.active = "en"
            self.assertEqual(s.tts_engine(), "kokoro")
            s.lang.active = "pl"
            self.assertEqual(s.tts_engine(), "piper")
            s.CFG["tts"] = "kokoro"
            self.assertIsNone(s.tts_engine())
            with self.assertRaises(s.NoVoice) as cm:
                s.synth("cześć")
            self.assertEqual(cm.exception.reason, "Kokoro has no Polish voice")
            s.lang.active = "nb"
            with self.assertRaises(s.NoVoice) as cm:
                s.synth("hei")
            self.assertEqual(cm.exception.reason, "Kokoro has no Norwegian voice")

    def test_espeak_gets_the_language(self):
        s = self.server
        s.lang.active = "pl"
        s.CFG["tts"] = "espeak"
        with mock.patch.object(s.shutil, "which", return_value="/bin/espeak-ng"), mock.patch.object(s.subprocess, "run") as run, \
                mock.patch.object(s.Path, "read_bytes", return_value=b"w"):
            s.synth("cześć")
        self.assertEqual(run.call_args.args[0][:3], ["espeak-ng", "-v", "pl"])

    def test_voice_by_lang_remembers_and_restores(self):
        s = self.server
        saves = []
        with mock.patch.object(s, "save_config", side_effect=lambda **kw: (saves.append(kw), s.CFG.update(kw))):
            s.CFG["voice_by_lang"] = {"pl": "guy"}
            s.CFG["voice"] = "girl"
            s.restore_voice("pl")
            self.assertEqual(s.CFG["voice"], "guy")
            s.restore_voice("nb")                       # nothing remembered: the voice stays
            self.assertEqual(s.CFG["voice"], "guy")

    def test_voice_ready_and_fetch_sync(self):
        s = self.server
        with mock.patch.object(s, "piper_bin", return_value="p"), mock.patch.object(s.shutil, "which", return_value="/bin/espeak-ng"), \
                mock.patch.object(s, "voice_file") as vf:
            vf.return_value.exists.return_value = False
            self.assertFalse(s.voice_ready_for("pl"))            # piper is there but the Polish voice isn't downloaded: wait for it
            vf.return_value.exists.return_value = True
            self.assertTrue(s.voice_ready_for("pl"))
            s.CFG["tts"] = "kokoro"
            self.assertFalse(s.voice_ready_for("nb"))
        s.CFG["tts"] = "auto"
        self.assertEqual(s.lang_voice_name("nb"), "no_NO-talesyntese-medium")
        with mock.patch.object(s, "voice_file") as vf:
            vf.return_value.exists.return_value = True
            self.assertEqual(s.fetch_voice_sync("x-y-z", 1), (True, ""))
        with mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
            ok, why = s.fetch_voice_sync("pl_PL-nobody-medium", 1)
        self.assertFalse(ok)
        self.assertIn("offline", why)
        self.assertNotIn("pl_PL-nobody-medium", s._downloading)

    def test_plugin_stage_passes_the_locale(self):
        s = self.server
        s.lang.active = "pl"
        s.Plug.stage["x"] = object()
        self.addCleanup(s.Plug.stage.pop, "x", None)
        with mock.patch.object(s.plugins, "run_stage", return_value={"v": 1}) as rs, mock.patch.object(s, "stages_on", return_value=False):
            try:
                s.plugin_stage("x", "q")
            except Exception:       # (what happens to the result is not this test's business)
                pass
        self.assertEqual(rs.call_args.kwargs["locale"], "pl")

    def test_a_cached_english_result_does_not_answer_a_polish_ask(self):
        import plugins
        calls = []
        p = mock.Mock(id="p1", manifest={"stage": {"cache_seconds": 60}})
        with mock.patch.object(plugins, "_consented"), mock.patch.object(plugins, "peers_allowed", return_value=False), \
                mock.patch.object(plugins, "_launch", side_effect=lambda p_, q, loc, *a: calls.append(loc) or {"loc": loc}):
            plugins._cache.clear()
            self.assertEqual(plugins.run_stage(p, "q", locale="en"), {"loc": "en"})
            self.assertEqual(plugins.run_stage(p, "q", locale="pl"), {"loc": "pl"})
            self.assertEqual(plugins.run_stage(p, "q", locale="pl"), {"loc": "pl"})
        self.assertEqual(calls, ["en", "pl"])


if __name__ == "__main__":
    unittest.main()
