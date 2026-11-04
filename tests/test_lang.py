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


if __name__ == "__main__":
    unittest.main()
