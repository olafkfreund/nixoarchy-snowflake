import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_speakable import _ServerEnv


class QuipsTest(_ServerEnv):
    """#133c: local quips, no repeat until the list is used up, and one visual look quip a day."""

    def setUp(self):
        S = self.server
        self.dir = Path(tempfile.mkdtemp(dir=self.tmp))
        self.file = self.dir / "quips.json"
        p = mock.patch.object(S.Quips, "path", self.file)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(lambda: (setattr(S.Quips, "data", None), S.Quips.bags.clear()))
        S.Quips.data, S.Quips.mtime = None, None
        S.Quips.bags.clear()

    def write(self, d):
        self.file.write_text(json.dumps(d))
        os.utime(self.file, (os.path.getmtime(self.file) + len(self.file.read_text()), os.path.getmtime(self.file) + len(self.file.read_text())))

    def test_no_repeat_until_the_list_is_used_up(self):
        q = self.server.quip
        self.write({"snow": ["a", "b", "c", "d"]})
        for _ in range(3):                                   # three rounds
            self.assertEqual(sorted(q("snow") for _ in range(4)), ["a", "b", "c", "d"])

    def test_missing_corrupt_or_unknown_falls_back(self):
        S = self.server
        self.assertIn(S.quip("snow"), S.QUIP_FALLBACK["snow"])                    # no file
        self.file.write_text("{not json")
        S.Quips.data = None
        self.assertIn(S.quip("break"), S.QUIP_FALLBACK["break"])
        self.write({"break": "not a list", "snow": [3, "", "  "]})
        self.assertIn(S.quip("break"), S.QUIP_FALLBACK["break"])
        self.assertIn(S.quip("snow"), S.QUIP_FALLBACK["snow"])                    # nothing usable in it
        self.assertEqual(S.quip("no-such-event"), "")

    def test_slots_and_a_missing_slot(self):
        q = self.server.quip
        self.write({"coding": ["{n} hours of code, {pct}% done"]})
        self.assertEqual(q("coding", n=2, pct=50), "2 hours of code, 50% done")
        self.assertEqual(q("coding", n=2), "{n} hours of code, {pct}% done")      # unformatted, never raises
        self.write({"coding": ["a { brace"]})
        self.assertEqual(q("coding", n=2), "a { brace")

    def test_the_file_is_re_read_when_it_changes(self):
        q = self.server.quip
        self.write({"party": ["one"]})
        self.assertEqual(q("party"), "one")
        self.write({"party": ["two"]})
        self.assertEqual(q("party"), "two")

    def test_the_shipped_file_covers_every_event_and_slot(self):
        S = self.server
        d = json.loads((S.APP_DIR / "quips.json").read_text(encoding="utf-8"))
        self.assertEqual(set(d), set(S.QUIP_FALLBACK))
        for event, lines in d.items():
            self.assertTrue(3 <= len(lines) <= 5, event)
            for line in lines:
                line.format(n=1, pct=1)                      # only known slots


class QuipNudgeTest(_ServerEnv):
    def setUp(self):
        S = self.server
        saved = dict(S.CFG)
        self.addCleanup(lambda: (S.CFG.clear(), S.CFG.update(saved)))
        S.CFG.update(proactive=True, react_quips=True, react_break=False, react_welcome=False, react_load=False)
        N, A, D = S.Nudge, S.Ambient, S.Desk
        for k, v in dict(pending={}, last_visual=None, last_speech=None, last_kind={}, active_since=None, seen_unlock=0.0,
                         was_hot=False, was_low=False, quipped={}, coding_offered=0.0).items():
            setattr(N, k, v)
        for k, v in dict(locked=False, unlocked_at=0.0, meeting=False, weather=None, night=False, party=False, events=[]).items():
            setattr(A, k, v)
        D.last_switch, D.last_event, D.coding_since = 0.0, 1.0, 0.0
        self.addCleanup(setattr, D, "coding_since", 0.0)
        self.q = S.BUS.sub()
        self.addCleanup(S.BUS.unsub, self.q)
        self.hist = Path(tempfile.mkdtemp(dir=self.tmp)) / "history.json"

    def sent(self):
        out = []
        while not self.q.empty():
            out.append(self.q.get_nowait())
        return [(e["kind"], e["text"], e["speak"]) for e in out if e.get("t") == "nudge"]

    def tick(self, t):
        self.server.Nudge.tick(mono=t, wall=10_000, hist=self.hist)

    def test_a_look_quip_comes_once_a_day_and_is_never_spoken(self):
        A = self.server.Ambient
        A.night = True
        self.tick(1000)
        sent = self.sent()
        self.assertEqual([(k, s) for k, _, s in sent], [("night", False)])
        self.tick(1400)                                      # still night: no new edge
        A.night = False
        self.tick(1500)
        A.night = True                                       # turns on again the same day: the cooldown holds
        self.tick(2000)
        self.assertEqual(self.sent(), [])
        A.night = False
        self.tick(80000)
        A.night = True
        self.tick(90000)                                     # the next day
        self.assertEqual([k for k, _, _ in self.sent()], ["night"])

    def test_rain_and_snow_are_their_own_kinds(self):
        S = self.server
        with mock.patch.object(S, "quip", side_effect=lambda e, **k: "q-" + e):
            S.Ambient.weather = "snow"
            self.tick(1000)
            S.Ambient.weather = "rain"
            self.tick(1400)                                  # a different kind: its own cooldown
        self.assertEqual(self.sent(), [("snow", "q-snow", False), ("rain", "q-rain", False)])

    def test_a_cooldown_drop_does_not_lose_tonights_quip(self):
        A, N = self.server.Ambient, self.server.Nudge
        A.night = True
        self.tick(1000)
        self.assertEqual(len(self.sent()), 1)
        A.night = False
        self.tick(2000)
        A.night = True                                       # tomorrow's edge, a little before 20 hours are up
        self.tick(1000 + 70000)
        self.assertEqual(self.sent(), [])
        self.assertFalse(N.quipped["night"])                 # re-armed
        self.tick(1000 + 72100)                              # still night: now it comes
        self.assertEqual([k for k, _, _ in self.sent()], ["night"])

    def test_off_means_off(self):
        S = self.server
        S.CFG["react_quips"] = False
        S.Ambient.night = S.Ambient.party = True
        self.tick(1000)
        self.assertEqual(self.sent(), [])

    def test_a_coding_quip_after_two_hours_once_per_session(self):
        S = self.server
        D = S.Desk
        D.coding_since = 100.0
        with mock.patch.object(S, "quip", side_effect=lambda e, **k: f"{e}:{k.get('n')}"):
            self.tick(100 + 7000)
            self.assertEqual(self.sent(), [])
            self.tick(100 + 7300)
            self.assertEqual(self.sent(), [("coding", "coding:2", False)])
            self.tick(100 + 7400)                            # same session: not again
            self.tick(100 + 14500)
            self.assertEqual(self.sent(), [])
            D.coding_since = 20000.0                         # a new session
            self.tick(20000 + 7300)
            self.assertEqual([k for k, _, _ in self.sent()], ["coding"])


if __name__ == "__main__":
    unittest.main()
