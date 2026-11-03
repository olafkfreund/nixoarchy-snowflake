"""Sky and desk stages (#144 slice 3): built from cached data only, meeting links only from the two allowed fields."""
import datetime
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
NOW = datetime.datetime.now().astimezone()
GOG = {"events": [                                     # fixture shaped like `gog calendar events` output
    {"id": "a", "summary": "Stand-up", "start": {"dateTime": (NOW + datetime.timedelta(minutes=40)).isoformat()},
     "hangoutLink": "https://meet.google.com/abc-defg-hij", "description": "join https://evil.example/x"},
    {"id": "b", "summary": "Review", "start": {"dateTime": (NOW + datetime.timedelta(hours=3)).isoformat()},
     "conferenceData": {"entryPoints": [{"entryPointType": "phone", "uri": "tel:+4712345678"}, {"entryPointType": "video", "uri": "https://zoom.example/j/1"}]}},
    {"id": "c", "summary": "Anna's birthday", "start": {"date": NOW.date().isoformat()}},
    {"id": "d", "summary": "Day off", "start": {"date": (NOW + datetime.timedelta(days=1)).date().isoformat()}},
    {"id": "e", "summary": "Old", "start": {"dateTime": (NOW - datetime.timedelta(hours=2)).isoformat()}, "hangoutLink": "http://insecure.example"},
    {"id": "f", "summary": "Notes only", "start": {"dateTime": (NOW + datetime.timedelta(hours=5)).isoformat()}, "location": "https://zoom.example/in-location"},
]}


class DeskStagesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_env = os.environ.copy()
        cls.tmp = tempfile.mkdtemp(prefix="nixi-desk-test-")
        for k, d in (("HOME", ""), ("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
            os.environ[k] = os.path.join(cls.tmp, d)
            os.makedirs(os.environ[k], exist_ok=True)
        sys.path.insert(0, str(REPO_ROOT / "app"))
        import server
        import stages
        cls.s, cls.st = server, stages

    @classmethod
    def tearDownClass(cls):
        os.environ.clear()
        os.environ.update(cls._orig_env)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        A = self.s.Ambient
        for k in ("wx", "omx", "cal_at"):
            self.addCleanup(setattr, A, k, getattr(A, k))
        for k in ("cal_items", "events", "birthdays"):
            self.addCleanup(setattr, A, k, getattr(A, k))
        A.wx = A.omx = None

    # ---- weather
    def test_server_kinds_validate_to_bare_stages(self):
        for k in ("weather", "calendar", "status"):
            self.assertEqual(self.st.validate({"v": 1, "kind": k, "extra": "<b>x</b>", "url": "javascript:1"}), {"v": 1, "kind": k})

    def test_weather_from_the_cached_omarchy_reading(self):
        A = self.s.Ambient
        A.omx = {"sky": "rain", "temp": 4.4, "wind": 12.6, "at": time.monotonic() - 600}
        with mock.patch.object(A, "day", False):
            w = self.s.desk_stage({"v": 1, "kind": "weather"})
        self.assertEqual((w["source"], w["sky"], w["temp"], w["wind"], w["dir"], w["day"]), ("omarchy", "rain", 4, 13, None, False))
        self.assertRegex(w["at"], r"^\d\d:\d\d$")
        self.assertNotIn("forecast", w)                      # neither source returns one

    def test_weather_with_the_open_meteo_reading(self):
        A = self.s.Ambient
        A.wx = {"key": (1, 2), "at": time.monotonic(), "sky": "snow", "heavy": True, "feel": -3.2, "temp": -1.0, "wind": 20, "dir": 225, "day": 1}
        with mock.patch.object(A, "gated", return_value=True), mock.patch.object(A, "place_key", return_value=(1, 2)):
            w = self.s.desk_stage({"v": 1, "kind": "weather"})
        self.assertEqual((w["source"], w["sky"], w["heavy"], w["feel"], w["dir"]), ("open-meteo", "snow", True, -3, "SW"))

    def test_no_reading_is_an_empty_stage_and_no_network(self):
        with mock.patch.object(self.s.Ambient, "run") as run, mock.patch("urllib.request.urlopen") as uo:
            self.assertEqual(self.s.desk_stage({"v": 1, "kind": "weather"}), {"v": 1, "kind": "weather", "empty": True})
            self.s.desk_stage({"v": 1, "kind": "calendar"})
        self.assertFalse(run.called or uo.called)

    # ---- calendar
    def fetch(self):
        conf = self.s.NIXI_CONF.parent / "calendars.json"
        conf.parent.mkdir(parents=True, exist_ok=True)
        conf.write_text(json.dumps([{"enabled": True, "googleCalendarId": "cal"}]))
        self.addCleanup(conf.unlink)
        with mock.patch.object(self.s.Ambient, "run", return_value=json.dumps(GOG)) as run:
            self.s.Ambient.fetch("cal")
        return run

    def test_the_gog_call_looks_two_days_ahead(self):
        argv = self.fetch().call_args[0][0]
        self.assertEqual(argv[argv.index("--days") + 1], "2")

    def test_links_only_from_hangout_or_conference_data(self):
        self.fetch()
        links = {i["title"]: i["link"] for i in self.s.Ambient.cal_items}
        self.assertEqual(links["Stand-up"], "https://meet.google.com/abc-defg-hij")
        self.assertEqual(links["Review"], "https://zoom.example/j/1")
        self.assertIsNone(links["Notes only"])                # a URL in a location or description is not a meeting link
        self.assertIsNone(links["Old"])                       # http is refused
        self.assertNotIn("Anna", repr(self.s.Ambient.cal_items))

    def test_the_next_four_upcoming_events_in_order(self):
        self.fetch()
        with mock.patch.dict(self.s.CFG, {"ambient_calendar": True}):
            st = self.s.desk_stage({"v": 1, "kind": "calendar"})
        rows = st["events"]
        titles = [r["title"] for r in rows]
        self.assertLessEqual(len(rows), 4)
        self.assertTrue({"Stand-up", "Review"} <= set(titles))      # (the order across midnight depends on the clock)
        self.assertNotIn("Old", titles)
        self.assertNotIn("Anna's birthday", titles)
        self.assertEqual([r["link"] for r in rows if r["title"] == "Stand-up"], ["https://meet.google.com/abc-defg-hij"])
        self.assertFalse(st["off"])

    def test_calendar_off_says_so(self):
        with mock.patch.dict(self.s.CFG, {"ambient_calendar": False}):
            st = self.s.desk_stage({"v": 1, "kind": "calendar"})
        self.assertTrue(st["off"] and st["events"] == [])

    def test_calendar_tokens_open_only_server_urls(self):
        rows = [{"when": "10:40", "title": "Stand-up", "link": "https://meet.google.com/x"}, {"when": "13:00", "title": "No link", "link": None}]
        page = self.s.STAGES.put(self.st.calendar_stage(rows, "09:55"))
        self.assertNotIn("meet.google.com", json.dumps(page))        # the page holds tokens, not URLs
        self.assertNotIn("join", page["events"][1])
        with mock.patch.object(self.s.subprocess, "Popen") as po:
            self.assertTrue(self.s.stage_act(page["events"][0]["join"], "open")["ok"])
            self.assertEqual(po.call_args[0][0], ["xdg-open", "https://meet.google.com/x"])
            self.assertTrue(self.s.stage_act(page["open"], "open")["ok"])
            self.assertEqual(po.call_args[0][0], ["xdg-open", "https://calendar.google.com"])
            po.reset_mock()
            self.assertFalse(self.s.stage_act(page["open"], "terminal")["ok"])      # a token only does its own act
            self.assertFalse(po.called)

    # ---- status
    AGENTS = [{"pane_id": "p_1", "cwd": "/home/u/proj", "agent": "claude", "agent_status": "working"},
              {"pane_id": "bad id; rm", "cwd": "/x", "agent": "claude"}]

    def test_status_from_herdr_and_the_failed_unit_list(self):
        with mock.patch.object(self.s, "herdr_agents", return_value=self.AGENTS), mock.patch.dict(self.s.Ambient.data, {"sys": ["foo.service"]}), \
                mock.patch.dict(self.s.CFG, {"ambient_system": True}):
            st = self.s.desk_stage({"v": 1, "kind": "status"})
        self.assertEqual(st["sessions"], [{"title": "proj", "status": "working", "pane": "p_1"}])        # a bad pane id is dropped
        self.assertEqual((st["failed"], st["sys_on"]), (["foo.service"], True))

    def test_status_with_the_system_list_off_is_not_checked(self):
        with mock.patch.object(self.s, "herdr_agents", return_value=[]), mock.patch.dict(self.s.CFG, {"ambient_system": False}):
            st = self.s.desk_stage({"v": 1, "kind": "status"})
        self.assertEqual((st["failed"], st["sys_on"]), ([], False))

    def test_open_session_attaches_by_pane_and_open_terminal(self):
        page = self.s.STAGES.put(self.st.status_stage([{"title": "proj", "status": "idle", "pane": "p_1"}], [], True))
        self.assertNotIn("p_1", json.dumps(page))
        with mock.patch.object(self.s.subprocess, "Popen") as po:
            self.assertTrue(self.s.stage_act(page["sessions"][0]["open"], "session")["ok"])
            self.assertIn("p_1", po.call_args[0][0])
            self.assertIn("xdg-terminal-exec", po.call_args[0][0])
            self.assertTrue(self.s.stage_act(page["term"], "terminal")["ok"])
            self.assertEqual(po.call_args[0][0], ["xdg-terminal-exec"])
            po.reset_mock()
            self.assertFalse(self.s.stage_act(page["term"], "session")["ok"])
            self.assertFalse(po.called)

    # ---- the stream
    def test_a_weather_block_in_a_reply_becomes_a_filled_stage(self):
        A = self.s.Ambient
        A.omx = {"sky": "snow", "temp": -2.0, "wind": 5, "at": time.monotonic()}

        def fake_bridge(prompt, emit, *_):
            emit(t="delta", text='Cold out.\n<<stage>>{"v":1,"kind":"weather"}')
            emit(t="result", text="", is_error=False)
            return "done"
        h = self.s.Handler.__new__(self.s.Handler)
        h.wfile = io.BytesIO()
        h.send_response, h.send_header, h.end_headers = mock.Mock(), mock.Mock(), mock.Mock()
        h._body = lambda: json.dumps({"prompt": "what's the weather?"}).encode()
        h._json = mock.Mock()
        with mock.patch.object(self.s, "BRIDGED", True), mock.patch.object(self.s, "run_bridge", fake_bridge), mock.patch.object(self.s, "hist_add"), \
                mock.patch.object(self.s, "pick_auto", return_value=None), mock.patch.object(self.s.recall, "add"), mock.patch.dict(self.s.CFG, {"auto_compact": False}):
            h.ask()
        evs = [json.loads(x[6:]) for x in h.wfile.getvalue().decode().split("\n\n") if x.startswith("data: ")]
        stage = next(e for e in evs if e["t"] == "stage")
        self.assertEqual((stage["kind"], stage["source"], stage["temp"]), ("weather", "omarchy", -2))
        self.assertNotIn("<<stage", json.dumps(evs))


class PureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(REPO_ROOT / "app"))
        import stages
        cls.st = stages

    def test_meeting_link_rules(self):
        ml = self.st.meeting_link
        self.assertEqual(ml({"hangoutLink": "https://meet.google.com/a"}), "https://meet.google.com/a")
        self.assertIsNone(ml({"hangoutLink": "javascript:alert(1)"}))
        self.assertIsNone(ml({"hangoutLink": "https://a.example/x y"}))
        self.assertIsNone(ml({"hangoutLink": "https://a.example/" + "x" * 300}))
        self.assertIsNone(ml({"description": "https://zoom.example/j/1"}))
        self.assertEqual(ml({"conferenceData": {"entryPoints": [{"uri": 5}, {"uri": "https://t.example/1"}]}}), "https://t.example/1")
        self.assertIsNone(ml({"conferenceData": "https://t.example/1"}))

    def test_rows_label_today_tomorrow_and_all_day(self):
        now = datetime.datetime(2026, 11, 3, 10, 0).astimezone()
        items = [{"start": now + datetime.timedelta(days=1, hours=1), "day": "2026-11-04", "title": "T", "link": None},
                 {"start": None, "day": "2026-11-03", "title": "Today all day", "link": None},
                 {"start": None, "day": "2026-11-02", "title": "Yesterday", "link": None},
                 {"start": now + datetime.timedelta(minutes=5), "day": "2026-11-03", "title": "Soon", "link": "https://x.example/"}]
        rows = self.st.calendar_rows(items, now)
        self.assertEqual([(r["when"], r["title"]) for r in rows], [("all day", "Today all day"), ("10:05", "Soon"), ("Wed 11:00", "T")])
        self.assertEqual(len(self.st.calendar_rows(items * 3, now)), 4)

    def test_sky_stage_rounds_and_names_the_compass(self):
        w = self.st.sky_stage("omarchy", "clear", False, 20.6, 21.4, 3.5, 350, "09:00", True)
        self.assertEqual((w["temp"], w["feel"], w["wind"], w["dir"]), (21, 21, 4, "N"))


if __name__ == "__main__":
    unittest.main()
