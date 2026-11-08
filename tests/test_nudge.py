import json
import tempfile
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
        S.CFG.update(proactive=True, react_break=True, react_welcome=True, react_load=True, ambient_calendar=False)
        N, A, D = S.Nudge, S.Ambient, S.Desk
        for k, v in dict(pending={}, last_visual=None, last_speech=None, last_kind={}, active_since=None, seen_unlock=0.0,
                         was_hot=False, was_low=False, n_quip=0).items():
            setattr(N, k, v)
        for k, v in dict(locked=False, unlocked_at=0.0, last_lock_len=0.0, lock_since=0.0, meeting=False, ram_low=False, cpu_hot=False, events=[]).items():
            setattr(A, k, v)
        A.dnd, A.dnd_due, A.fullscreen = False, 0.0, False
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


if __name__ == "__main__":
    unittest.main()
