"""Shared settings load before local overrides and can be reset without touching HOME."""
import hashlib
import io
import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from test_speakable import _ServerEnv


class _SharedBase(_ServerEnv):
    def setUp(self):
        self.s = self.server
        self.path = Path(self.tmp) / self.id().split(".")[-1] / "config.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(self.s, "CONF_PATH", self.path).start()
        mock.patch.object(self.s, "SHARED", {}).start()
        saved = dict(self.s.CFG)
        self.addCleanup(lambda: (self.s.CFG.clear(), self.s.CFG.update(saved)))


class SharedSettingsTest(_SharedBase):
    def test_every_default_has_one_rule_or_is_local(self):
        s = self.s
        self.assertFalse(s.LOCAL_ONLY & s.SHARED_OK)
        self.assertEqual(s.LOCAL_ONLY | s.SHARED_OK, set(s.DEFAULTS))
        self.assertEqual(set(s.SHARED_RULES), s.SHARED_OK)
        self.assertEqual(set(s.SHARED_RULES["voice"][1]), set(s.VOICES))
        self.assertEqual(set(s.SHARED_RULES["effort"][1]), set(s.EFFORTS))

    def test_layer_order_and_invalid_shared_data(self):
        s = self.s
        shared = self.path.with_name("shared.json")
        shared.write_text(json.dumps({"trust": "readonly", "size": 10, "port": 9999, "voice": "guy",
                                      "plugins_on": ["news"], "voices": {"en_US-amy-medium": {"onnx": "a" * 64, "json": "b" * 64}}}))
        settings, extras, notes = s.load_shared(shared)
        self.assertEqual(settings, {"trust": "readonly", "voice": "guy"})
        self.assertEqual(extras["plugins_on"], ["news"])
        self.assertEqual(extras["private_plugins"], [])
        self.assertIn("en_US-amy-medium", extras["voices"])
        self.assertEqual(len(notes), 2)
        self.path.write_text('{"trust":"trust"}')
        with mock.patch.object(s, "SHARED", settings):
            cfg = s.load_config()
        self.assertEqual((cfg["trust"], cfg["voice"], cfg["port"]), ("trust", "guy", s.DEFAULTS["port"]))
        self.assertEqual(s.load_shared(self.path.with_name("missing.json")), ({}, {"plugins_on": [], "private_plugins": [], "voices": {}}, []))
        shared.write_text("{")
        self.assertEqual(s.load_shared(shared)[:2], ({}, {"plugins_on": [], "private_plugins": [], "voices": {}}))
        self.assertTrue(s.load_shared(shared)[2])

    def test_first_run_writes_only_local_seed(self):
        s = self.s
        with mock.patch.dict(s.os.environ, {"LC_ALL": "pl_PL.UTF-8"}):
            self.assertEqual(s.load_config()["language"], "pl")
        self.assertEqual(json.loads(self.path.read_text()), {"lang_good": "en", "language": "pl"})
        self.path.unlink()
        with mock.patch.object(s, "SHARED", {"language": "nb"}):
            self.assertEqual(s.load_config()["language"], "nb")
        self.assertEqual(json.loads(self.path.read_text()), {"lang_good": "en"})

    def test_bridge_shared_and_local(self):
        s = self.s
        local = self.path.parent / "nixi.json"
        shared = local.with_name("nixi-shared.json")
        shared.write_text('{"trust":"mechanic","agent":"codex","permissionMode":"bad"}')
        local.write_text('{"agent":"claude"}')
        with mock.patch.object(s, "NIXI_CONF", local):
            self.assertEqual(s.nixi_conf(), {"trust": "mechanic", "agent": "claude"})

    def test_state_overrides_include_equal_values(self):
        s = self.s
        self.path.write_text('{"trust":"ask"}')
        with mock.patch.object(s, "SHARED", {"trust": "ask", "voice": "guy"}), \
             mock.patch.object(s.quick, "projects", return_value={}), mock.patch.object(s.Updates, "status", return_value={}):
            info = s.state_info()
        self.assertEqual(info["shared"], {"trust": "ask", "voice": "guy"})
        self.assertEqual(info["overrides"], ["trust"])


class ResetSharedSettingsTest(SharedSettingsTest):
    def setUp(self):
        super().setUp()
        self.srv = self.s.ThreadingHTTPServer(("127.0.0.1", 0), self.s.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.popen = mock.patch.object(self.s.subprocess, "Popen").start()

    def post(self, key, token=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.srv.server_port}/api/settings/reset",
                                     json.dumps({"key": key}).encode(),
                                     headers={"X-Nixi-Token": token or self.s.TOKEN})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_reset_voice_and_language_restore(self):
        s = self.s
        self.path.write_text('{"voice":"guy","voice_by_lang":{"en":"guy","pl":"cute"}}')
        s.CFG.update(voice="guy", voice_by_lang={"en": "guy", "pl": "cute"})
        with mock.patch.object(s, "SHARED", {"voice": "girl"}):
            self.assertEqual(self.post("voice"), (200, {"ok": True, "restart": True}))
            saved = json.loads(self.path.read_text())
            self.assertNotIn("voice", saved)
            self.assertEqual(saved["voice_by_lang"], {"pl": "cute"})
            s.restore_voice("pl")
            s.restore_voice("en")
            self.assertNotIn("voice", json.loads(self.path.read_text()))
        self.popen.assert_called_once()
        self.assertTrue(self.popen.call_args.kwargs["start_new_session"])

    def test_reset_notification_details_clears_images(self):
        s = self.s
        self.path.write_text('{"notify_details":true}')
        with mock.patch.object(s, "SHARED", {"notify_details": False}), mock.patch.object(s.NImage, "clear") as clear:
            self.assertEqual(self.post("notify_details")[0], 200)
        self.assertNotIn("notify_details", json.loads(self.path.read_text()))
        clear.assert_called_once()

    def test_reset_still_ok_when_restart_cannot_start(self):
        self.path.write_text('{"trust":"ask"}')
        self.popen.side_effect = OSError("no launcher")
        with mock.patch.object(self.s, "SHARED", {"trust": "readonly"}):
            self.assertEqual(self.post("trust"), (200, {"ok": True, "restart": False}))
        self.assertNotIn("trust", json.loads(self.path.read_text()))

    def test_refuses_unshared_key_and_other_token(self):
        with mock.patch.object(self.s, "SHARED", {"voice": "girl"}):
            self.assertEqual(self.post("port")[0], 400)
            self.assertEqual(self.post("voice", "bad")[0], 403)
        self.popen.assert_not_called()


class SharedLayerFixesTest(_SharedBase):
    LOOK = {"body": "#161616", "pupL": "#ffffff", "pupR": "#ffffff", "whiteL": "#eeeeee", "whiteR": "#eeeeee", "skin": "none",
            "skinColor": "", "link": True, "random": False, "follow_theme": True, "character": "robot"}

    def shared(self, data):
        f = self.path.with_name("shared.json")
        f.write_text(json.dumps(data))
        return self.s.load_shared(f)[0]

    def test_real_look_is_accepted_and_junk_is_not(self):
        self.assertEqual(self.shared({"look": self.LOOK}), {"look": self.LOOK})
        self.assertEqual(self.shared({"look": {**self.LOOK, "body": "red"}}), {})
        self.assertEqual(self.shared({"look": {**self.LOOK, "extra": 1}}), {})

    def test_legacy_permission_mode_does_not_override_shared_trust(self):
        s = self.s
        self.path.write_text('{"permission_mode":"plan"}')
        with mock.patch.object(s, "SHARED", {"trust": "ask"}):
            self.assertEqual(s.load_config()["trust"], "ask")
        self.assertEqual(s.load_config()["trust"], "readonly")

    def switch(self, code):
        s = self.s

        class Now:
            def __init__(self, target, daemon=None):
                self.target = target

            def start(self):
                self.target()
        with mock.patch.object(s.threading, "Thread", Now), mock.patch.object(s, "_load", return_value=object()), \
             mock.patch.object(s, "_gpu_ok", return_value=False), mock.patch.object(s, "fetch_voice_sync", return_value=(True, "")), \
             mock.patch.object(s, "lang_voice_name", return_value=""), mock.patch.object(s, "voice_ready_for", return_value=True), \
             mock.patch.object(s, "stt_names", return_value=[]), mock.patch.object(s.BUS, "pub"):
            s.request_language(code)

    def keep_lang_state(self):
        s = self.s
        old = (s.lang.active, s._stt, s._whisper, s.lang_status)
        self.addCleanup(lambda: (setattr(s.lang, "active", old[0]), setattr(s, "_stt", old[1]),
                                 setattr(s, "_whisper", old[2]), setattr(s, "lang_status", old[3])))

    def test_language_round_trip_keeps_shared_voice_out_of_config(self):
        s = self.s
        self.keep_lang_state()
        s.lang.active = "en"
        self.path.write_text("{}")
        s.CFG.update(voice="girl", voice_by_lang={"en": "girl", "pl": "cute"})
        with mock.patch.object(s, "SHARED", {"voice": "girl", "voice_by_lang": {"en": "girl", "pl": "cute"}}):
            self.switch("pl")
            self.assertEqual((s.lang.active, s.CFG["voice"]), ("pl", "cute"))
            self.switch("en")
            self.assertEqual((s.lang.active, s.CFG["voice"]), ("en", "girl"))
        saved = json.loads(self.path.read_text())
        self.assertNotIn("voice_by_lang", saved)
        self.assertNotIn("voice", saved)

    def test_shared_voice_by_lang_alone_is_not_saved_on_switch(self):
        s = self.s
        self.keep_lang_state()
        s.lang.active = "en"
        self.path.write_text("{}")
        s.CFG.update(voice="girl", voice_by_lang={"en": "guy"})
        with mock.patch.object(s, "SHARED", {"voice_by_lang": {"en": "guy"}}):
            self.switch("pl")
        self.assertNotIn("voice_by_lang", json.loads(self.path.read_text()))

    def test_restore_from_shared_voice_by_lang_alone_is_not_saved(self):
        s = self.s
        self.path.write_text("{}")
        s.CFG["voice_by_lang"] = {"pl": "cute"}
        with mock.patch.object(s, "SHARED", {"voice_by_lang": {"pl": "cute"}}):
            s.restore_voice("pl")
        self.assertEqual(s.CFG["voice"], "cute")
        self.assertNotIn("voice", json.loads(self.path.read_text()))

    def test_failed_switch_with_shared_language_is_not_saved(self):
        s = self.s
        self.keep_lang_state()
        s.lang.active = "en"
        self.path.write_text("{}")
        s.CFG["language"] = "pl"
        with mock.patch.object(s, "SHARED", {"language": "pl"}), mock.patch.object(s, "_load", side_effect=RuntimeError("no")):
            class Now:
                def __init__(self, target, daemon=None):
                    self.target = target

                def start(self):
                    self.target()
            with mock.patch.object(s.threading, "Thread", Now), mock.patch.object(s, "_gpu_ok", return_value=False), \
                 mock.patch.object(s.BUS, "pub"):
                s.request_language("pl")
        self.assertEqual(s.CFG["language"], "en")
        self.assertNotIn("language", json.loads(self.path.read_text()))


class SharedVoiceTest(_SharedBase):
    NAME = "en_US-amy-medium"

    def setUp(self):
        super().setUp()
        self.data = Path(self.tmp) / self.id().split(".")[-1] / "data"
        mock.patch.object(self.s, "DATA_DIR", self.data).start()
        self.good = {"onnx": b"model", "json": b"{}"}
        sha = {k: hashlib.sha256(v).hexdigest() for k, v in self.good.items()}
        mock.patch.object(self.s, "SHARED_EXTRAS", {"plugins_on": [], "private_plugins": [], "voices": {self.NAME: sha}}).start()
        self.urls = []
        self.served = dict(self.good)

    def urlopen(self, url, timeout=None):
        self.urls.append(url)
        return io.BytesIO(self.served["json" if url.endswith(".json") else "onnx"])

    def put(self, onnx, js):
        d = self.data / "voices"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{self.NAME}.onnx").write_bytes(onnx)
        (d / f"{self.NAME}.onnx.json").write_bytes(js)

    def sync(self):
        with mock.patch.object(self.s.urllib.request, "urlopen", self.urlopen):
            return self.s.fetch_voice_sync(self.NAME)

    def test_replacing_a_stale_voice_drops_its_cached_model(self):
        self.put(b"stale", b"{}")
        path = str(self.s.voice_file(self.NAME))
        self.s._PIPER[path] = "old model"
        self.addCleanup(self.s._PIPER.pop, path, None)
        self.assertEqual(self.sync(), (True, ""))
        self.assertNotIn(path, self.s._PIPER)

    def test_pinned_urls_and_matching_voice_kept(self):
        self.assertEqual(self.sync(), (True, ""))
        self.assertTrue(all(self.s.PIPER_REV in u and "/main/" not in u for u in self.urls) and len(self.urls) == 2)
        self.assertTrue(self.s.voice_ok(self.NAME))
        self.assertEqual(self.sync(), (True, ""))
        self.assertEqual(len(self.urls), 2)

    def test_stale_files_moved_aside_and_fetched_again(self):
        for onnx, js in ((b"old", self.good["json"]), (self.good["onnx"], b"old")):
            self.urls.clear()
            self.put(onnx, js)
            self.assertFalse(self.s.voice_ok(self.NAME))
            self.assertEqual(self.sync(), (True, ""))
            self.assertEqual(len(self.urls), 2)
            self.assertTrue(self.s.voice_ok(self.NAME))
        self.assertEqual(len(list((self.data / "voices" / ".stale").glob("*/*"))), 4)

    def test_mismatching_download_not_kept(self):
        self.served["onnx"] = b"bad"
        ok, why = self.sync()
        self.assertFalse(ok)
        self.assertEqual(list((self.data / "voices").glob(f"{self.NAME}*")), [])

    def test_pending_download_is_checked(self):
        self.put(b"old", b"old")
        self.s._downloading.add(self.NAME)
        self.addCleanup(self.s._downloading.discard, self.NAME)
        with mock.patch.object(self.s.time, "sleep", lambda _: self.s._downloading.discard(self.NAME)):
            self.assertEqual(self.sync()[0], False)

    def test_background_fetch_skips_good_voice_and_fetches_stale(self):
        self.put(self.good["onnx"], self.good["json"])
        with mock.patch.object(self.s.threading, "Thread") as t:
            self.s.fetch_voice(self.NAME)
        t.assert_not_called()
        self.put(b"old", b"old")
        with mock.patch.object(self.s.threading, "Thread") as t:
            self.s.fetch_voice(self.NAME)
        t.assert_called_once()
        self.s._downloading.discard(self.NAME)

    def test_unlisted_voice_needs_only_the_onnx(self):
        d = self.data / "voices"
        d.mkdir(parents=True)
        (d / "en_GB-alan-medium.onnx").write_bytes(b"x")
        self.assertTrue(self.s.voice_ok("en_GB-alan-medium"))
        self.assertFalse(self.s.voice_ok("en_GB-other-medium"))


class PluginsOnTest(_ServerEnv):
    def state(self, data=None, on=("news",)):
        plugins = self.server.plugins
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        if data is not None:
            (d / "s.json").write_text(json.dumps(data))
        return plugins.State(d / "s.json", plugins_on=on)

    def test_listed_id_without_entry_is_on(self):
        st = self.state()
        self.assertEqual(st.get("news"), {"enabled": True, "sha256": None})
        self.assertFalse(st.get("other")["enabled"])

    def test_explicit_off_wins(self):
        self.assertFalse(self.state({"news": {"enabled": False, "sha256": None}}).get("news")["enabled"])

    def test_folder_plugin_in_plugins_on_still_needs_hash_consent(self):
        plugins = self.server.plugins
        st = self.state()
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        (d / "plugin.json").write_text(json.dumps({"api": 1, "id": "news", "name": "N", "version": "1", "stage": {"cmd": ["x"]}}))
        p = mock.Mock(id="news", source="folder", error=None, manifest={"stage": {}}, dir=d)
        notes = plugins.review([p], st)
        self.assertEqual(notes, {"news": plugins.CHANGED})
        self.assertFalse(st.get("news")["enabled"])


    def test_inherited_nix_plugin_keeps_following_the_shared_list(self):
        plugins = self.server.plugins
        st = self.state()
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        (d / "plugin.json").write_text("{}")
        p = mock.Mock(id="news", source="nix", error=None, manifest={"stage": {}}, dir=d)
        plugins.review([p], st)
        self.assertNotIn("news", st.data)          # no local entry: dropping it from plugins_on turns it off


class MigrateTest(_SharedBase):
    def setUp(self):
        super().setUp()
        s = self.s
        root = self.path.parent
        self.nixi = root / "omarchy" / "nixi.json"
        self.nixi.parent.mkdir()
        self.data = root / "data"
        (self.data / "plugins" / "news").mkdir(parents=True)
        (self.data / "plugins" / "you").mkdir()
        self.nix_plugins = root / "pk"
        (self.nix_plugins / "news").mkdir(parents=True)
        (self.nix_plugins / "news" / "plugin.json").write_text(json.dumps({"api": 1, "id": "news", "name": "N", "version": "1"}))
        self.state = self.data / "plugins-state.json"
        self.backups = root / "backups"
        mock.patch.object(s, "NIXI_CONF", self.nixi).start()
        mock.patch.object(s, "DATA_DIR", self.data).start()
        mock.patch.object(s.plugins, "plugin_dirs", lambda: [self.nix_plugins, self.data / "plugins"]).start()
        mock.patch.object(s.plugins, "_in_store", lambda d: True).start()
        mock.patch.object(s, "SHARED", {"trust": "readonly", "voice": "guy"}).start()
        mock.patch.object(s, "SHARED_EXTRAS", {"plugins_on": ["news", "you"], "private_plugins": ["you"], "voices": {}}).start()
        self.idle = mock.patch.object(s, "_nixi_idle", return_value=True).start()
        self.start = mock.patch.object(s, "_nixi_start").start()
        (root / "omarchy" / "nixi-shared.json").write_text('{"trust":"mechanic","agent":"codex"}')
        self.path.write_text(json.dumps({"trust": "readonly", "voice": "girl", "size": self.s.DEFAULTS["size"], "port": 1234, "effort": "high"}))
        self.nixi.write_text(json.dumps({"trust": "guide", "agent": "codex", "model": "x", "other": 1}))
        self.state.write_text(json.dumps({"news": {"enabled": True, "sha256": "ab"}, "you": {"enabled": True, "sha256": "cd"},
                                          "off": {"enabled": False, "sha256": "ef"}}))

    def run_migrate(self, **kw):
        return self.s.settings_migrate(backup_root=self.backups, **kw)

    def j(self, p):
        return json.loads(p.read_text())

    def test_drops_equal_values_and_backs_up(self):
        before = [p.read_text() for p in (self.path, self.nixi, self.state)]
        self.assertEqual(self.run_migrate(drop_all=True), 0)
        self.assertEqual(self.j(self.path), {"port": 1234, "effort": "high"})
        self.assertEqual(self.j(self.nixi), {"model": "x", "other": 1})
        self.assertEqual(self.j(self.state), {"you": {"enabled": True, "sha256": "cd"}, "off": {"enabled": False, "sha256": "ef"}})
        (b,) = self.backups.glob("migrate-*")
        self.assertEqual([(b / n).read_text() for n in ("config.json", "nixi.json", "plugins-state.json")], before)
        self.start.assert_called_once()

    def test_explicit_trust_stays_while_legacy_permission_mode_does(self):
        s = self.s
        self.path.write_text(json.dumps({"trust": s.DEFAULTS["trust"], "permission_mode": "bypassPermissions"}))
        with mock.patch.object(s, "SHARED", {}):
            self.assertEqual(self.run_migrate(drop_all=True), 0)
            saved = self.j(self.path)
            self.assertEqual(saved["trust"], s.DEFAULTS["trust"])
            mock.patch.object(s, "CONF_PATH", self.path).start()
            self.assertEqual(s.load_config()["trust"], s.DEFAULTS["trust"])   # not re-derived as "trust"

    def test_keep_and_questions(self):
        asked = []
        self.assertEqual(self.run_migrate(keep=["voice"], ask=lambda q: asked.append(q) or False), 0)
        self.assertEqual(self.j(self.path), {"voice": "girl", "port": 1234, "effort": "high"})
        self.assertEqual(len(asked), 1)           # only the bridge's `trust` (guide vs mechanic) was asked about
        self.assertEqual(self.j(self.nixi), {"model": "x", "other": 1})

    def test_changed_mtime_on_second_file_replaces_nothing(self):
        before = [p.read_text() for p in (self.path, self.nixi, self.state)]
        real = self.s._read_obj
        calls = []

        def racing(path):
            calls.append(path)
            if len(calls) == 4 and path == self.path:          # the re-check pass: first file still fine
                pass
            if len(calls) == 5:                                  # second file changes before the check reads it
                self.nixi.write_text(self.nixi.read_text() + " ")
            return real(path)
        with mock.patch.object(self.s, "_read_obj", racing):
            self.assertEqual(self.run_migrate(drop_all=True), 1)
        self.assertEqual([p.read_text() for p in (self.path, self.state)], [before[0], before[2]])
        self.assertEqual(self.j(self.nixi), json.loads(before[1]))
        self.assertEqual(list(self.path.parent.glob("*.migrate.tmp")) + list(self.nixi.parent.glob("*.migrate.tmp")), [])
        self.start.assert_called_once()

    def test_failed_replace_restores_all(self):
        before = [p.read_text() for p in (self.path, self.nixi, self.state)]
        real = self.s.os.replace
        n = []

        def flaky(a, b):
            n.append(1)
            if len(n) == 2:
                raise OSError("disk")
            return real(a, b)
        with mock.patch.object(self.s.os, "replace", flaky):
            self.assertEqual(self.run_migrate(drop_all=True), 1)
        self.assertEqual([p.read_text() for p in (self.path, self.nixi, self.state)], before)

    def test_superseded_plugin_moves_and_private_stays(self):
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.run_migrate(drop_all=True)
        (b,) = self.backups.glob("migrate-*")
        self.assertTrue((b / "plugins" / "news").is_dir())
        self.assertFalse((self.data / "plugins" / "news").exists())
        self.assertTrue((self.data / "plugins" / "you").is_dir())
        undo = next(l for l in out.getvalue().splitlines() if l.startswith("undo"))
        self.assertIn(f"mv {b / 'plugins' / 'news'} {self.data / 'plugins' / 'news'}", undo)

    def test_did_not_stop_changes_nothing(self):
        self.idle.return_value = False
        self.assertEqual(self.run_migrate(drop_all=True), 1)
        self.assertEqual(self.j(self.nixi)["trust"], "guide")
        self.assertFalse(self.backups.exists())

    def test_reset_bridge(self):
        self.assertEqual(self.s.settings_reset_bridge(), 0)
        self.assertEqual(self.j(self.nixi), {"other": 1})
        self.start.assert_called_once()

    def test_doctor_section(self):
        import contextlib
        with mock.patch.object(self.s, "SHARED_NOTES", ["Ignored shared setting: junk"]), \
             mock.patch.object(self.s, "SHARED_EXTRAS", {"plugins_on": [], "private_plugins": ["gone"], "voices": {"en_US-amy-medium": {"onnx": "a" * 64, "json": "b" * 64}}}), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            self.s.doctor_shared()
        text = out.getvalue()
        for want in ("shared.json", "Ignored shared setting: junk", "override trust: 'readonly' → 'readonly'",
                     "override voice: 'girl' → 'guy'", "bridge override trust: 'guide' → 'mechanic'",
                     "private plugin missing: gone", "voice en_US-amy-medium: missing"):
            self.assertIn(want, text)


if __name__ == "__main__":
    unittest.main()
