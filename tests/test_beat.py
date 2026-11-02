import array
import sys
import unittest
from unittest import mock

from test_speakable import _ServerEnv


class BeatTest(_ServerEnv):
    """#138 B3: when the beat recorder may run, the level maths, and the read loop (against a fake recorder)."""

    def gates(self, **over):
        S = self.server
        g = dict(look_beat=True, music=True, meeting=False, asleep=False, subs=[object()])
        g.update(over)
        return (mock.patch.dict(S.CFG, {"look_beat": g["look_beat"]}), mock.patch.object(S.Ambient, "music", g["music"]),
                mock.patch.object(S.Ambient, "meeting", g["meeting"]), mock.patch.object(S.Wake, "asleep", g["asleep"]),
                mock.patch.object(S.BUS, "subs", g["subs"]))

    def want(self, **over):
        ps = self.gates(**over)
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        return self.server.Beat.want()

    def test_want_needs_every_gate(self):
        self.assertTrue(self.want())
        for k, v in dict(look_beat=False, music=False, meeting=True, asleep=True, subs=[]).items():
            mock.patch.stopall()
            self.assertFalse(self.want(**{k: v}), k)

    def test_level_rises_on_a_kick_and_falls_back(self):
        L = self.server.Beat.level
        avg, v = None, 0
        for _ in range(40):
            avg, v = L(avg, 100.0)
        self.assertEqual(v, 0)                                # steady: no kick
        avg, v = L(avg, 3000.0)
        self.assertGreater(v, .5)                             # a loud block over a quiet bed
        for _ in range(200):
            avg, v = L(avg, 3000.0)
        self.assertLess(v, .1)                                # steady loud: the bed caught up
        self.assertEqual(L(None, 0.0)[1], 0)                  # silence is not a kick

    def test_run_publishes_levels_from_a_recorder(self):
        S = self.server
        quiet, loud = array.array("h", [100] * 100).tobytes(), array.array("h", [20000] * 100).tobytes()
        script = "import sys,time; w=sys.stdout.buffer.write; [w(%r) for _ in range(30)]; w(%r); sys.stdout.flush(); time.sleep(.3)" % (quiet, loud)
        seen = []
        with mock.patch.object(S.Beat, "cmd", return_value=[sys.executable, "-c", script]), mock.patch.object(S.Beat, "want", return_value=True), \
                mock.patch.object(S.BUS, "pub", side_effect=lambda **e: seen.append(e)):
            S.Beat.run()
        self.assertTrue(seen and all(e["t"] == "beat" for e in seen))
        self.assertEqual(seen[0]["v"], 0)
        self.assertGreater(max(e["v"] for e in seen), .5)

    def test_no_recorder_no_thread(self):
        S = self.server
        with mock.patch.object(S.Beat, "cmd", return_value=None):
            self.assertIsNone(S.Beat.run())


if __name__ == "__main__":
    unittest.main()
