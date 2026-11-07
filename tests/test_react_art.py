"""Reaction art in index.html (#208): safe markup/CSS, fx- ids, only the 14 in-scope ids, under 40 KB."""
import json
import re
import unittest
from pathlib import Path

HTML = Path(__file__).resolve().parent.parent / "app/static/index.html"
# Copied verbatim from mockups/206/build.py in nixi-nixarchy:
BAD = re.compile(r"<\s*(script|image|foreignObject|iframe|use|a|style)\b|\son\w+\s*=|https?:|javascript:|@import|expression\(|\bfilter\s*[=:]|</style", re.I)
IDS = ("load", "memory", "error", "soon", "meeting", "notice", "ask", "done", "open", "music", "rain", "snow", "wind", "workout")
CHARS = ("snowflake", "terminal", "robot", "devil")


def _load_react():
    text = HTML.read_text()
    m = re.search(r"\bconst\s+REACT\s*=\s*", text)
    if not m:
        raise AssertionError("REACT not found in index.html")
    obj, end = json.JSONDecoder().raw_decode(text, m.end())
    return obj, text[m.end():end]


def _strings(node, path="REACT"):
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _strings(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _strings(v, f"{path}[{i}]")


class ReactArtTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.react, cls.raw = _load_react()
        cls.html = HTML.read_text()

    def test_size_under_40kb(self):
        self.assertLess(len(self.raw.encode("utf-8")), 40 * 1024)

    def test_only_in_scope_ids(self):
        self.assertEqual(set(self.react.keys()), {"defs", "props", "touch"})
        self.assertEqual(tuple(self.react["props"].keys()), IDS)
        for rid, prop in self.react["props"].items():
            self.assertEqual(set(prop.keys()), {"sky", "back", "front", "css"}, rid)
        self.assertEqual(tuple(self.react["touch"].keys()), CHARS)
        for char, touches in self.react["touch"].items():
            self.assertEqual(tuple(touches.keys()), IDS, char)
            for rid, touch in touches.items():
                self.assertEqual(set(touch.keys()), {"back", "front", "css"}, f"{char}.{rid}")

    def test_every_string_passes_bad_regex_and_fx_ids(self):
        strs = list(_strings(self.react))
        self.assertGreater(len(strs), 0)
        for path, s in strs:
            m = BAD.search(s)
            self.assertIsNone(m, f"{path} matched BAD: {m.group(0) if m else ''!r}")
            for id_m in re.finditer(r"\bid\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", s, re.I):
                val = id_m.group(1) or id_m.group(2) or id_m.group(3) or ""
                self.assertTrue(val.startswith("fx-"), f"{path} has non-fx id={val!r}")

    def test_svg_defs_and_layer_groups(self):
        self.assertIn(self.react["defs"], self.html)
        self.assertRegex(self.html, r'<g class="whole">\s*<g id="body">\s*<g id="rxSky"></g>\s*<g id="accBack"></g>\s*<g id="sitBack"></g>\s*<g id="rxBack"></g>')
        self.assertRegex(self.html, r'<g id="accFront"></g>\s*<g id="sitFront"></g>\s*<g id="rxFront"></g>')


if __name__ == "__main__":
    unittest.main()
