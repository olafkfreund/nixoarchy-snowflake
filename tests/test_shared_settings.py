"""Shared settings load before local overrides and can be reset without touching HOME."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from test_speakable import _ServerEnv


class SharedSettingsTest(_ServerEnv):
    def setUp(self):
        self.s = self.server
        self.path = Path(self.tmp) / self.id().split(".")[-1] / "config.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(self.s, "CONF_PATH", self.path).start()
        mock.patch.object(self.s, "SHARED", {}).start()
        saved = dict(self.s.CFG)
        self.addCleanup(lambda: (self.s.CFG.clear(), self.s.CFG.update(saved)))

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

    def test_refuses_unshared_key_and_other_token(self):
        with mock.patch.object(self.s, "SHARED", {"voice": "girl"}):
            self.assertEqual(self.post("port")[0], 400)
            self.assertEqual(self.post("voice", "bad")[0], 403)
        self.popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
