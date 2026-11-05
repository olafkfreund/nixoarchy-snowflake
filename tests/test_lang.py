"""#177 step 1: LANGS, t(), the first-run default, the language setting, and lang_clause in the four agent paths."""
import json
import string
import sys
import threading
import urllib.request
import unittest
from pathlib import Path
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
        self.lang.active = "pl"
        with mock.patch.dict(self.lang.load("pl")["lines"]):
            del self.lang.load("pl")["lines"]["lang.switching"]       # a line pl lacks: English answers
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

    def test_saved_request_starts_from_last_good_language(self):
        s = self.server
        path = s.CONF_PATH.parent / "restart-config.json"
        with mock.patch.object(s, "CONF_PATH", path):
            path.write_text(json.dumps({"language": "pl", "lang_good": "en"}))
            self.assertEqual((s.load_config()["language"], s.load_config()["lang_good"]), ("pl", "en"))
            path.write_text(json.dumps({"language": "pl", "whisper_model": "small.en"}))
            cfg = s.load_config()
            self.assertEqual((cfg["language"], cfg["lang_good"], cfg["whisper_model"]), ("pl", "en", "auto"))

    def test_requested_words_wait_for_active_switch(self):
        s = self.server
        s.CFG["language"] = "en"
        s.lang.active = "pl"
        self.assertEqual(s.stages.fast_path("otwórz pierwszy", {"kind": "headlines", "items": [0]}, None), ("open", 0))
        self.assertIsNotNone(s._stop_re(s.stages.lang_active()).fullmatch("cicho"))
        s.lang.active = "en"
        self.assertIsNone(s.stages.fast_path("otwórz pierwszy", {"kind": "headlines", "items": [0]}, None))
        self.assertIsNone(s._stop_re(s.stages.lang_active()).fullmatch("cicho"))

    def test_language_is_saved_but_active_stays(self):
        s = self.server
        s.lang.active = "en"
        with mock.patch.object(s.quick, "projects", return_value={}), mock.patch.object(s, "save_config", side_effect=lambda **kw: s.CFG.update(kw)), \
             mock.patch.object(s, "request_language") as request, mock.patch.object(s.Wake, "ensure"):
            handler = s.Handler.__new__(s.Handler)
            handler.path = "/api/settings"
            handler.headers = {"X-Nixi-Token": s.TOKEN, "Host": "localhost"}
            for lg in ("de", "pl"):             # an unknown language is ignored, a known one saved
                with mock.patch.object(handler, "_body", return_value=json.dumps({"language": lg}).encode()), \
                     mock.patch.object(handler, "_json", side_effect=lambda obj, code=200: obj):
                    info = handler.do_POST()
                self.assertEqual((info["language"], info["lang_active"]), ("en" if lg == "de" else "pl", "en"))
            request.assert_called_once_with("pl", force=False)
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
        with mock.patch.object(s, "piper_bin", return_value="/bin/piper"):   # (without piper there is nothing to download)
            self.assertEqual(s.lang_voice_name("nb"), "no_NO-talesyntese-medium")
        with mock.patch.object(s, "voice_file") as vf:
            vf.return_value.exists.return_value = True
            self.assertEqual(s.fetch_voice_sync("x-y-z", 1), (True, ""))
        with mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
            ok, why = s.fetch_voice_sync("pl_PL-nobody-medium", 1)
        self.assertFalse(ok)
        self.assertIn("offline", why)
        self.assertNotIn("pl_PL-nobody-medium", s._downloading)

    def test_switch_voice_depends_on_selected_engine(self):
        s = self.server
        with mock.patch.object(s, "piper_bin", return_value=None), mock.patch.object(s.shutil, "which", return_value="/bin/espeak-ng"):
            for mode in ("espeak", "off"):
                s.CFG["tts"] = mode
                self.assertIsNone(s.lang_voice_name("pl"))
                self.assertTrue(s.voice_ready_for("pl"))
            s.CFG.update(tts="elevenlabs", eleven_on=True, eleven_voice="abcdefghij1234")
            with mock.patch.object(s.eleven, "has_key", return_value=True):
                self.assertIsNone(s.lang_voice_name("pl"))
                self.assertTrue(s.voice_ready_for("pl"))
                self.assertTrue(s.voice_ready_for("en"))
            s.CFG["tts"] = "kokoro"
            self.assertIsNone(s.lang_voice_name("pl"))
            self.assertFalse(s.voice_ready_for("pl"))
            s.CFG["tts"] = "auto"
            self.assertIsNone(s.lang_voice_name("en"))
            self.assertTrue(s.voice_ready_for("en"))

    def test_parallel_voice_fetch_starts_once(self):
        s = self.server
        name = "pl_PL-gosia-medium"
        s._downloading.discard(name)
        fake = mock.Mock()
        fake.exists.side_effect = lambda: (threading.Event().wait(.03), False)[1]
        a = threading.Thread(target=s.fetch_voice, args=(name,))
        b = threading.Thread(target=s.fetch_voice, args=(name,))
        with mock.patch.object(s, "voice_file", return_value=fake), mock.patch.object(s.threading, "Thread") as worker:
            a.start(); b.start(); a.join(); b.join()
            worker.assert_called_once()
        s._downloading.discard(name)

    def test_approval_falls_back_when_english_description_is_all_we_have(self):
        s = self.server
        s.lang.active = "pl"
        with mock.patch.object(s, "summarize_command", return_value=None):
            self.assertEqual(s.approval_say("Bash", {"description": "delete the file", "command": "rm x"}), s.lang.t("approve.command"))
        self.assertEqual(s.bridge_question("rm x", "delete the file"), s.lang.t("approve.command"))
        with mock.patch.object(s, "claude_bin", return_value="claude"), mock.patch.object(s.subprocess, "run") as run:
            run.return_value.stdout = "usuń plik"
            s.summarize_command("rm x")
            self.assertIn("infinitive verb in the reply language", run.call_args.kwargs["input"])

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


class SwitchVoiceChoiceTest(_ServerEnv):
    """Codex on PR #42: only a voice of the right language counts, and nothing is downloaded that can't be used."""
    def setUp(self):
        s = self.server
        saved = dict(s.CFG)
        self.addCleanup(lambda: (s.CFG.clear(), s.CFG.update(saved)))
        self.addCleanup(setattr, s.lang, "active", s.lang.active)
        s.CFG.update(tts="auto", voice="girl", voice_by_lang={}, piper_voice="")
        self.vdir = s.DATA_DIR / "voices"
        self.vdir.mkdir(parents=True, exist_ok=True)
        for f in self.vdir.glob("*.onnx"):
            f.unlink()
        self.addCleanup(lambda: [f.unlink() for f in self.vdir.glob("*.onnx")])

    def test_only_a_polish_voice_doesnt_make_english_ready(self):
        s = self.server
        (self.vdir / "pl_PL-gosia-medium.onnx").write_bytes(b"x")
        s.lang.active = "en"
        with mock.patch.object(s, "piper_bin", return_value="/bin/piper"), mock.patch.object(s, "kokoro_ready", return_value=False), \
                mock.patch.object(s.shutil, "which", return_value=None):
            self.assertIsNone(s.piper_voice())
            self.assertFalse(s.voice_ready_for("en"))
            self.assertEqual(s.lang_voice_name("en"), s.VOICES["girl"]["piper"])
            (self.vdir / (s.VOICES["girl"]["piper"] + ".onnx")).write_bytes(b"x")
            self.assertTrue(s.voice_ready_for("en"))
        s.lang.active = "pl"
        self.assertTrue(s.piper_voice().endswith("pl_PL-gosia-medium.onnx"))

    def test_no_piper_binary_means_no_download_and_espeak_speaks(self):
        s = self.server
        with mock.patch.object(s, "piper_bin", return_value=None), mock.patch.object(s, "kokoro_ready", return_value=False), \
                mock.patch.object(s.shutil, "which", return_value="/bin/espeak-ng"):
            self.assertIsNone(s.lang_voice_name("pl"))
            self.assertTrue(s.voice_ready_for("pl"))


class LinesTest(unittest.TestCase):
    """#177 step 5: every English line has a Bokmål and a Polish one, with the same slots; quips per language."""
    ALLOWED_ENGLISH = set()                              # keys that may stay English in nb/pl

    def setUp(self):
        import lang
        self.lang = lang
        self.addCleanup(setattr, lang, "active", lang.active)

    def slots(self, s):
        return {f for _, f, _, _ in string.Formatter().parse(s) if f}

    def test_every_key_is_translated_with_the_same_slots(self):
        en = self.lang.load("en")["lines"]
        for code in ("nb", "pl"):
            mine = self.lang.load(code)["lines"]
            self.assertEqual(set(mine) - set(en), set(), code)
            for k, v in en.items():
                if k in self.ALLOWED_ENGLISH:
                    continue
                self.assertIn(k, mine, (code, k))
                self.assertEqual(self.slots(mine[k]), self.slots(v), (code, k))
            self.assertEqual(self.lang.load(code)["_review"],
                             ["page.agents", "page.agents_hint", "page.agents_empty", "page.agent_replay", "page.agent_more"], code)

    def test_t_speaks_the_active_language(self):
        self.lang.active = "nb"
        self.assertEqual(self.lang.t("approve.change", name="a.py"), "Kan jeg endre a.py?")
        self.lang.active = "pl"
        self.assertEqual(self.lang.t("stage.done"), "Gotowe.")


class ServerLinesTest(_ServerEnv):
    def setUp(self):
        self.addCleanup(setattr, self.server.lang, "active", self.server.lang.active)

    def test_the_spoken_literals_follow_the_language(self):
        S = self.server
        S.lang.active = "en"
        self.assertEqual(S.say_path("/home/me/Downloads"), "your Downloads folder")
        self.assertEqual(S.approval_say("WebSearch", {}), "Can I search the web?")
        self.assertEqual(S.bridge_question("t", "Print the file."), "Can I print the file?")
        S.lang.active = "nb"
        self.assertEqual(S.say_path("/home/me/Downloads"), "Downloads-mappen din")
        self.assertEqual(S.approval_say("WebFetch", {"url": "https://www.x.org/a"}), "Kan jeg åpne en side på x.org?")
        self.assertEqual(S.speakable("se https://x.org nå"), "se en lenke nå")
        S.lang.active = "pl"
        self.assertEqual(S.say_path("~"), "Home")
        self.assertEqual(S.approval_say("WebSearch", {}), "Czy mogę poszukać w sieci?")


class QuipFilesTest(_ServerEnv):
    EVENTS = ("break", "welcome", "ram", "cpu", "rain", "snow", "night", "party", "coding", "done")

    def setUp(self):
        S = self.server
        self.addCleanup(setattr, S.lang, "active", S.lang.active)

    def test_refill_uses_the_cached_merged_file(self):
        S = self.server
        S.lang.active = "pl"
        S.Quips.data = None
        first = S.Quips.lines("done")
        with mock.patch.object(Path, "read_text", side_effect=AssertionError("second read")):
            self.assertEqual(S.Quips.lines("done"), first)
        self.addCleanup(S.Quips.bags.clear)

    def test_the_shipped_files_cover_every_event(self):
        for code in ("nb", "pl"):
            d = json.loads((self.server.APP_DIR / f"quips.{code}.json").read_text(encoding="utf-8"))
            self.assertNotIn("_review", d, code)    # (the user's native check cleared them, 2026-11-04)
            self.assertEqual(set(d), set(self.EVENTS), code)
            for event, lines in d.items():
                self.assertTrue(3 <= len(lines) <= 5, (code, event))
                for line in lines:
                    line.format(n=1)

    def test_quips_follow_the_active_language_with_an_english_fallback(self):
        S = self.server
        for code in ("nb", "pl"):
            S.lang.active = code
            native = json.loads((S.APP_DIR / f"quips.{code}.json").read_text(encoding="utf-8"))
            for event in self.EVENTS:
                self.assertTrue(set(native[event]) <= set(S.Quips.lines(event)), (code, event))
                self.assertFalse(set(S.QUIP_FALLBACK[event]) & set(S.Quips.lines(event)), (code, event))
        S.lang.active = "pl"
        self.assertIn(S.quip("done"), json.loads((S.APP_DIR / "quips.pl.json").read_text(encoding="utf-8"))["done"])
        S.lang.active = "en"
        self.assertIn(S.quip("done"), S.Quips.lines("done"))
        self.assertFalse(set(S.Quips.lines("done")) & set(json.loads((S.APP_DIR / "quips.pl.json").read_text(encoding="utf-8"))["done"]))

    def test_a_missing_file_or_event_falls_back_to_english(self):
        S = self.server
        tmp = Path(self.tmp) / "q"
        tmp.mkdir(exist_ok=True)
        (tmp / "quips.json").write_text(json.dumps({"snow": ["en snow"], "done": ["en done"]}))
        (tmp / "quips.pl.json").write_text(json.dumps({"snow": ["pl snow"]}))
        with mock.patch.object(S.Quips, "path", tmp / "quips.json"):
            S.Quips.data, S.Quips.mtime = None, None
            self.addCleanup(setattr, S.Quips, "data", None)
            S.lang.active = "pl"
            self.assertEqual(S.Quips.lines("snow"), ["pl snow"])
            self.assertEqual(S.Quips.lines("done"), ["en done"])              # event missing in pl
            S.lang.active = "nb"
            self.assertEqual(S.Quips.lines("snow"), ["en snow"])              # no nb file at all


if __name__ == "__main__":
    unittest.main()
