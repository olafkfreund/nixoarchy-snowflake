import json
import datetime
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from test_speakable import _ServerEnv


class NudgeTest(_ServerEnv):
    """#133b: nudges wait for a breakpoint, stay inside the budget, and never read notification text."""

    def setUp(self):
        S = self.server
        saved = dict(S.CFG)
        self.addCleanup(lambda: (S.CFG.clear(), S.CFG.update(saved)))
        S.CFG.update(proactive=True, react_break=True, react_welcome=True, react_load=True, ambient_calendar=False,
                     workout=[], water_every=0)
        failed = mock.patch.object(S.plugins, "_failed", side_effect=lambda cmd, out, i: out.__setitem__(i, []))
        failed.start()
        self.addCleanup(failed.stop)
        N, A, D = S.Nudge, S.Ambient, S.Desk
        for k, v in dict(pending={}, last_visual=None, last_speech=None, last_kind={}, active_since=None, seen_unlock=0.0,
                         was_hot=False, was_low=False, n_quip=0, water_since=None, workout_done=set(),
                         workout_pending=set(), shown={}, snoozed={}, skip_cool=set(), next_id=0, last_sched=None).items():
            setattr(N, k, v)
        for k, v in dict(locked=False, unlocked_at=0.0, last_lock_len=0.0, lock_since=0.0, meeting=False, ram_low=False, cpu_hot=False, events=[]).items():
            setattr(A, k, v)
        A.dnd, A.dnd_due, A.fullscreen = False, 0.0, False
        self.addCleanup(lambda: [setattr(A, k, False) for k in ("dnd", "fullscreen", "meeting", "locked")])   # (a held cue would silence later suites)
        ipc = mock.patch.object(S.Inbox, "call", return_value=None)
        self.ipc = ipc.start()
        self.addCleanup(ipc.stop)
        run = mock.patch.object(A, "run", return_value=None)
        run.start()
        self.addCleanup(run.stop)
        D.last_switch, D.last_event = 0.0, 1.0           # (quiet since long ago)
        qp = mock.patch.object(S, "quip", side_effect=lambda e, **k: "Welcome back!" if e == "welcome" else "q-" + e)   # (the wording is test_quips')
        qp.start()
        self.addCleanup(qp.stop)
        self.q = S.BUS.sub()
        self.addCleanup(S.BUS.unsub, self.q)
        self.hist = Path(tempfile.mkdtemp(dir=self.tmp)) / "history.json"
        self.hist.write_text("[]")

    def sent(self):
        out = []
        while not self.q.empty():
            out.append(self.q.get_nowait())
        return [e for e in out if e.get("t") == "nudge"]

    def tick(self, t, **kw):
        self.server.Nudge.tick(mono=t, wall=kw.pop("wall", 10_000), hist=self.hist, **kw)

    def busy(self, t):
        self.server.Desk.last_event = t - 5                  # windows are changing: no breakpoint

    def test_nothing_without_a_breakpoint(self):
        N = self.server.Nudge
        N.offer("ram", "tight", True, 100)
        self.busy(100)
        self.tick(100)
        self.assertEqual(self.sent(), [])
        self.server.Desk.last_switch = 100                   # a workspace switch is one
        self.tick(101)
        self.assertEqual([e["kind"] for e in self.sent()], ["ram"])

    def test_no_events_seen_is_not_a_breakpoint(self):
        self.server.Desk.last_event = 0.0
        self.server.Nudge.offer("ram", "tight", True, 100)
        self.tick(100)
        self.assertEqual(self.sent(), [])

    def test_quiet_for_20s_is_a_breakpoint(self):
        self.server.Nudge.offer("cpu", "hot", False, 100)
        self.server.Desk.last_event = 90
        self.tick(100)
        self.assertEqual(self.sent(), [])
        self.tick(110)
        self.assertEqual(len(self.sent()), 1)

    def test_budget_and_cooldown(self):
        N = self.server.Nudge
        N.offer("ram", "a", True, 1000)
        self.tick(1000)
        self.assertEqual(len(self.sent()), 1)
        N.offer("cpu", "b", False, 1010)
        self.tick(1100)                                      # one visual per 300 s
        self.assertEqual(self.sent(), [])
        self.tick(1301)
        self.assertEqual([e["kind"] for e in self.sent()], ["cpu"])
        N.offer("ram", "again", True, 1400)
        self.tick(1700)                                      # ram: 30 minute cooldown
        self.assertEqual(self.sent(), [])
        N.offer("ram", "later", True, 3200)
        self.tick(3200)
        self.assertEqual([e["text"] for e in self.sent()], ["later"])

    def test_a_cooldown_drop_re_arms_the_edge(self):
        N, A = self.server.Nudge, self.server.Ambient
        N.last_kind["ram"] = 1000
        A.ram_low, N.was_low = True, True
        N.offer("ram", "x", True, 1100)
        self.tick(1200)
        self.assertEqual((self.sent(), N.was_low), ([], False))
        self.tick(1202)                                      # offered again, dropped again: still cooling
        self.assertEqual(self.sent(), [])
        self.tick(2900)                                      # cooled down and still low: delivered
        self.assertEqual([e["kind"] for e in self.sent()], ["ram"])

    def test_speech_budget_and_meeting(self):
        N, A = self.server.Nudge, self.server.Ambient
        N.offer("break", "stretch", True, 1000)
        self.tick(1000)
        self.assertTrue(self.sent()[0]["speak"])
        N.offer("ram", "tight", True, 1400)
        self.tick(1400)                                      # a second spoken line inside 10 minutes
        self.assertFalse(self.sent()[0]["speak"])
        A.meeting = True
        N.offer("welcome", "hi", True, 5000)
        self.tick(5000)
        self.assertEqual(self.sent(), [])
        self.assertIn("welcome", N.pending)
        A.meeting = False
        N.last_speech = 4900                              # a fresh speech budget still makes the held nudge silent
        self.tick(5001)
        self.assertFalse(self.sent()[0]["speak"])

    def test_dnd_poll_keeps_last_answer_and_runs_with_proactive_off(self):
        S, A = self.server, self.server.Ambient
        S.CFG["proactive"] = False
        self.ipc.side_effect = ["on", "unknown", None, "off"]
        for t in (100, 101, 109, 110, 120, 130):
            A.sense(mono=t)
            self.assertEqual(A.dnd, t < 130)
            self.assertEqual(A.situation()["dnd"], A.dnd)
        self.assertEqual(self.ipc.call_count, 4)
        self.ipc.assert_has_calls([mock.call("isDnd")] * 4)

    def test_quiet_cues_hold_until_next_breakpoint(self):
        N, A = self.server.Nudge, self.server.Ambient
        for cue in ("dnd", "fullscreen", "meeting", "locked"):
            with self.subTest(cue=cue):
                N.pending.clear()
                N.last_visual = None
                N.last_kind.clear()
                N.offer("break", "stretch", True, 100)
                setattr(A, cue, True)
                self.tick(100)
                self.assertEqual(self.sent(), [])
                self.assertIn("break", N.pending)
                setattr(A, cue, False)
                self.busy(101)
                self.tick(101)
                self.assertEqual(self.sent(), [])
                self.server.Desk.last_switch = 102
                self.tick(102)
                self.assertEqual(self.sent()[0]["kind"], "break")
                self.server.Desk.last_switch = 0

    def test_break_waits_thirty_minutes_without_deadline(self):
        N, A = self.server.Nudge, self.server.Ambient
        N.offer("break", "stretch", True, 100)
        A.dnd = True
        self.tick(1901)
        self.assertIn("break", N.pending)
        self.assertEqual(self.sent(), [])
        A.dnd = False
        self.tick(1902)
        self.assertEqual(self.sent()[0]["wait"], None)

    def test_default_and_numeric_deadlines(self):
        N = self.server.Nudge
        N.offer("cpu", "hot", False, 100)
        self.tick(701)
        self.assertNotIn("cpu", N.pending)
        self.assertEqual(self.sent(), [])
        N.offer("water", "drink", False, 702)
        self.assertIsNone(N.pending["water"][2])
        N.pending.clear()
        N.offer("cpu", "move", False, 800, until=900)
        self.tick(901)
        self.assertNotIn("cpu", N.pending)
        self.assertEqual(self.sent(), [])
        N.offer("cpu", "move", False, 902, until=1000)
        self.tick(903)
        self.assertEqual(self.sent()[0]["wait"], 97)

    def test_agent_say_quiet_reasons_keep_priority(self):
        S, A = self.server, self.server.Ambient
        with mock.patch.object(S.Wake, "asleep", False), mock.patch.dict(S.CFG, {"agent_voice_mute": []}):
            A.meeting = A.dnd = A.locked = A.fullscreen = True
            for cue, reason in (("meeting", "meeting"), ("dnd", "dnd"), ("locked", "locked"), ("fullscreen", "fullscreen")):
                self.assertEqual(S.agent_say_ready("claude"), {"speak": False, "reason": reason})
                setattr(A, cue, False)
            self.assertEqual(S.agent_say_ready("claude"), {"speak": True})

    def test_agent_say_asks_the_desk_with_proactive_off(self):
        S = self.server
        S.CFG["proactive"] = False                           # Ambient.locked/fullscreen stay False: the desk is asked
        with mock.patch.object(S.Wake, "asleep", False), mock.patch.dict(S.CFG, {"agent_voice_mute": []}):
            for locked, w, want in ((True, {}, "locked"), (False, {"fullscreen": 2}, "fullscreen"), (None, None, None)):
                with mock.patch.object(S.Desk, "locked", return_value=locked), mock.patch.object(S.Desk, "ask", return_value=w):
                    r = S.agent_say_ready("claude")
                self.assertEqual(r, {"speak": True} if want is None else {"speak": False, "reason": want})

    def test_approval_route_is_unaffected_by_dnd(self):
        S = self.server
        S.Ambient.dnd = True
        h = object.__new__(S.Handler)
        h.path = "/api/approve"
        h.headers = {"X-Nixi-Token": S.TOOL_TOKEN}
        h._host_ok = lambda: True
        h._body = lambda: b'{"tool":"Bash","input":{"command":"touch /tmp/nixi-test"}}'
        h._json = mock.Mock()
        with mock.patch.object(S.APPROVALS, "ask", return_value={"ok": False, "why": "asked"}) as ask:
            h.do_POST()
        ask.assert_called_once()
        self.assertEqual(h._json.call_args.args[0], {"ok": False, "why": "asked"})

    def test_nothing_while_locked_or_off(self):
        N, A, S = self.server.Nudge, self.server.Ambient, self.server
        N.offer("ram", "tight", True, 100)
        A.locked = True
        self.tick(100)
        self.assertEqual(self.sent(), [])
        A.locked = False
        S.CFG["proactive"] = False
        self.tick(101)
        self.assertEqual((self.sent(), N.pending), ([], {}))

    def test_break_counter_resets_after_a_5_minute_lock_only(self):
        N, A = self.server.Nudge, self.server.Ambient
        self.tick(0)                                         # active_since = 0
        A.unlocked_at, A.last_lock_len = 3000, 60            # a 1-minute lock: no reset
        self.tick(3000)
        self.assertEqual(N.active_since, 0)
        self.tick(3601)
        sent = self.sent()
        self.assertEqual([e["kind"] for e in sent], ["break"])
        self.assertEqual(sent[0]["text"], "q-break")
        N.active_since, A.unlocked_at, A.last_lock_len = 0, 4000, 300   # 5 minutes: reset
        self.tick(4000)
        self.assertEqual(N.active_since, 4000)
        self.assertEqual(self.sent(), [])

    def test_welcome_counts_ts_only(self):
        N, A = self.server.Nudge, self.server.Ambient
        self.hist.write_text(json.dumps([
            {"ts": 9_500, "summary": "SENTINEL-SECRET", "body": "SENTINEL-BODY"},
            {"ts": 9_900, "summary": "SENTINEL-2"},
            {"ts": 1_000, "summary": "long ago"},
            {"summary": "no ts"}, "junk", {"ts": "9500"}]))
        A.unlocked_at, A.last_lock_len = 500, 1800
        self.busy(500)
        self.tick(500, wall=10_000)
        sent = self.sent()
        self.assertEqual(sent[0]["text"], "Welcome back! 2 notifications while you were away.")
        self.assertNotIn("SENTINEL", repr(sent))

    def test_welcome_names_the_next_meeting_and_survives_a_bad_file(self):
        import datetime
        N, A, S = self.server.Nudge, self.server.Ambient, self.server
        now = datetime.datetime.now().astimezone().replace(hour=10, minute=0, second=0, microsecond=0)   # (a fixed daytime: after 23:00, "in an hour" is tomorrow)
        A.events = [(now + datetime.timedelta(hours=1), "Standup", "e"),
                    (now + datetime.timedelta(days=1), "Tomorrow's thing", "t")]           # (never named: the welcome is about today)
        S.CFG["ambient_calendar"] = True
        self.hist.write_text("{not json")
        text = N.welcome(10_000, self.hist, now)
        self.assertTrue(text.startswith("Welcome back! Next: Standup at "), text)
        self.assertNotIn("Tomorrow", text)
        self.assertNotIn("notification", text)

    def test_load_nudges_fire_once_on_the_edge(self):
        N, A = self.server.Nudge, self.server.Ambient
        self.busy(100)
        A.ram_low = A.cpu_hot = True
        self.tick(100)
        self.assertEqual(set(N.pending), {"ram", "cpu"})
        self.assertFalse(N.pending["cpu"][1])                # never spoken
        N.pending.clear()
        self.tick(110)                                       # still on: no new offer
        self.assertEqual(N.pending, {})

    def test_workout_window_once_with_deadline_and_dnd_expiry(self):
        S, N, A = self.server, self.server.Nudge, self.server.Ambient
        now = datetime.datetime(2026, 11, 9, 9, 5, tzinfo=datetime.timezone.utc)  # Monday
        S.CFG["workout"] = [{"days": [0], "at": "09:00"}]
        self.tick(100, now=now)
        event = self.sent()[0]
        self.assertEqual((event["kind"], event["wait"], event["id"]), ("workout", 3300, 0))
        self.assertFalse(event["speak"])
        self.tick(500, now=now + datetime.timedelta(minutes=6))
        self.assertEqual(self.sent(), [])
        self.assertEqual(len(N.workout_done), 1)
        N.workout_done.clear()
        N.shown.clear()
        N.last_visual = None
        A.dnd = True
        self.tick(1000, now=now)
        self.assertIn("workout", N.pending)
        self.assertEqual(N.workout_done, set())
        self.tick(4401, now=now + datetime.timedelta(hours=1, seconds=1))
        self.assertNotIn("workout", N.pending)
        self.assertEqual((N.workout_pending, N.workout_done), (set(), set()))
        self.tick(4500, now=now + datetime.timedelta(hours=1, minutes=2))
        self.assertEqual(self.sent(), [])

    def test_overlapping_workouts_and_midnight(self):
        S, N = self.server, self.server.Nudge
        monday = datetime.datetime(2026, 11, 9, 9, 5, tzinfo=datetime.timezone.utc)
        S.CFG["workout"] = [{"days": [0], "at": "09:00"}, {"days": [0], "at": "09:30"},
                            {"days": [0], "at": "10:40"}]
        self.tick(100, now=monday)
        self.assertEqual([e["kind"] for e in self.sent()], ["workout"])
        self.assertEqual(len(N.workout_done), 2)  # 09:30 intersects the published 09:00 window
        self.tick(2000, now=monday + datetime.timedelta(minutes=35))
        self.assertEqual(self.sent(), [])
        N.active_since = 6100  # keep the independent hourly break out of this schedule assertion
        self.tick(6100, now=monday + datetime.timedelta(minutes=100))
        self.assertEqual([e["kind"] for e in self.sent()], ["workout"])
        S.CFG["workout"] = [{"days": [0], "at": "23:30"}]
        N.last_visual = None
        self.tick(7000, now=datetime.datetime(2026, 11, 10, 0, 10, tzinfo=datetime.timezone.utc))
        self.assertEqual([e["kind"] for e in self.sent()], ["workout"])
        self.assertEqual(N.shown["workout"][2], 8200)
        S.CFG["workout"] = [{"days": [1], "at": "23:30"}]
        self.tick(7100, now=datetime.datetime(2026, 11, 10, 0, 10, tzinfo=datetime.timezone.utc))
        self.assertEqual(self.sent(), [])

    def test_schedule_edit_drops_pending_and_future_day_does_not_fire(self):
        S, N, A = self.server, self.server.Nudge, self.server.Ambient
        now = datetime.datetime(2026, 11, 9, 9, 5, tzinfo=datetime.timezone.utc)
        S.CFG["workout"] = [{"days": [0], "at": "09:00"}]
        A.dnd = True
        self.tick(100, now=now)
        self.assertIn("workout", N.pending)
        S.CFG["workout"] = [{"days": [1], "at": "09:00"}]
        self.tick(101, now=now)
        self.assertNotIn("workout", N.pending)
        self.assertEqual(N.workout_pending, set())

    def test_water_counter_locks_and_switch_off(self):
        S, N, A = self.server, self.server.Nudge, self.server.Ambient
        S.CFG["water_every"] = 45
        self.tick(0)
        self.tick(2700)
        self.assertEqual([e["kind"] for e in self.sent()], ["water"])
        self.tick(2701)
        self.assertEqual(self.sent(), [])
        A.unlocked_at, A.last_lock_len = 3000, 120
        self.tick(3000)
        self.assertEqual(N.water_since, 2700)
        N.active_since = 5400
        self.tick(5400)
        self.assertEqual([e["kind"] for e in self.sent()], ["water"])
        A.unlocked_at, A.last_lock_len = 6000, 300
        self.tick(6000)
        self.assertEqual(N.water_since, 6000)
        A.dnd = True
        self.tick(8700)
        self.assertIn("water", N.pending)
        S.CFG["water_every"] = 0
        self.tick(8701)
        self.assertNotIn("water", N.pending)
        self.assertIsNone(N.water_since)

    def test_water_counter_waits_for_a_snooze(self):
        S, N = self.server, self.server.Nudge
        S.CFG["water_every"] = 45
        self.tick(0)
        N.active_since = 1e9                                # (no break in the way)
        self.tick(2700)
        wid = [e for e in self.sent() if e["kind"] == "water"][0]["id"]
        self.assertTrue(N.act(wid, "snooze", 30, t=2700))
        self.tick(4500)                                     # the snooze is due at 4500 and the counter isn't
        self.assertEqual([e["kind"] for e in self.sent()], ["water"])
        wid = N.shown["water"][0]
        self.assertTrue(N.act(wid, "snooze", 30, t=4500))
        self.tick(5400)                                     # 45 minutes since the last count, but snoozed to 6300: nothing
        self.assertEqual(self.sent(), [])
        self.tick(6300)
        self.assertEqual([e["kind"] for e in self.sent()], ["water"])

    def test_a_broken_hand_edited_schedule_does_not_stop_nudges(self):
        S, A = self.server, self.server.Ambient
        S.CFG.update(workout=[{"days": [0]}, {"days": [0], "at": "24:00"}, "x"], water_every="45")
        A.ram_low = True
        self.server.Desk.last_switch = 100                   # a breakpoint
        self.tick(100, now=datetime.datetime(2026, 11, 9, 9, 5).astimezone())
        self.assertEqual([e["kind"] for e in self.sent()], ["ram"])

    def test_ids_snooze_dismiss_and_old_clicks(self):
        S, N = self.server, self.server.Nudge
        N.offer("cpu", "hot", False, 100)
        self.tick(100)
        self.assertNotIn("id", self.sent()[0])
        N.last_visual = None
        N.offer("break", "stretch", True, 200)
        self.tick(200)
        id = self.sent()[0]["id"]
        N.offer("break", "duplicate", True, 201)
        before = N.active_since
        self.assertTrue(N.act(id, "snooze", 10, t=202))
        self.assertNotIn("break", N.pending)
        self.assertEqual(N.active_since, before)
        self.assertFalse(N.act(id, "snooze", 10, t=203))
        self.tick(801)
        self.assertEqual(self.sent(), [])
        N.last_visual = None
        self.tick(802)
        new = self.sent()
        self.assertEqual(len(new), 1)
        self.assertEqual((new[0]["kind"], new[0]["text"]), ("break", "stretch"))
        self.tick(803)
        self.assertEqual(self.sent(), [])
        N.offer("break", "duplicate", True, 804)
        self.assertTrue(N.act(new[0]["id"], "dismiss", t=805))
        self.assertEqual(N.active_since, 805)
        self.assertNotIn("break", N.pending)
        self.assertFalse(N.act(id, "dismiss", t=806))

    def test_workout_snooze_deadline_and_react_break_off(self):
        S, N = self.server, self.server.Nudge
        now = datetime.datetime(2026, 11, 9, 9, 55, tzinfo=datetime.timezone.utc)
        S.CFG["workout"] = [{"days": [0], "at": "09:00"}]
        self.tick(100, now=now)
        id = self.sent()[0]["id"]
        self.assertTrue(N.act(id, "snooze", 10, t=101))
        self.assertNotIn("workout", N.snoozed)
        N.offer("break", "stretch", True, 200)
        N.last_visual = None
        self.tick(200, now=now)
        id = self.sent()[0]["id"]
        self.assertTrue(N.act(id, "snooze", 10, t=201))
        S.CFG["react_break"] = False
        self.tick(202, now=now)
        self.assertEqual(N.snoozed, {})
        S.CFG["react_break"] = True
        self.tick(802, now=now)
        self.assertEqual(self.sent(), [])

    def test_act_is_single_use_across_threads_and_waits_for_tick(self):
        N = self.server.Nudge
        N.shown["break"] = (7, "stretch", None)
        results = []
        threads = [threading.Thread(target=lambda: results.append(N.act(7, "dismiss", t=100))) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=1)
        self.assertEqual(sorted(results), [False, True])
        N.shown["break"] = (8, "stretch", None)
        in_tick, release, acting = threading.Event(), threading.Event(), threading.Event()

        def held_watch(*_args):
            in_tick.set()
            release.wait(1)

        with mock.patch.object(N, "watch", side_effect=held_watch):
            tick_thread = threading.Thread(target=lambda: self.tick(100))
            tick_thread.start()
            self.assertTrue(in_tick.wait(1))
            thread = threading.Thread(target=lambda: (acting.set(), results.append(N.act(8, "dismiss", t=101))))
            thread.start()
            self.assertTrue(acting.wait(1))
            self.assertEqual(len(results), 2)
            release.set()
            tick_thread.join(timeout=1)
        thread.join(timeout=1)
        self.assertEqual(results[-1], True)

    def test_nudge_route_token_and_validation(self):
        S, N = self.server, self.server.Nudge
        N.shown["break"] = (8, "stretch", None)

        def post(body, token):
            h = S.Handler.__new__(S.Handler)
            h.path = "/api/nudge"
            h.headers = {"Host": "localhost", "X-Nixi-Token": token}
            h._host_ok = lambda: True
            h._body = lambda: json.dumps(body).encode()
            h._json = lambda obj, code=200: (code, obj)
            return h.do_POST()

        self.assertEqual(post({"id": 8, "act": "dismiss"}, "")[0], 403)
        for bad in ({"id": True, "act": "dismiss"}, {"id": 8, "act": "snooze", "minutes": True},
                    {"id": 8, "act": "snooze", "minutes": 45}):
            self.assertEqual(post(bad, S.TOKEN)[0], 400)
        self.assertEqual(post({"id": 8, "act": "dismiss"}, S.TOKEN), (200, {"ok": True}))
        self.assertEqual(post({"id": 8, "act": "dismiss"}, S.TOKEN), (200, {"ok": False}))


if __name__ == "__main__":
    unittest.main()
