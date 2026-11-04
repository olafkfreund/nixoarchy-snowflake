"""#149 A4: the /api/companion-plugins logic (the HTTP layer only checks the window token and calls these)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_speakable import _ServerEnv

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="3"/></svg>'


class PluginRoutesTest(_ServerEnv):
    def setUp(self):
        S = self.server
        self.root = Path(tempfile.mkdtemp(dir=self.tmp))
        self.state = S.plugins.State(self.root / "st.json")
        for target, val in (("plugin_dirs", lambda: [self.root / "pk"]), ("State", lambda *a: self.state)):
            mock.patch.object(S.plugins, target, val).start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(lambda: setattr(S.Plug, "loaded", None))
        S.Plug.loaded = None

    def mk(self, pid, **extra):
        d = self.root / "pk" / pid
        d.mkdir(parents=True, exist_ok=True)
        (d / "prop.svg").write_text(SVG)
        (d / "run").write_text("#!/bin/sh\n")
        (d / "plugin.json").write_text(json.dumps({"api": 1, "id": pid, "name": "<b>x</b>", "version": "1", **extra}))

    def items(self, got):
        return {i["id"]: i for i in got["items"]}

    def test_list_toggle_and_reload(self):
        S = self.server
        self.mk("hat-one", prop={"file": "prop.svg", "anchor": "head"}, notifications=[{"app": "element", "category": "chat"}])
        it = self.items(S.plugins_api())["hat-one"]
        self.assertEqual((it["name"], it["source"], it["enabled"], it["error"]), ("<b>x</b>", "Nix", False, ""))
        self.assertEqual(len(it["caps"]), 2)
        got = S.plugins_act({"id": "hat-one", "enabled": True})
        self.assertTrue(self.items(got)["hat-one"]["enabled"])
        self.assertEqual([p["id"] for p in S.Plug.props], ["hat-one"])        # applied without a restart
        self.assertTrue(self.state.get("hat-one")["enabled"])
        self.assertFalse(self.items(S.plugins_act({"id": "hat-one", "enabled": False}))["hat-one"]["enabled"])
        self.assertEqual(S.Plug.props, [])
        self.state.set("hat-one", True)                                        # edited on disk, then Reload
        self.assertEqual([p["id"] for p in S.Plug.props], [])
        S.plugins_act({"reload": True})
        self.assertEqual([p["id"] for p in S.Plug.props], ["hat-one"])

    def test_broken_listed_with_reason_and_refused(self):
        S = self.server
        self.mk("bad-one", surprise=1)
        (self.root / "pk" / "nojson").mkdir()
        got = S.plugins_api()
        it = self.items(got)["bad-one"]
        self.assertIn("unknown key", it["error"])
        self.assertEqual(it["caps"], [])
        self.assertIn("plugin.json missing", self.items(got)["nojson"]["error"])
        self.assertIn("broken", S.plugins_act({"id": "bad-one", "enabled": True})["error"])
        self.assertFalse(self.state.get("bad-one")["enabled"])

    def test_bad_requests(self):
        S = self.server
        self.assertIn("no such", S.plugins_act({"id": "nope-x", "enabled": True})["error"])
        self.mk("hat-one")
        self.assertIn("no such", S.plugins_act({"id": "hat-one", "enabled": "yes"})["error"])

    def test_dropped_prop_reason_is_listed(self):
        S = self.server
        self.mk("hat-one", prop={"file": "prop.svg", "anchor": "head"})
        (self.root / "pk" / "hat-one" / "prop.svg").write_text(SVG.replace("circle", "script"))
        S.plugins_act({"id": "hat-one", "enabled": True})
        it = self.items(S.plugins_api())["hat-one"]
        self.assertIn("element not allowed", it["error"])

    def test_odd_manifests_leave_the_others_working(self):
        S = self.server
        mock.patch.object(S.quick, "projects", return_value={}).start()
        self.mk("good-one", prop={"file": "prop.svg", "anchor": "head"})
        self.mk("odd-cat", notifications=[{"app": "x", "category": ["chat"]}])
        self.mk("odd-read", stage={"phrases": ["a b"], "argv": ["run"], "reads": [[1]]})
        S.plugins_act({"id": "good-one", "enabled": True})
        got = self.items(S.plugins_api())
        self.assertTrue(got["odd-cat"]["error"] and got["odd-read"]["error"])
        self.assertEqual([p["id"] for p in S.state_info()["plugin_props"]], ["good-one"])
        self.assertIn("broken", S.plugins_act({"id": "odd-cat", "enabled": True})["error"])

    def test_an_enabled_plugin_with_a_prop_error_can_be_switched_off(self):
        S = self.server
        self.mk("hat-one", prop={"file": "prop.svg", "anchor": "head"})
        S.plugins_act({"id": "hat-one", "enabled": True})
        (self.root / "pk" / "hat-one" / "prop.svg").write_text(SVG.replace("circle", "script"))
        it = self.items(S.plugins_act({"reload": True}))["hat-one"]
        self.assertTrue(it["enabled"] and it["error"])                        # the page keeps its switch usable
        self.assertFalse(self.items(S.plugins_act({"id": "hat-one", "enabled": False}))["hat-one"]["enabled"])

    def test_routes_need_the_window_token(self):
        import urllib.error
        import urllib.request
        S = self.server
        srv = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        S.threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            base = "http://127.0.0.1:%d" % srv.server_address[1]

            def call(path, method, token):
                req = urllib.request.Request(base + path, method=method, data=b"{}" if method == "POST" else None,
                                             headers={"X-Nixi-Token": token} if token else {})
                try:
                    with urllib.request.urlopen(req, timeout=5) as r:
                        return r.status
                except urllib.error.HTTPError as e:
                    return e.code
            for path, method in (("/api/companion-plugins", "GET"), ("/api/companion-plugins", "POST"),
                                 ("/api/companion-plugins/reload", "POST")):
                self.assertEqual(call(path, method, None), 403, (path, method))
                self.assertEqual(call(path, method, S.TOOL_TOKEN), 403, (path, method, "tool token"))
                self.assertEqual(call(path, method, S.TOKEN), 200, (path, method))
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
