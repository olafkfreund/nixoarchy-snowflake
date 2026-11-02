import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import stages as S

CMDS = {"v": 1, "kind": "commands", "items": [{"label": "Install", "cmd": "  nix profile install nixpkgs#firefox "},
                                              {"label": "Try", "cmd": "nix run nixpkgs#firefox"}]}
FACTS = {"v": 1, "kind": "facts", "title": "Tide", "points": ["a", "b"], "source": "moon"}


class CutterTest(unittest.TestCase):
    def run_cut(self, parts):
        c = S.Cutter()
        shown = "".join(c.feed(p) for p in parts)
        tail, blk = c.close()
        return shown + tail, blk

    def test_plain_text_passes(self):
        self.assertEqual(self.run_cut(["Hello ", "there <3"]), ("Hello there <3", None))

    def test_block_cut_and_parsed(self):
        text, blk = self.run_cut(['Do this.\n<<stage>>{"v":1,"kind":"facts"}'])
        self.assertEqual((text, blk), ("Do this.\n", {"v": 1, "kind": "facts"}))

    def test_marker_split_over_three_deltas(self):
        text, blk = self.run_cut(["Hi\n<<st", "age>>{\"v\":", "1}\nafter"])
        self.assertEqual((text, blk), ("Hi\nafter", {"v": 1}))

    def test_partial_marker_that_is_not_one_is_released(self):
        self.assertEqual(self.run_cut(["a <<st", "ar"]), ("a <<star", None))
        self.assertEqual(self.run_cut(["tail <<st"]), ("tail <<st", None))

    def test_bad_json_or_no_arrow_gives_none(self):
        self.assertEqual(self.run_cut(["x\n<<stage>>{oops"]), ("x\n", None))
        self.assertEqual(self.run_cut(["x\n<<stage {}"]), ("x\n", None))

    def test_last_block_wins(self):
        _, blk = self.run_cut(['<<stage>>{"v":1,"n":1}\n<<stage>>{"v":1,"n":2}'])
        self.assertEqual(blk["n"], 2)


class ValidateTest(unittest.TestCase):
    def test_commands_ok_strips_ends_only(self):
        v = S.validate(CMDS)
        self.assertEqual(v["items"][0]["cmd"], "nix profile install nixpkgs#firefox")
        self.assertEqual(set(v), {"v", "kind", "items"})

    def test_commands_title_optional_and_checked(self):
        self.assertEqual(S.validate({**CMDS, "title": " Install "})["title"], "Install")
        self.assertNotIn("title", S.validate(CMDS))
        for bad in ("", "x" * 121, "a\nb", 5):
            self.assertIsNone(S.validate({**CMDS, "title": bad}))

    def test_facts_ok(self):
        self.assertEqual(S.validate(FACTS), FACTS)

    def test_drops(self):
        def bad(o):
            self.assertIsNone(S.validate(o))
        bad(None)
        bad({"v": 2, "kind": "facts"})
        bad({"v": 1, "kind": "weather"})
        bad({**CMDS, "items": []})
        bad({**CMDS, "items": [{"label": "a", "cmd": "b"}] * 6})
        bad({**CMDS, "items": [{"label": "x" * 121, "cmd": "b"}]})
        bad({**CMDS, "items": [{"label": "a", "cmd": "b" * 501}]})
        bad({**CMDS, "items": [{"label": "a", "cmd": "ls\nrm -rf x"}]})
        bad({**CMDS, "items": [{"label": "a\x1b", "cmd": "ls"}]})
        bad({**FACTS, "points": ["x"] * 6})
        bad({**FACTS, "points": ["ok", 3]})
        bad({**FACTS, "source": 5})

    def test_limits_inclusive(self):
        ok = {**CMDS, "items": [{"label": "x" * 120, "cmd": "c" * 500}] * 5}
        self.assertIsNotNone(S.validate(ok))


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.t = [0.0]
        self.s = S.Store(now=lambda: self.t[0])

    def test_tokens_resolve_and_page_has_no_extra(self):
        page = self.s.put(S.validate(CMDS))
        tok = page["items"][0]["token"]
        self.assertEqual(self.s.get(tok), ("command", {"label": "Install", "cmd": "nix profile install nixpkgs#firefox"}))
        self.assertIsNone(self.s.get("nope"))
        self.assertEqual(self.s.current(), page)

    def test_facts_token_copies_text(self):
        page = self.s.put(S.validate(FACTS))
        self.assertEqual(self.s.get(page["token"])[1]["text"], "Tide\na\nb")

    def test_token_of_old_stage_refused(self):
        old = self.s.put(S.validate(CMDS))["items"][0]["token"]
        self.s.put(S.validate(FACTS))
        self.assertIsNone(self.s.get(old))

    def test_expiry(self):
        tok = self.s.put(S.validate(CMDS))["items"][0]["token"]
        self.t[0] = 599
        self.assertIsNotNone(self.s.get(tok))
        self.t[0] = 601
        self.assertIsNone(self.s.get(tok))
        self.assertIsNone(self.s.current())

    def test_back_and_close(self):
        a = self.s.put(S.validate(CMDS))
        self.s.put(S.validate(FACTS))
        self.assertEqual(self.s.back(), a)
        self.assertIsNotNone(self.s.get(a["items"][1]["token"]))
        self.s.close()
        self.assertIsNone(self.s.current())
        self.assertEqual(self.s.back(), a)

    def test_visible_only_after_the_page_says_so(self):
        self.s.put(S.validate(CMDS))
        self.assertFalse(self.s.visible())
        self.s.set_visible(True)
        self.assertTrue(self.s.visible())
        self.s.put(S.validate(FACTS))                    # a new stage is not shown until the page draws it
        self.assertFalse(self.s.visible())
        self.s.set_visible(True)
        self.s.back()
        self.assertFalse(self.s.visible())
        self.s.set_visible(True)
        self.s.close()
        self.assertFalse(self.s.visible())
        self.s.set_visible(True)                         # nothing current: stays false
        self.assertFalse(self.s.visible())

    def test_has_prev(self):
        self.assertFalse(self.s.has_prev())
        self.s.put(S.validate(CMDS))
        self.assertFalse(self.s.has_prev())
        self.s.put(S.validate(FACTS))
        self.assertTrue(self.s.has_prev())
        self.t[0] = 700
        self.assertFalse(self.s.has_prev())

    def test_back_expired_or_empty(self):
        self.assertIsNone(self.s.back())
        self.s.put(S.validate(CMDS))
        self.s.put(S.validate(FACTS))
        self.t[0] = 700
        self.assertIsNone(self.s.back())


class MapsTest(unittest.TestCase):
    def test_dir(self):
        self.assertEqual(S.maps_url("Café & Bar, Oslo", "walking"),
                         "https://www.google.com/maps/dir/?api=1&destination=Caf%C3%A9+%26+Bar%2C+Oslo&travelmode=walking")

    def test_place_no_origin(self):
        u = S.maps_url("Tate Modern")
        self.assertEqual(u, "https://www.google.com/maps/search/?api=1&query=Tate+Modern")
        self.assertNotIn("origin", u)

    def test_bad(self):
        for a in (("x", "flying"), ("", "driving"), ("a\nb", "driving")):
            with self.assertRaises(ValueError):
                S.maps_url(*a)


class FastPathTest(unittest.TestCase):
    two = {"kind": "commands", "items": [{}, {}]}
    one = {"kind": "commands", "items": [{}]}
    facts = {"kind": "facts"}

    def test_phrases(self):
        f = S.fast_path
        self.assertEqual(f("Run the first one", self.two), ("run", 0))
        self.assertEqual(f("run the second one.", self.two), ("run", 1))
        self.assertEqual(f("run the third", {"items": [{}] * 3}), ("run", 2))
        self.assertEqual(f("run 2", self.two), ("run", 1))
        self.assertEqual(f("copy the first one", self.two), ("copy", 0))
        self.assertEqual(f("play number two", self.two), ("play", 1))
        self.assertEqual(f("please play number 2", self.two), ("play", 1))
        self.assertEqual(f("close", None), ("close", None))
        self.assertEqual(f("Go back!", None), ("back", None))
        self.assertEqual(f("show it", self.two), ("show", None))

    def test_it_targets(self):
        f = S.fast_path
        self.assertEqual(f("open it", self.one), ("open", 0))
        self.assertEqual(f("copy that", self.facts), ("copy", 0))
        self.assertEqual(f("open it", self.two), ("ask", None))
        self.assertEqual(f("copy that", self.two), ("ask", None))

    def test_no_match(self):
        f = S.fast_path
        self.assertIsNone(f("run the fifth one", self.two))
        self.assertIsNone(f("run the first one", None))
        self.assertIsNone(f("how do I close a window", self.two))
        self.assertIsNone(f("run the first one and then delete it", self.two))
        self.assertIsNone(f("", self.two))


if __name__ == "__main__":
    unittest.main()
