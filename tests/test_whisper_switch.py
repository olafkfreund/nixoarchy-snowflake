"""Language switches keep speech recognition and speech output on one active language."""
import threading
import time
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from test_speakable import _ServerEnv


class WhisperSwitchTest(_ServerEnv):
    def setUp(self):
        self.s = self.server
        self.old_cfg = dict(self.s.CFG)
        self.old_active = self.s.lang.active
        self.old_stt = self.s._stt
        self.old_whisper = self.s._whisper
        self.old_status = self.s.lang_status
        self.old_sg = self.s.sg
        self.old_bags = self.s.Quips.bags
        self.old_quips_data = self.s.Quips.data
        self.old_quips_mtime = self.s.Quips.mtime
        self.s.CFG.update(language="en", whisper_model="auto", stt_hint="Nixi")
        self.s.lang.active = "en"
        self.old = FakeModel("base.en")
        self.s._stt = (self.old, "en", "cpu")
        self.s._whisper = self.old
        self.s._whisper_err = None
        self.s.lang_status = ""

    def tearDown(self):
        self.s.CFG.clear()
        self.s.CFG.update(self.old_cfg)
        self.s.lang.active = self.old_active
        self.s._stt = self.old_stt
        self.s._whisper = self.old_whisper
        self.s.lang_status = self.old_status
        self.s.sg = self.old_sg + 100  # invalidate any late worker
        self.s.Quips.bags = self.old_bags
        self.s.Quips.data = self.old_quips_data
        self.s.Quips.mtime = self.old_quips_mtime

    def switch(self, code, loader, fetch=lambda name: (True, "")):
        with mock.patch.object(self.s, "_load", side_effect=loader), mock.patch.object(self.s, "_gpu_ok", return_value=False), \
             mock.patch.object(self.s, "fetch_voice_sync", side_effect=fetch), mock.patch.object(self.s, "lang_voice_name", side_effect=lambda c: "voice-" + c), \
             mock.patch.object(self.s, "restore_voice"), mock.patch.object(self.s, "voice_ready_for", return_value=True), mock.patch.object(self.s.Speaker, "say"):
            self.s.request_language(code)
            wait_until(lambda: self.s.lang_status in ("download failed", "") or self.s.lang.active == code)
            return self.s.lang_status

    def test_old_language_while_voice_downloads_then_switches(self):
        waiting, release = threading.Event(), threading.Event()
        def fetch(name):
            waiting.set()
            release.wait(2)
            return True, ""
        with mock.patch.object(self.s, "_load", return_value=FakeModel("base")), mock.patch.object(self.s, "_gpu_ok", return_value=False), \
             mock.patch.object(self.s, "fetch_voice_sync", side_effect=fetch), mock.patch.object(self.s, "lang_voice_name", return_value="voice-pl"), \
             mock.patch.object(self.s, "restore_voice"), mock.patch.object(self.s, "voice_ready_for", return_value=True), mock.patch.object(self.s.Speaker, "say") as say, mock.patch.object(self.s.BUS, "pub") as pub:
            self.s.request_language("pl")
            self.assertTrue(waiting.wait(2))
            self.assertIn("Switching to Polski", self.s.lang_status)
            self.assertEqual(self.s.run_whisper("audio"), "heard")
            self.assertEqual(self.old.languages, ["en"])
            self.assertEqual(self.s.lang.active, "en")
            say.assert_not_called()
            self.assertEqual(pub.call_args.kwargs["t"], "remind")
            release.set()
            self.assertTrue(wait_until(lambda: self.s.lang.active == "pl"))
            self.assertEqual(self.s.run_whisper("audio"), "heard")
            self.assertEqual(self.s._stt[0].languages, ["pl"])

    def test_superseded_pl_finishing_last_cannot_install(self):
        pl_started, release = threading.Event(), threading.Event()
        def load(dev, code):
            if code == "pl":
                pl_started.set()
                release.wait(2)
            return FakeModel("base")
        with mock.patch.object(self.s, "_load", side_effect=load), mock.patch.object(self.s, "_gpu_ok", return_value=False), \
             mock.patch.object(self.s, "fetch_voice_sync", return_value=(True, "")), mock.patch.object(self.s, "lang_voice_name", return_value="voice"), \
             mock.patch.object(self.s, "restore_voice"), mock.patch.object(self.s, "voice_ready_for", return_value=True), mock.patch.object(self.s.Speaker, "say"):
            self.s.request_language("pl")
            self.assertTrue(pl_started.wait(2))
            self.s.request_language("nb")
            self.assertTrue(wait_until(lambda: self.s.lang.active == "nb"))
            release.set()
            time.sleep(.05)
            self.assertEqual(self.s.lang.active, "nb")
            self.assertEqual(self.s._stt[1], "nb")
            self.s.run_whisper("audio")
            self.assertEqual(self.s._stt[0].languages, ["no"])

    def test_download_failure_keeps_old_pair_and_reports_reason(self):
        self.switch("pl", lambda *args: FakeModel("base"), lambda name: (False, "download failed"))
        self.assertTrue(wait_until(lambda: self.s.lang_status == "download failed"))
        self.assertIs(self.s._stt[0], self.old)
        self.assertEqual(self.s.lang.active, "en")

    def test_failed_request_is_not_replayed_on_restart(self):
        s = self.s
        path = s.CONF_PATH.parent / "failed-switch.json"
        with mock.patch.object(s, "CONF_PATH", path), mock.patch.object(s, "_load", return_value=FakeModel("base")), \
             mock.patch.object(s, "_gpu_ok", return_value=False), mock.patch.object(s, "fetch_voice_sync", return_value=(False, "offline")), \
             mock.patch.object(s, "lang_voice_name", return_value="voice-pl"):
            path.write_text(json.dumps({"language": "pl", "lang_good": "en"}))
            s.CFG.update(language="pl", lang_good="en")
            s.request_language("pl")
            self.assertTrue(wait_until(lambda: s.lang_status == "offline"))
            self.assertEqual((s.load_config()["language"], s.load_config()["lang_good"]), ("en", "en"))

    def test_active_choice_is_no_op_and_cancels_pending_switch(self):
        s = self.s
        with mock.patch.object(s, "_load") as load, mock.patch.object(s.BUS, "pub") as pub:
            s.request_language("en")
            load.assert_not_called()
            pub.assert_not_called()
            self.assertEqual(s.lang_status, "")

    def test_kokoro_rejects_polish_before_voice_fetch(self):
        s = self.s
        s.CFG["tts"] = "kokoro"
        with mock.patch.object(s, "_load", return_value=FakeModel("base")) as load, mock.patch.object(s, "_gpu_ok", return_value=False), \
             mock.patch.object(s, "fetch_voice_sync") as fetch:
            s.request_language("pl")
            self.assertTrue(wait_until(lambda: s.lang_status == "Kokoro has no Polish voice"))
            load.assert_not_called()
            fetch.assert_not_called()

    def test_switch_back_restores_english_preset(self):
        s = self.s
        s.CFG.update(tts="off", voice="girl", voice_by_lang={})
        with mock.patch.object(s, "_load", return_value=FakeModel("base")), mock.patch.object(s, "_gpu_ok", return_value=False):
            s.request_language("pl")
            self.assertTrue(wait_until(lambda: s.lang.active == "pl"))
            s.save_config(voice="guy", voice_by_lang={**s.CFG["voice_by_lang"], "pl": "guy"})
            s.request_language("en")
            self.assertTrue(wait_until(lambda: s.lang.active == "en"))
            self.assertEqual(s.CFG["voice"], "girl")

    def test_off_switch_never_fetches_piper(self):
        s = self.s
        s.CFG["tts"] = "off"
        with mock.patch.object(s, "_load", return_value=FakeModel("base")), mock.patch.object(s, "_gpu_ok", return_value=False), \
             mock.patch.object(s, "fetch_voice_sync") as fetch:
            s.request_language("pl")
            self.assertTrue(wait_until(lambda: s.lang.active == "pl"))
            fetch.assert_not_called()

    def test_voice_click_during_switch_keeps_both_presets(self):
        s = self.s
        loading, release = threading.Event(), threading.Event()
        s.CFG.update(tts="off", voice="girl", voice_by_lang={"pl": "girl"})
        def load(*_):
            loading.set()
            release.wait(2)
            return FakeModel("base")
        with mock.patch.object(s, "_load", side_effect=load), mock.patch.object(s, "_gpu_ok", return_value=False), \
             mock.patch.object(s.Wake, "ensure"), mock.patch.object(s, "state_info", return_value={}), \
             mock.patch.object(s.quick, "projects", return_value={}):
            s.request_language("pl")
            self.assertTrue(loading.wait(2))
            handler = s.Handler.__new__(s.Handler)
            handler.path = "/api/settings"
            handler.headers = {"X-Nixi-Token": s.TOKEN, "Host": "localhost"}
            with mock.patch.object(handler, "_body", return_value=b'{"voice":"guy"}'), \
                 mock.patch.object(handler, "_json", side_effect=lambda obj, code=200: obj):
                handler.do_POST()
            release.set()
            self.assertTrue(wait_until(lambda: s.lang.active == "pl"))
            self.assertEqual((s.CFG["voice_by_lang"]["en"], s.CFG["voice"]), ("guy", "girl"))

    def test_snapshot_survives_switch_and_cpu_retry_cannot_replace_new_pair(self):
        started, release = threading.Event(), threading.Event()
        old = FakeModel("small.en", fail_cuda=True, started=started, release=release)
        self.s._stt = (old, "en", "cuda")
        self.s._whisper = old
        result = []
        with mock.patch.object(self.s, "_load", side_effect=lambda dev, code: FakeModel("base")), mock.patch.object(self.s, "_gpu_ok", return_value=False), \
             mock.patch.object(self.s, "fetch_voice_sync", return_value=(True, "")), mock.patch.object(self.s, "lang_voice_name", return_value="voice"), \
             mock.patch.object(self.s, "restore_voice"), mock.patch.object(self.s, "voice_ready_for", return_value=True), mock.patch.object(self.s.Speaker, "say"):
            thread = threading.Thread(target=lambda: result.append(self.s.run_whisper("audio")))
            thread.start()
            self.assertTrue(started.wait(2))
            self.s.request_language("pl")
            self.assertTrue(wait_until(lambda: self.s.lang.active == "pl"))
            new = self.s._stt
            release.set()
            thread.join(2)
            self.assertEqual(result, ["heard"])
            self.assertIs(self.s._stt, new)
            self.assertEqual(self.s._stt[1], "pl")
            self.assertEqual(old.languages, ["en"])
            self.s.run_whisper("audio")
            self.assertEqual(new[0].languages, ["pl"])

    def test_multilingual_model_and_hallucinations(self):
        with mock.patch.dict("sys.modules", {"faster_whisper": SimpleNamespace(WhisperModel=FakeModel)}):
            self.s.CFG["whisper_model"] = "base.en"
            with self.assertRaises(ValueError):
                self.s._load("cpu", "pl")
            self.s.CFG["whisper_model"] = "auto"
            self.assertEqual(self.s._load("cpu", "nb").name, "base")
        for code, phrase in (("pl", "Napisy stworzone przez społeczność Amara.org"), ("pl", "Dziękuję."),
                             ("nb", "Teksting av"), ("nb", "Takk for meg.")):
            model = FakeModel("base", text=phrase)
            self.s._stt = (model, code, "cpu")
            self.s._whisper = model
            self.assertEqual(self.s.run_whisper("audio"), "")
            self.assertEqual(model.languages, [self.s.lang.LANGS[code]["whisper"]])

    def test_english_prompt_has_one_wake_phrase(self):
        model = FakeModel("base.en")
        self.s._stt = (model, "en", "cpu")
        self.s._whisper = model
        self.s.CFG["stt_hint"] = self.s.DEFAULTS["stt_hint"]
        self.s.run_whisper("audio")
        self.assertEqual(model.prompts[-1], self.s.DEFAULTS["stt_hint"])

    def test_quip_bag_is_per_language(self):
        root = Path(self.tmp) / "quips-test"
        root.mkdir(exist_ok=True)
        (root / "quips.json").write_text('{"done":["English"],"break":["Stretch"]}')
        (root / "quips.pl.json").write_text('{"done":["Polski"]}')
        with mock.patch.object(self.s.Quips, "path", root / "quips.json"), mock.patch.object(self.s.Plug, "ensure"):
            self.s.Quips.data = None
            self.s.Quips.bags = {}
            self.assertEqual(self.s.quip("done"), "English")
            self.s.lang.active = "pl"
            self.assertEqual(self.s.quip("done"), "Polski")
            self.assertEqual(self.s.quip("break"), "Stretch")  # English event fallback


class FakeModel:
    def __init__(self, name, device="cpu", compute_type="int8", text="heard", fail_cuda=False, started=None, release=None):
        self.name, self.text, self.fail_cuda = name, text, fail_cuda
        self.started, self.release = started, release
        self.languages = []
        self.prompts = []
        self._nixi_name, self._nixi_dev, self._nixi_ct = name, device, compute_type

    def transcribe(self, audio, **kw):
        self.languages.append(kw["language"])
        self.prompts.append(kw["initial_prompt"])
        if self.started:
            self.started.set()
            self.release.wait(2)
        if self.fail_cuda:
            raise RuntimeError("CUDA failed")
        return [SimpleNamespace(text=self.text)], None


def wait_until(predicate):
    end = time.monotonic() + 2
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(.01)
    return False
