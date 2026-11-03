"""app/plugins.py: scan, manifest rules, hashing and the state file (#149)."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import plugins  # noqa: E402

GOOD = {"api": 1, "id": "pirate-quips", "name": "Pirate", "version": "1.0"}


class T(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.root = Path(self._t.name)

    def mk(self, name, manifest, base="a", files=()):
        d = self.root / base / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "plugin.json").write_text(manifest if isinstance(manifest, str) else json.dumps(manifest))
        for f in files:
            (d / f).write_text("x")
        return d

    def one(self, manifest, files=()):
        shutil.rmtree(self.root / "a", ignore_errors=True)
        self.mk("p", manifest, files=files)
        (p,) = plugins.scan([self.root / "a"])
        return p

    def test_good(self):
        p = self.one(GOOD)
        self.assertIsNone(p.error)
        self.assertEqual((p.id, p.source), ("pirate-quips", "nix"))

    def test_sources(self):
        self.mk("p", GOOD, "a")
        self.mk("q", dict(GOOD, id="other-one"), "b")
        self.assertEqual([x.source for x in plugins.scan([self.root / "a", self.root / "b"])], ["nix", "folder"])

    def test_bad_json_and_missing(self):
        self.assertIn("unreadable", self.one("{nope").error)
        (self.root / "a" / "empty").mkdir()
        self.assertIn("missing", [x for x in plugins.scan([self.root / "a"]) if x.dir.name == "empty"][0].error)

    def test_api(self):
        self.assertEqual(self.one(dict(GOOD, api=2, future=1)).error, "needs a newer Nixi")
        self.assertEqual(self.one(dict(GOOD, api=True)).error, "needs a newer Nixi")

    def test_required_unknown_id(self):
        self.assertIn("missing key: name", self.one({k: v for k, v in GOOD.items() if k != "name"}).error)
        self.assertIn("unknown key", self.one(dict(GOOD, extra=1)).error)
        for bad in ("ab", "Pirate", "-abc", "a" * 65, "a b c"):
            self.assertEqual(self.one(dict(GOOD, id=bad)).error, "bad id", bad)

    def test_duplicates_both_broken(self):
        self.mk("p", GOOD, "a")
        self.mk("q", GOOD, "b")
        r = plugins.scan([self.root / "a", self.root / "b"])
        self.assertEqual([x.error for x in r], ["duplicate id"] * 2)

    def test_notifications(self):
        ok = [{"app": "element", "category": "chat"}, {"host": "*.example.org", "category": "mail"}]
        self.assertIsNone(self.one(dict(GOOD, notifications=ok)).error)
        for bad in ([{"app": "Element", "category": "chat"}], [{"app": "a.*", "category": "chat"}],
                    [{"host": "a/b", "category": "chat"}], [{"app": "a", "host": "b", "category": "chat"}],
                    [{"app": "a", "category": "spam"}]):
            self.assertTrue(self.one(dict(GOOD, notifications=bad)).error, bad)

    def test_prop_and_quips(self):
        prop = {"file": "prop.svg", "anchor": "head", "layer": "front"}
        self.assertIsNone(self.one(dict(GOOD, prop=prop, quips="quips.json"), ["prop.svg", "quips.json"]).error)
        self.assertTrue(self.one(dict(GOOD, prop=dict(prop, anchor="feet")), ["prop.svg"]).error)
        self.assertTrue(self.one(dict(GOOD, prop=prop)).error)  # file missing

    def test_stage_and_argv_escape(self):
        st = {"phrases": ["nixi status"], "argv": ["run"], "cache_seconds": 30}
        self.assertIsNone(self.one(dict(GOOD, stage=st), ["run"]).error)
        self.assertIn("argv[0]", self.one(dict(GOOD, stage=dict(st, argv=["../run"])), ["run"]).error)
        self.assertIn("argv[0]", self.one(dict(GOOD, stage=dict(st, argv=["/bin/sh"]))).error)
        self.assertIn("cache", self.one(dict(GOOD, stage=dict(st, cache_seconds=601)), ["run"]).error)
        self.assertTrue(self.one(dict(GOOD, stage=dict(st, reads=["home"])), ["run"]).error)

    def test_argv_symlink_escape(self):
        outside = self.root / "outside"
        outside.write_text("x")
        d = self.mk("p", dict(GOOD, stage={"phrases": ["x"], "argv": ["run"]}))
        os.symlink(outside, d / "run")
        (p,) = plugins.scan([self.root / "a"])
        self.assertIn("argv[0]", p.error)

    def test_sha256(self):
        d = self.mk("p", GOOD, files=["run"])
        h = plugins.sha256_of(d)
        self.assertEqual(h, plugins.sha256_of(d))
        (d / "run").write_text("y")
        self.assertNotEqual(h, plugins.sha256_of(d))
        h = plugins.sha256_of(d)
        outside = self.root / "outside"
        outside.write_text("x")
        os.symlink(outside, d / "link")
        self.assertEqual(h, plugins.sha256_of(d))  # outside symlink ignored

    def test_state_roundtrip(self):
        f = self.root / "s" / "plugins-state.json"
        s = plugins.State(f)
        self.assertFalse(s.get("x")["enabled"])
        s.set("x", True, "abc")
        s2 = plugins.State(f)
        self.assertEqual(s2.get("x"), {"enabled": True, "sha256": "abc"})
        self.assertEqual(os.listdir(f.parent), ["plugins-state.json"])  # no temp left
        f.write_text("garbage")
        self.assertEqual(plugins.State(f).data, {})

    def test_plugin_dirs(self):
        d = plugins.plugin_dirs()
        self.assertEqual(d[0], plugins.APP_DIR.parent / "plugins")
        self.assertEqual(d[1].name, "plugins")


if __name__ == "__main__":
    unittest.main()
