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
        D.last_switch, D.last_event = 0.0, 1.0           # (quiet since long ago)
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
        self.assertFalse(self.sent()[0]["speak"])

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
        self.assertIn(sent[0]["text"], N.QUIPS)
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
        now = datetime.datetime.now().astimezone()
        A.events = [(now + datetime.timedelta(hours=1), "Standup", "e")]
        S.CFG["ambient_calendar"] = True
        self.hist.write_text("{not json")
        text = N.welcome(10_000, self.hist, now)
        self.assertTrue(text.startswith("Welcome back! Next: Standup at "), text)
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
