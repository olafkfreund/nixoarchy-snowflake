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

    def mk(self, pid, quips=None, notifications=None, reactions=None, on=True):
        d = self.root / "pk" / pid
        d.mkdir(parents=True, exist_ok=True)
        m = {"api": 1, "id": pid, "name": pid, "version": "1"}
        if quips is not None:
            m["quips"] = "quips.json"
            (d / "quips.json").write_text(json.dumps(quips))
        if notifications:
            m["notifications"] = notifications
        if reactions is not None:
            m["reactions"] = reactions
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

    def test_reactions_settings_line(self):
        S = self.server
        self.mk("reaction-map", reactions=[{"app": "element", "reaction": "notice"}])
        (item,) = S.plugins_api()["items"]
        self.assertEqual(item["error"], "")
        self.assertIn("Reacts to notifications from some apps or sites", item["caps"])

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

    def test_the_examples_load_whole(self):
        S = self.server
        ex = Path(S.APP_DIR).parent / "plugins/examples"
        pack = json.loads((ex / "pirate-quips/quips.json").read_text())
        kept = S.Plug.clean(pack)
        self.assertEqual(kept, pack)                                          # no line dropped
        self.assertTrue(set(pack) <= set(S.QUIP_FALLBACK))                    # every event is a real one
        for d in sorted(ex.iterdir()):
            self.assertIsNone(S.plugins.check_dir(d), d.name)

    def ticks(self, rows, n=1, t0=1000.0):
        """Run Inbox.tick n times over the same shell reply; the published notify rows of the last run."""
        S = self.server
        got = []
        reply = json.dumps(rows)
        with mock.patch.object(S.Inbox, "want", return_value=True), mock.patch.object(S.Inbox, "call", return_value=reply), \
                mock.patch.object(S.BUS, "pub", side_effect=lambda **kw: got.append(kw)), \
                mock.patch.object(S.time, "monotonic", return_value=t0):
            for _ in range(n):
                S.Inbox.tick()
        return got

    def row(self, key, app="element", source="", **kw):
        return {"key": key, "category": "other", "app": app, "source": source, "summary": "secret", **kw}

    def setup_rx(self):
        S = self.server
        S.Inbox.rxkeys.clear()
        S.Inbox.rxat.clear()
        p = mock.patch.dict(S.CFG, {"proactive": True, "notify_details": False})   # (another test may leave notify_details on)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(lambda: (S.Inbox.rxkeys.clear(), S.Inbox.rxat.clear(), S.Inbox.unseen.clear()))

    def test_reaction_matches_app_and_host_only(self):
        self.setup_rx()
        self.mk("rx-map", reactions=[{"app": "element", "reaction": "music"}, {"host": "*.example.org", "reaction": "notice"}])
        S = self.server
        for n, (app, src, want) in enumerate([("x", "other.net", None), ("x", "example.org", None), ("Element", "", "music"),
                                              ("x", "app.example.org", "notice"), ("x", "https://a.example.org/p", "notice")]):
            S.Inbox.rxat.clear()                                         # (the 5-minute limit has its own test)
            (r,) = self.ticks([self.row(f"k{n}", app, src)])
            self.assertEqual(r.get("reaction"), want, (app, src))

    def test_reaction_outside_allowlist_refused(self):
        self.mk("rx-map", reactions=[{"app": "element", "reaction": "ask"}])
        (item,) = self.server.plugins_api()["items"]
        self.assertTrue(item["error"])

    def test_shell_reaction_key_dropped_and_row_unchanged(self):
        self.setup_rx()
        (r,) = self.ticks([self.row("a", reaction="music")])
        self.assertNotIn("reaction", r)
        self.assertEqual((r["category"], r["summary"]), ("other", ""))   # (no notify_details: text stays blank)

    def test_one_reaction_per_key_and_per_plugin_every_5_minutes(self):
        self.setup_rx()
        self.mk("rx-map", reactions=[{"app": "element", "reaction": "notice"}])
        S = self.server
        self.assertEqual([r.get("reaction") for r in self.ticks([self.row("a")], n=2)], ["notice", None])   # same key twice
        self.assertEqual([r.get("reaction") for r in self.ticks([self.row("b")], t0=1100.0)], [None])        # within 5 minutes
        self.assertEqual([r.get("reaction") for r in self.ticks([self.row("c")], t0=1301.0)], ["notice"])
        self.assertEqual(S.Inbox.rxat["rx-map"], 1301.0)

    def test_two_matching_plugins_give_one(self):
        self.setup_rx()
        self.mk("rx-one", reactions=[{"app": "element", "reaction": "music"}])
        self.mk("rx-two", reactions=[{"app": "element", "reaction": "notice"}])
        (r,) = self.ticks([self.row("a")])
        self.assertIn(r["reaction"], ("music", "notice"))
        self.assertEqual(len(self.server.Inbox.rxat), 1)

    def test_cut_source_long_command_and_key_cap(self):
        self.setup_rx()
        self.mk("rx-map", reactions=[{"host": "*.example.org", "reaction": "notice"}, {"app": "nixi-job", "reaction": "notice"}])
        S = self.server
        (r,) = self.ticks([self.row("cut", "x", "https://" + "a" * 60 + ".example.org.evil.net/")])   # (cut to 80, it ends in .example.org)
        self.assertNotIn("reaction", r)
        (r,) = self.ticks([self.row("job", "nixi-job")])
        self.assertNotIn("reaction", r)
        self.mk("rx-app", reactions=[{"app": "element", "reaction": "notice"}])
        for n in range(70):
            S.Inbox.rxat.clear()
            self.ticks([self.row(f"m{n}")], t0=1000.0 + n)
        self.assertLessEqual(len(S.Inbox.rxkeys), 64)


if __name__ == "__main__":
    unittest.main()
