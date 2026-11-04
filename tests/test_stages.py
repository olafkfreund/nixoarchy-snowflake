import json
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import stages as S

CMDS = {"v": 1, "kind": "commands", "items": [{"label": "Install", "cmd": "  nix profile install nixpkgs#firefox "},
                                              {"label": "Try", "cmd": "nix run nixpkgs#firefox"}]}
FACTS = {"v": 1, "kind": "facts", "title": "Tide", "points": ["a", "b"], "source": "moon"}
GAUGES = {"v": 1, "kind": "gauges", "title": "System", "source": "local", "live": True, "say": "All fine.",
          "hosts": [{"name": "p620", "state": "up", "badges": [{"k": "gen", "v": "42", "tone": "ok"}],
                     "meters": [{"label": "CPU", "pct": 18, "v": 1.5, "text": "busy", "tone": "warn"},
                                {"label": "NET", "pct": None}],
                     "lists": [{"title": "Failed", "items": ["none"], "tone": "ok"}]}]}


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

    def test_facts_say_is_optional_and_checked(self):
        self.assertEqual(S.validate({**FACTS, "say": " All fine. "})["say"], "All fine.")
        self.assertNotIn("say", S.validate(FACTS))
        self.assertIsNone(S.validate({**FACTS, "say": "x" * 201}))

    def test_gauges_full_example_and_unknown_keys(self):
        self.assertEqual(S.validate(GAUGES), GAUGES)
        stage = {**GAUGES, "extra": "drop", "hosts": [{**GAUGES["hosts"][0], "extra": "drop",
                  "badges": [{**GAUGES["hosts"][0]["badges"][0], "extra": "drop"}],
                  "meters": [{**GAUGES["hosts"][0]["meters"][0], "extra": "drop"}],
                  "lists": [{**GAUGES["hosts"][0]["lists"][0], "extra": "drop"}]}]}
        clean = S.validate(stage)
        self.assertNotIn("extra", clean)
        self.assertNotIn("extra", clean["hosts"][0])
        for key in ("badges", "meters", "lists"):
            self.assertNotIn("extra", clean["hosts"][0][key][0])
        self.assertEqual(S.validate({"v": 1, "kind": "gauges", "title": "x", "hosts": [{"name": "p620"}]})["hosts"][0]["state"], "up")

    def test_gauges_refuses_bad_fields(self):
        host = GAUGES["hosts"][0]
        bad_hosts = ([host] * 7,
                     [{**host, "meters": host["meters"] * 5}],
                     *[[{**host, "meters": [{"label": "CPU", "pct": pct}]}] for pct in (101, float("nan"), True)],
                     [{**host, "name": "p 620"}],
                     [{**host, "badges": [{"k": "gen", "v": "x" * 61}]}])
        for hosts in bad_hosts:
            self.assertIsNone(S.validate({**GAUGES, "hosts": hosts}))
        for field, value in (("live", 1), ("say", "x" * 201)):
            self.assertIsNone(S.validate({**GAUGES, field: value}))
        self.assertIsNone(S.validate({**GAUGES, "hosts": [{**host, "meters": [{"label": "CPU", "pct": 2, "v": True}]}]}))

    def test_drops(self):
        def bad(o):
            self.assertIsNone(S.validate(o))
        bad(None)
        bad({"v": 2, "kind": "facts"})
        bad({"v": 1, "kind": "sundial"})
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

    def test_say_stays_off_page_and_on_stage(self):
        stage = S.validate({**FACTS, "say": "All fine."})
        page = self.s.put(stage)
        self.assertNotIn("say", page)
        self.assertEqual(stage["say"], "All fine.")

    def test_gauges_tokens_and_replace(self):
        stage = S.validate(GAUGES)
        page = self.s.put(stage, refresh=("nix-status", "system status"))
        copy, refresh = page["token"], page["refresh"]
        self.assertNotIn("say", page)
        self.assertEqual(stage["say"], "All fine.")
        self.assertEqual(self.s.get(refresh), ("refresh", {"pid": "nix-status", "query": "system status"}))
        self.assertIn("CPU: 18%", self.s.get(copy)[1]["text"])
        self.assertIn("NET: —", self.s.get(copy)[1]["text"])
        self.t[0] = 5
        updated = S.validate({**GAUGES, "say": "Changed.", "hosts": [{**GAUGES["hosts"][0],
                  "meters": [{"label": "CPU", "pct": 23}]}]})
        new_page = self.s.replace(refresh, updated)
        self.assertEqual((new_page["token"], new_page["refresh"]), (copy, refresh))
        self.assertNotIn("say", new_page)
        self.assertEqual(updated["say"], "Changed.")
        self.assertEqual(self.s.get(refresh), ("refresh", {"pid": "nix-status", "query": "system status"}))
        self.assertIn("CPU: 23%", self.s.get(copy)[1]["text"])
        self.assertNotIn("CPU: 18%", self.s.get(copy)[1]["text"])
        self.assertEqual(self.s.cur[2], 0)
        self.assertIsNone(self.s.replace(refresh, S.validate(FACTS)))
        self.assertEqual(self.s.current()["kind"], "gauges")
        self.s.close()
        self.assertIsNone(self.s.replace(refresh, updated))
        page = self.s.put(stage, refresh=("nix-status", "system status"))
        self.s.put(S.validate(FACTS))
        self.assertIsNone(self.s.replace(page["refresh"], updated))

    def test_gauges_refresh_only_when_live_and_supplied(self):
        self.assertNotIn("refresh", self.s.put(S.validate(GAUGES)))
        self.assertNotIn("refresh", self.s.put(S.validate({**GAUGES, "live": False}), refresh=("id", "q")))

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

    def test_forget_where_drops_current_and_back(self):        # (#168: peers switched off)
        a = self.s.put(S.validate(CMDS))
        self.s.put(S.validate(FACTS))
        self.assertFalse(self.s.forget_where(lambda pg: pg.get("kind") == "commands"))   # only the one Back would bring back
        self.assertIsNotNone(self.s.current())
        self.assertIsNone(self.s.back())
        self.assertTrue(self.s.forget_where(lambda pg: pg.get("kind") == "facts"))
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

    def test_place_stage(self):
        self.assertEqual(S.validate({"v": 1, "kind": "place", "dest": " Oslo ", "mode": "walking"}), {"v": 1, "kind": "place", "dest": "Oslo", "mode": "walking"})
        self.assertNotIn("mode", S.validate({"v": 1, "kind": "place", "dest": "Oslo"}))
        for bad in ({"dest": "x" * 161}, {"dest": "a\nb"}, {"dest": ""}, {"dest": "x", "mode": "flying"}, {}):
            self.assertIsNone(S.validate({"v": 1, "kind": "place", **bad}))

    def test_place_tokens_hide_the_url(self):
        st = S.Store()
        page = st.put(S.validate({"v": 1, "kind": "place", "dest": "Tate Modern"}))
        self.assertNotIn("http", json.dumps(page))
        self.assertEqual(st.get(page["open"])[1]["url"], "https://www.google.com/maps/search/?api=1&query=Tate+Modern")
        self.assertEqual(st.get(page["copy"])[1]["text"], "Tate Modern")

    def test_origin_only_when_given(self):
        self.assertEqual(S.maps_url("Oxford station", "transit", "51.75,-1.26"),
                         "https://www.google.com/maps/dir/?api=1&destination=Oxford+station&travelmode=transit&origin=51.75%2C-1.26")
        self.assertNotIn("origin", S.maps_url("Oxford station", "transit"))
        for bad in ("", "  ", "a\nb"):
            with self.assertRaises(ValueError):
                S.maps_url("x", "driving", bad)

    def test_home_and_work_are_valid_destinations(self):
        for d in ("@home", "@work"):
            self.assertEqual(S.validate({"v": 1, "kind": "place", "dest": d, "mode": "driving"})["dest"], d)

    HOME = {"name": "Lisbon", "latitude": 38.72, "longitude": -9.14}

    def put(self, loc, dest="@home", mode="driving"):
        st = S.Store(where=lambda: loc)
        return st, st.put(S.validate({"v": 1, "kind": "place", "dest": dest, "mode": mode}))

    def test_home_resolves_to_the_stored_place(self):
        st, page = self.put({"now": None, "chosen": False, "home": self.HOME, "work": None})
        self.assertEqual(page["dest"], "Lisbon")
        self.assertNotIn("from", page)
        self.assertEqual(st.get(page["open"])[1]["url"],
                         "https://www.google.com/maps/dir/?api=1&destination=38.72%2C-9.14&travelmode=driving")
        self.assertEqual(st.get(page["copy"])[1]["text"], "Lisbon")
        self.assertNotIn("38.72", json.dumps(page))

    def test_unset_home_gets_no_token(self):
        st, page = self.put({"now": None, "chosen": False, "home": None, "work": self.HOME})
        self.assertEqual(page["unset"], "home")
        self.assertNotIn("open", page)
        self.assertNotIn("copy", page)
        self.assertIsNone(st.get("anything"))

    def test_unset_without_any_location(self):
        st = S.Store()                                     # (no lookup at all)
        page = st.put(S.validate({"v": 1, "kind": "place", "dest": "@work"}))
        self.assertEqual(page["unset"], "work")

    def test_a_chosen_place_is_the_origin(self):
        loc = {"now": {"name": "Porto"}, "chosen": True, "home": self.HOME, "work": None}
        st, page = self.put(loc, "Oxford station")
        self.assertEqual(page["from"], "Porto")
        self.assertTrue(st.get(page["open"])[1]["url"].endswith("&origin=Porto"))
        st, page = self.put({**loc, "now": self.HOME}, "Oxford station")
        self.assertIn("origin=38.72%2C-9.14", st.get(page["open"])[1]["url"])

    def test_a_plain_place_search_has_no_start(self):
        loc = {"now": {"name": "Porto"}, "chosen": True, "home": self.HOME, "work": None}
        st, page = self.put(loc, "Oxford station", mode=None)
        self.assertNotIn("from", page)
        self.assertNotIn("origin", st.get(page["open"])[1]["url"])

    def test_home_is_matched_loosely(self):
        for d in ("@Home", "@HOME", "@home"):
            st = S.Store(where=lambda: {"home": self.HOME})
            page = st.put({"v": 1, "kind": "place", "dest": " " + d + " ", "mode": "driving"})
            self.assertEqual(page["dest"], "Lisbon", d)

    def test_a_guess_is_never_an_origin(self):
        st, page = self.put({"now": {"name": "Guessville"}, "chosen": False, "home": None, "work": None}, "Oxford station")
        self.assertNotIn("from", page)
        self.assertNotIn("origin", st.get(page["open"])[1]["url"])

    def test_a_failing_lookup_still_shows_the_card(self):
        def boom():
            raise RuntimeError("x")
        page = S.Store(where=boom).put(S.validate({"v": 1, "kind": "place", "dest": "Oxford"}))
        self.assertIn("open", page)

    def test_bad(self):
        for a in (("x", "flying"), ("", "driving"), ("a\nb", "driving")):
            with self.assertRaises(ValueError):
                S.maps_url(*a)


class VideoTest(unittest.TestCase):
    FIX = Path(__file__).parent / "fixtures" / "ytdlp_search.json"

    def run_fake(self, out, calls=None):
        def run(argv, **kw):
            if calls is not None:
                calls.append((argv, kw))
            return type("R", (), {"stdout": out})()
        return run

    def test_search_parses_three_and_passes_one_argv_arg(self):
        calls = []
        r = S.video_search("a; rm -rf ~ --x", self.run_fake(self.FIX.read_bytes(), calls))
        self.assertEqual(len(r), 3)
        self.assertEqual(set(r[0]), {"id", "title", "channel", "duration"})
        self.assertEqual(calls[0][0], ["yt-dlp", "--ignore-config", "--flat-playlist", "-J", "ytsearch3:a; rm -rf ~ --x"])
        self.assertEqual(calls[0][1]["timeout"], 8)
        self.assertNotIn("shell", calls[0][1])

    def test_search_failures_are_empty(self):
        for out in (b"", b"{}", b"[1]", b'{"entries":[{"id":"bad id"}]}'):
            self.assertEqual(S.video_search("x", self.run_fake(out)), [])

        def boom(*a, **k):
            raise S.subprocess.TimeoutExpired("yt-dlp", 8)
        self.assertEqual(S.video_search("x", boom), [])

    def test_agent_cannot_bring_items(self):
        self.assertEqual(S.validate({"v": 1, "kind": "video", "query": "cats", "items": [{"id": "x"}]}), {"v": 1, "kind": "video", "query": "cats"})
        self.assertIsNone(S.validate({"v": 1, "kind": "video", "query": ""}))

    def test_tokens_hide_urls_and_search_url_encodes(self):
        st = S.Store()
        v = S.validate({"v": 1, "kind": "video", "query": "a&b c"})
        page = st.put({**v, "items": S.video_search("x", self.run_fake(self.FIX.read_bytes()))})
        self.assertNotIn("http", json.dumps(page))
        self.assertTrue(st.get(page["items"][0]["play"])[1]["url"].startswith("https://www.youtube.com/watch?v="))
        self.assertEqual(st.get(page["search"])[1]["url"], "https://www.youtube.com/results?search_query=a%26b+c")

    def fetch(self, body=b"x", ct="image/jpeg", err=None):
        urls = []

        class R:
            headers = {"Content-Type": ct}
            def read(self, n): return body[:n]
            def __enter__(self): return self
            def __exit__(self, *a): return False

        class Op:
            def open(self, req, timeout=None):
                urls.append(req.full_url)
                if err:
                    raise err
                return R()
        with mock.patch.object(S.urllib.request, "build_opener", return_value=Op()):
            return S.fetch_thumb("abcdefghijk"), urls

    def test_thumb_fetch(self):
        got, urls = self.fetch()
        self.assertEqual(got, (b"x", "image/jpeg"))
        self.assertEqual(urls, ["https://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg"])
        self.assertIsNotNone(self.fetch(b"x" * 200_000)[0])
        self.assertIsNone(self.fetch(b"x" * 200_001)[0])
        self.assertIsNone(self.fetch(ct="text/html")[0])
        import urllib.error
        self.assertIsNone(self.fetch(err=urllib.error.HTTPError("u", 302, "redirect", {}, None))[0])
        self.assertIsNone(self.fetch(err=OSError())[0])

    def test_thumb_bad_id_never_fetches(self):
        with mock.patch.object(S.urllib.request, "build_opener") as bo:
            self.assertIsNone(S.fetch_thumb("../evil"))
            self.assertIsNone(S.fetch_thumb("x" * 11 + "/../.."))
        self.assertFalse(bo.called)


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


class PluginOnlyKindsTest(unittest.TestCase):
    def test_the_agent_cannot_send_a_gauges_board(self):          # (#166 review: made-up readings dressed as system status)
        g = {"v": 1, "kind": "gauges", "title": "System status", "hosts": [{"name": "p620", "meters": [{"label": "CPU", "pct": 1}]}]}
        self.assertIsNotNone(S.validate(g))                          # a plugin's output
        self.assertIsNone(S.validate(g, lambda pid: True))           # the agent's <<stage>> block

