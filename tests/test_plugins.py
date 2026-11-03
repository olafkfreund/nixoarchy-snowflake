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


HAT = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><g transform="translate(1 2) scale(1.5)"><path d="M50 8L88 92Z" fill="acc" stroke="#fff"/><circle cx="5" cy="5" r="2" fill="#abc" opacity=".5"/></g></svg>'


class Sanitize(unittest.TestCase):
    def bad(self, svg, why=""):
        with self.assertRaises(ValueError, msg=svg) as c:
            plugins.sanitize_svg(svg if isinstance(svg, bytes) else svg.encode())
        self.assertIn(why, str(c.exception))

    def wrap(self, inner, root_attrs='viewBox="0 0 10 10"'):
        return f'<svg xmlns="http://www.w3.org/2000/svg" {root_attrs}>{inner}</svg>'

    def test_a_hat_passes(self):
        n = plugins.sanitize_svg(HAT)
        self.assertEqual([x["tag"] for x in n], ["svg", "g", "path", "circle"])
        self.assertEqual([x["p"] for x in n], [-1, 0, 1, 1])
        self.assertEqual(n[0]["a"], {"viewBox": "0 0 100 100"})

    def test_refused_elements(self):
        for tag in ("script", "use", "image", "text", "foreignObject", "style", "animate", "linearGradient", "filter", "svg"):
            self.bad(self.wrap(f"<{tag}/>"), "element not allowed")
        self.bad(self.wrap('<x:path xmlns:x="urn:evil"/>'), "element not allowed")

    def test_refused_attributes(self):
        for a in ('style="x"', 'href="#a"', 'onload="x()"', 'id="a"', 'class="a"', 'filter="a"', 'xlink:href="a" xmlns:xlink="urn:x"'):
            self.bad(self.wrap(f"<g {a}/>"), "not allowed")
        self.bad(self.wrap('<path d="M0 0" fill="url(#a)"/>'), "bad fill")
        self.bad(self.wrap('<path d="M0 0" fill="red"/>'), "bad fill")
        self.bad(self.wrap('<path d="M0 0" fill="#12"/>'), "bad fill")
        self.bad(self.wrap('<path d="M0 0" fill-opacity="2"/>'), "bad fill-opacity")
        self.bad(self.wrap('<path d="M0 0" stroke-linecap="x"/>'), "bad stroke-linecap")
        self.bad(self.wrap('<rect x="1e3" y="0" width="1" height="1"/>'), "bad number")
        self.bad(self.wrap('<circle cx="0" cy="0" r="1" d="M0 0"/>'), "not allowed")

    def test_transform_numeric_translate_scale_rotate_only(self):
        for t in ("skewX(3)", "matrix(1 0 0 1 0 0)", "translate(url(#a))", "rotate(1 2)", "scale(1 2 3)", "translate()", "translate(1) foo"):
            self.bad(self.wrap(f'<g transform="{t}"/>'), "bad transform")
        plugins.sanitize_svg(self.wrap('<g transform="translate(1,2) rotate(30 5 5) scale(2)"/>').encode())

    def test_dangerous_prologue(self):
        self.bad(b'<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg"/>', "DOCTYPE")
        self.bad(b'<!doctype svg><svg/>', "DOCTYPE")
        self.bad(b'<!DOCTYPE svg [<!ENTITY a "b">]><svg/>', "DOCTYPE")
        self.bad(b'<?xml version="1.0"?><svg/>', "<?")
        self.bad(b'<svg/><?pi x?>', "<?")
        self.bad("<svg/>".encode("utf-16"), "UTF-8")
        self.bad(b"<svg", "not valid")

    def test_limits(self):
        self.bad(b"<svg>" + b" " * 17000 + b"</svg>", "16 KB")
        self.bad(self.wrap("<g/>" * 200), "200 elements")   # root + 200 = 201
        plugins.sanitize_svg(self.wrap("<g/>" * 198).encode())
        deep = "<g>" * 7 + "</g>" * 7                      # root + 7 = depth 8
        plugins.sanitize_svg(self.wrap(deep).encode())
        self.bad(self.wrap("<g>" + deep + "</g>"), "deeper than 8")
        self.bad(self.wrap(f'<path d="M0 0{" L1 1" * 800}"/>'), "path data")
        self.bad(self.wrap('<path d="M0 1001"/>'), "±1000")
        self.bad(self.wrap('<path d="M0 -1001.5"/>'), "±1000")
        self.bad(self.wrap('<circle cx="1001" cy="0" r="1"/>'), "bad number")
        self.bad(self.wrap('<path d="M0 0 alert(1)"/>'), "path data")
        self.bad(self.wrap('<polygon points="0,0 1001,5"/>'), "±1000")
        self.bad("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'>text</svg>", "text not allowed")

    def test_the_example_hat(self):
        d = Path(__file__).resolve().parent.parent / "plugins/examples/party-hat-plus"
        plugins.sanitize_svg((d / "prop.svg").read_bytes())
        m = json.loads((d / "plugin.json").read_text())
        self.assertIsNone(plugins._check(m, d))


if __name__ == "__main__":
    unittest.main()
