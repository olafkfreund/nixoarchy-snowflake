"""#149 A2: quip packs and notification maps from enabled plugins."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_speakable import _ServerEnv


class PluginMapsTest(_ServerEnv):
    def setUp(self):
        S = self.server
        self.root = Path(tempfile.mkdtemp(dir=self.tmp))
        self.addCleanup(lambda: (setattr(S.Plug, "loaded", None), S.Quips.bags.clear()))
        self.state = S.plugins.State(self.root / "st.json")
        for target, val in (("plugin_dirs", lambda: [self.root / "pk"]), ("State", lambda *a: self.state)):
            p = mock.patch.object(S.plugins, target, val)
            p.start()
            self.addCleanup(p.stop)
        S.Plug.loaded = None

    def mk(self, pid, quips=None, notifications=None, on=True):
        d = self.root / "pk" / pid
        d.mkdir(parents=True, exist_ok=True)
        m = {"api": 1, "id": pid, "name": pid, "version": "1"}
        if quips is not None:
            m["quips"] = "quips.json"
            (d / "quips.json").write_text(json.dumps(quips))
        if notifications:
            m["notifications"] = notifications
        (d / "plugin.json").write_text(json.dumps(m))
        self.state.set(pid, on)
        self.server.Plug.loaded = None

    def test_pack_lines_only_while_enabled(self):
        S = self.server
        self.mk("pirates", {"snow": ["Arr, snow!"]}, on=False)
        self.assertNotIn("Arr, snow!", S.Quips.lines("snow"))
        self.mk("pirates", {"snow": ["Arr, snow!"]}, on=True)
        self.assertIn("Arr, snow!", S.Quips.lines("snow"))
        self.assertTrue(set(S.QUIP_FALLBACK["snow"]) <= set(S.Quips.lines("snow")))

    def test_pack_validation(self):
        S = self.server
        self.mk("pirates", {"snow": ["x" * 121, "tab\there", "{0.x}", "{a.b}", "ok {name}", "fine"], "bogus": ["no"]})
        got = S.Quips.lines("snow")
        for bad in ("x" * 121, "tab\there", "{0.x}", "{a.b}"):
            self.assertNotIn(bad, got)
        self.assertIn("ok {name}", got)
        self.assertIn("fine", got)
        self.assertEqual(S.Quips.lines("bogus"), [])

    def test_pack_capped_at_200_lines(self):
        self.mk("pirates", {"snow": [f"line {i}" for i in range(300)]})
        self.server.Plug.ensure()
        self.assertEqual(len(self.server.Plug.quips["snow"]), 200)

    def cats(self, *rows):
        rs = [{"key": f"n{i}", "category": "other", "app": a, "source": s} for i, (a, s) in enumerate(rows)]
        return [r["category"] for r in self.server.Inbox.rows(json.dumps(rs))]

    def test_notification_map(self):
        rows = (("Element", ""), ("x", "app.matrix.example.org"), ("x", "example.org"), ("whatsapp", ""), ("other", ""))
        self.assertEqual(self.cats(*rows), ["other", "other", "other", "chat", "other"])   # no map: Element is "other"
        self.mk("element-map", notifications=[{"app": "element", "category": "chat"}, {"host": "*.example.org", "category": "feed"}])
        self.assertEqual(self.cats(*rows), ["chat", "video", "other", "chat", "other"])

    def test_builtin_rules_win(self):
        self.mk("element-map", notifications=[{"app": "whatsapp", "category": "feed"}])
        self.assertEqual(self.cats(("whatsapp", "")), ["chat"])

    def mk_prop(self, pid, svg, on=True):
        d = self.root / "pk" / pid
        d.mkdir(parents=True, exist_ok=True)
        (d / "prop.svg").write_text(svg)
        (d / "plugin.json").write_text(json.dumps({"api": 1, "id": pid, "name": "<b>hat</b>", "version": "1",
                                                   "prop": {"file": "prop.svg", "anchor": "left", "layer": "back"}}))
        self.state.set(pid, on)
        self.server.Plug.loaded = None

    def test_props(self):
        S = self.server
        mock.patch.object(S.quick, "projects", return_value={}).start()
        self.addCleanup(mock.patch.stopall)
        ok = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="3" fill="acc"/></svg>'
        self.mk_prop("hat-one", ok, on=False)
        self.assertEqual(S.state_info()["plugin_props"], [])
        self.mk_prop("hat-one", ok)
        (p,) = S.state_info()["plugin_props"]
        self.assertEqual((p["id"], p["anchor"], p["layer"], p["name"]), ("hat-one", "left", "back", "<b>hat</b>"))
        self.assertEqual([n["tag"] for n in p["nodes"]], ["svg", "circle"])
        S.CFG["look"] = {"skin": "plug:hat-one"}
        self.assertEqual(S.look()["skin"], "plug:hat-one")
        S.CFG["look"] = {"skin": "plug:nope"}
        self.assertEqual(S.look()["skin"], "none")
        self.mk_prop("hat-one", ok.replace("<circle", "<script"))              # a bad prop is dropped whole
        self.assertEqual(S.state_info()["plugin_props"], [])
        self.assertIn("hat-one", S.Plug.prop_errors)
        S.CFG["look"] = {}


if __name__ == "__main__":
    unittest.main()
