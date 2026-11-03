"""The day desk's data (#144 slice 4): gog and gh fixtures through a fake runner. Titles in the fixtures are made up."""
import datetime
import json
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "app"))
import day  # noqa: E402
import stages  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "day"
NOW = datetime.datetime.combine(datetime.date.today(), datetime.time(9, 0)).astimezone()
D = NOW.date()


def fixture(name):
    """A fixture with {D} {Y} {T} (today, yesterday, tomorrow) and {TZ} (today's local offset) filled in."""
    tz = NOW.strftime("%z")
    tz = tz[:3] + ":" + tz[3:]
    t = (FIX / name).read_text()
    for k, v in (("{D}", D.isoformat()), ("{Y}", (D - datetime.timedelta(days=1)).isoformat()), ("{T}", (D + datetime.timedelta(days=1)).isoformat()), ("{TZ}", tz)):
        t = t.replace(k, v)
    return t


class Runner:
    """Stands in for subprocess.run: answers by argv, records every call."""

    def __init__(self, gh_signed_in=True, fail=(), missing=()):
        self.calls, self.gh_signed_in, self.fail, self.missing = [], gh_signed_in, set(fail), set(missing)

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        assert isinstance(argv, list) and not kw.get("shell")
        tool = argv[0]
        if tool in self.missing:
            raise FileNotFoundError(tool)
        src = "gh" if tool == "gh" else "cal" if argv[3] == "calendar" else "tasks"
        if tool == "gh" and argv[1] == "auth":
            return SimpleNamespace(returncode=0 if self.gh_signed_in else 1, stdout=b"", stderr=b"")
        if src in self.fail:
            return SimpleNamespace(returncode=1, stdout=b"", stderr=b"boom")
        name = ("gog_calendar.json" if argv[3] == "calendar" else "gog_tasklists.json" if argv[4] == "lists" else "gog_tasks_%s.json" % argv[5]) if tool == "gog" \
            else "gh_%s.json" % argv[2]
        return SimpleNamespace(returncode=0, stdout=fixture(name).encode(), stderr=b"gog: token refreshed\n")   # (chatter on stderr, still a success)

    def of(self, tool, *words):
        return [a for a, _ in self.calls if a[0] == tool and all(w in a for w in words)]


def snap(run=None, now=NOW, ids=("work@example.com",), **kw):
    return day.snapshot(now, list(ids), run=run or Runner(), **kw)


class DayTest(unittest.TestCase):
    def setUp(self):
        day._cache.clear()

    # ---- the commands
    def test_argv_lists_and_eight_second_timeouts(self):
        r = Runner()
        snap(r)
        self.assertTrue(r.calls)
        for argv, kw in r.calls:
            self.assertIsInstance(argv, list)
            self.assertLessEqual(kw["timeout"], 8)
            self.assertFalse(kw.get("shell"))
        self.assertNotIn("shell=True", (REPO / "app" / "day.py").read_text())

    def test_calendar_window_is_the_local_day(self):
        r = Runner()
        snap(r)
        (argv,) = r.of("gog", "calendar")
        lo, hi = datetime.datetime.fromisoformat(argv[argv.index("--from") + 1]), datetime.datetime.fromisoformat(argv[argv.index("--to") + 1])
        self.assertEqual((lo.date(), lo.time()), (D, datetime.time(0, 0)))
        self.assertEqual((hi.date(), hi.time()), (D + datetime.timedelta(days=1), datetime.time(0, 0)))
        self.assertIn("work@example.com", argv)

    def test_tasks_use_up_to_three_lists_and_due_max_tomorrow(self):
        r = Runner()
        snap(r)
        lists = r.of("gog", "tasks", "list")
        self.assertEqual([a[a.index("list") + 1] for a in lists], ["L1", "L2", "L3"])
        self.assertTrue(all(a[a.index("--due-max") + 1].startswith((D + datetime.timedelta(days=1)).isoformat()) for a in lists))

    def test_github_asks_issues_and_review_requests(self):
        r = Runner()
        snap(r)
        self.assertEqual(len(r.of("gh", "issues", "--assignee=@me")), 1)
        self.assertEqual(len(r.of("gh", "prs", "--review-requested=@me")), 1)

    # ---- the calendar
    def test_next_is_the_first_unfinished_timed_event_with_a_join(self):
        s = snap()
        self.assertEqual((s["next"]["when"], s["next"]["title"], s["next"]["in"]), ("09:40", "Team stand-up", "in 40 min"))
        self.assertEqual(s["next"]["link"], "https://meet.google.com/abc-defg-hij")
        self.assertEqual(s["next"]["url"], stages.CAL_URL)                        # (a google.com/calendar link is not on the list)

    def test_today_has_all_day_events_and_no_finished_ones(self):
        s = snap()
        self.assertEqual([(x["when"], x["title"]) for x in s["today"]],
                         [("all day", "Release day"), ("all day", "Conf week"), ("12:30", "<b>Markup</b> lunch"), ("14:00", "Design review")])
        self.assertEqual(s["today"][3]["url"], "https://calendar.google.com/calendar/event?eid=e2")
        self.assertEqual(s["today"][2]["url"], stages.CAL_URL)                    # (javascript: refused, fallback)
        self.assertIsNone(s["today"][3]["link"])                                  # (a URL in the notes is never a Join)
        self.assertEqual(s["count"]["today"], 4)

    def test_ongoing_event_is_now(self):
        s = snap(now=NOW.replace(hour=9, minute=50))
        self.assertEqual((s["next"]["title"], s["next"]["in"], s["next"]["when"]), ("Team stand-up", "now", "now"))

    def test_nothing_left_after_the_last_event(self):
        s = snap(now=NOW.replace(hour=20))
        self.assertIsNone(s["next"])
        self.assertEqual([x["title"] for x in s["today"]], ["Release day", "Conf week"])

    # ---- tasks
    def test_overdue_marked_completed_and_undated_left_out(self):
        s = snap()
        self.assertEqual([(t["title"], t["overdue"]) for t in s["tasks"]], [("Send invoice", True), ("Book dentist", False), ("Water plants", False)])
        self.assertEqual(s["tasks"][0]["when"], "overdue")

    # ---- github
    def test_github_rows_and_url_check(self):
        s = snap()
        self.assertEqual([(g["when"], g["pr"]) for g in s["github"]], [("showcase#42", True), ("showcase#18", False), ("tools#7", False)])
        self.assertIsNone(s["github"][2]["url"])                                  # (a non-github URL is dropped)

    def test_signed_out_gh_is_off_and_not_queried(self):
        r = Runner(gh_signed_in=False)
        s = snap(r)
        self.assertEqual((s["status"]["gh"], s["github"]), ("off", []))
        self.assertEqual(r.of("gh", "search"), [])

    def test_missing_tools_and_no_calendars_are_off(self):
        s = snap(Runner(missing=("gog", "gh")), ids=())
        self.assertEqual(s["status"], {"cal": "off", "tasks": "off", "gh": "off"})

    # ---- caching and failure
    def test_five_minute_cache_then_refetch(self):
        r = Runner()
        snap(r)
        n = len(r.calls)
        snap(r)
        self.assertEqual(len(r.calls), n)
        for k, (t, items, hm) in list(day._cache.items()):
            day._cache[k] = (t - 301, items, hm)
        snap(r)
        self.assertGreater(len(r.calls), n)

    def test_failure_after_success_keeps_the_old_data_as_stale(self):
        snap()
        for k, (t, items, hm) in list(day._cache.items()):
            day._cache[k] = (t - 301, items, "09:00")
        s = snap(Runner(fail=("cal", "gh")), now=NOW.replace(minute=30))
        self.assertEqual((s["status"]["cal"], s["status"]["gh"], s["status"]["tasks"]), ("stale@09:00", "stale@09:00", "ok"))
        self.assertEqual(s["next"]["title"], "Team stand-up")
        self.assertEqual(len(s["github"]), 3)

    def test_failure_with_nothing_cached_is_stale_and_empty(self):
        s = snap(Runner(fail=("cal",)))
        self.assertEqual((s["status"]["cal"], s["next"], s["today"]), ("stale@09:00", None, []))

    def test_yesterdays_cache_never_serves_today(self):
        snap(now=NOW - datetime.timedelta(days=1))
        s = snap(Runner(fail=("cal", "tasks", "gh")))
        self.assertEqual((s["next"], s["tasks"], s["github"]), (None, [], []))
        self.assertTrue(all(k[1] == D.isoformat() for k in day._cache))

    def test_cache_only_gives_nothing_when_cold(self):
        r = Runner()
        self.assertIsNone(snap(r, cache_only=True))
        self.assertEqual(r.calls, [])
        snap(r)
        self.assertEqual(snap(r, cache_only=True)["next"]["title"], "Team stand-up")

    def test_invalid_json_is_a_failure_not_a_crash(self):
        bad = lambda argv, **kw: SimpleNamespace(returncode=0, stdout=b"not json", stderr=b"")
        s = snap(bad)
        self.assertEqual(s["status"]["cal"][:5], "stale")

    def test_timeout_is_a_failure(self):
        def slow(argv, **kw):
            raise subprocess.TimeoutExpired(argv, 8)
        self.assertEqual(snap(slow)["status"]["tasks"][:5], "stale")

    # ---- speech
    def test_whats_next_line(self):
        self.assertEqual(day.whats_next(snap()), "Team stand-up in 40 minutes.")
        self.assertEqual(day.whats_next(snap(now=NOW.replace(minute=50))), "Team stand-up is on now.")
        self.assertEqual(day.whats_next(snap(now=NOW.replace(hour=20))), "Nothing else timed today.")
        day._cache.clear()
        self.assertEqual(day.whats_next(snap(ids=())), "Your calendar isn't set up.")

    def test_in_wording(self):
        self.assertEqual(day._in(40 * 60), "in 40 min")
        self.assertEqual(day._in(120 * 60), "in 2 h")
        self.assertEqual(day._in(135 * 60), "in 2 h 15 min")

    def test_summary_is_counts_and_two_titles(self):
        t = day.summary(snap())
        self.assertIn("Team stand-up", t)
        self.assertIn("Today: 4 \u2014 Release day; Conf week.", t)
        self.assertIn("Tasks: 3 \u2014 Send invoice; Book dentist (1 overdue).", t)
        self.assertIn("GitHub: 3 \u2014 ", t)
        self.assertNotIn("Design review", t)                                       # (only the top two per row)
        self.assertLess(len(t), 700)
        day._cache.clear()
        self.assertIn("GitHub: 0 (not set up).", day.summary(snap(Runner(gh_signed_in=False))))

    # ---- the stage
    def test_validate_accepts_a_bare_day_block(self):
        self.assertEqual(stages.validate({"v": 1, "kind": "day", "url": "javascript:1", "x": "<b>"}), {"v": 1, "kind": "day"})

    def test_store_turns_urls_into_tokens_and_drops_other_hosts(self):
        st = stages.Store()
        s = snap()
        s["next"]["url"] = "javascript:alert(1)"
        s["today"][0]["url"] = "https://evil.example/x"
        s["tasks"][0]["url"] = "https://user:pw@github.com/x"
        page = st.put(day.stage(s))
        self.assertIsNone(page["next"]["open"])
        self.assertEqual(st.get(page["next"]["join"])[1]["url"], "https://meet.google.com/abc-defg-hij")
        rows = {r["key"]: r for r in page["rows"]}
        self.assertIsNone(rows["today"]["items"][0]["open"])
        self.assertIsNone(rows["tasks"]["items"][0]["open"])
        self.assertTrue(rows["tasks"]["items"][0]["bad"])
        tok = rows["github"]["items"][0]["open"]
        self.assertEqual(st.get(tok), ("link", {"url": "https://github.com/someone/showcase/pull/42"}))
        self.assertNotIn("http", json.dumps(page))                                 # (the page never sees a URL)

    def test_item_url_allowlist(self):
        ok = stages.item_url_ok
        self.assertTrue(ok("https://github.com/a/b/issues/1") and ok("https://calendar.google.com/x") and ok("https://meet.google.com/a-b"))
        for bad in ("javascript:alert(1)", "http://github.com/a", "https://github.com.evil.example/a", "https://evil.example/github.com",
                    "https://u@github.com/a", "https://github.com/a b", "file:///etc/passwd", None, "https://zoom.us/j/1"):
            self.assertFalse(ok(bad), bad)

    def test_page_stage_carries_status_and_counts(self):
        page = stages.Store().put(day.stage(snap(Runner(gh_signed_in=False))))
        rows = {r["key"]: r for r in page["rows"]}
        self.assertEqual((rows["github"]["st"], rows["github"]["n"], rows["today"]["n"], page["cal"]), ("off", 0, 4, "ok"))
        self.assertEqual((page["wd"], page["md"]), (D.strftime("%A"), "%d %s" % (D.day, D.strftime("%b"))))

    def test_day_desk_has_no_voice_opening(self):
        page = stages.Store().put(day.stage(snap()))
        self.assertIsNone(stages.fast_path("open it", page))
        self.assertIsNone(stages.fast_path("open the second one", page))
        self.assertEqual(stages.fast_path("close", page), ("close", None))


if __name__ == "__main__":
    unittest.main()
