import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
import screens  # noqa: E402


SIDE = [(0, 0, 2560, 1440), (2560, 0, 2560, 1440)]
OFFSET = [(0, 0, 1920, 1080), (1920, 200, 2560, 1440)]


class DragScreensTest(unittest.TestCase):
    def test_strict_monitor_and_drag_place(self):
        self.assertIsNone(screens.mon_strict(OFFSET, 1920, 100))
        self.assertEqual(screens.mon_strict(SIDE, 2559, 500), 0)
        self.assertEqual(screens.mon_strict(SIDE, 2560, 500), 1)
        off = (170, 165)
        self.assertEqual(screens.drag_place(SIDE, (2559, 500), off, 0), (0, 2389, 335))
        self.assertEqual(screens.drag_place(SIDE, (2560, 500), off, 0), (1, -170, 335))
        self.assertEqual(screens.drag_place(OFFSET, (1930, 600), off, 0), (1, -160, 235))
        self.assertEqual(screens.drag_place(OFFSET, (1920, 100), off, 0), (0, 1750, -65))
        self.assertEqual(screens.clamp_on(SIDE[1], -170, 335, 340, 460), (0, 335))
        self.assertEqual(screens.clamp_on(OFFSET[1], 2600, 1500, 340, 460), (2220, 980))

    def test_dock_shared_outer_and_offset_edges(self):
        self.assertIsNone(screens.dock_edge(SIDE, 0, (2555, 600)))
        self.assertEqual(screens.dock_edge(SIDE, 1, (5115, 600)), "right")
        self.assertEqual(screens.dock_edge(OFFSET, 0, (1915, 100)), "right")
        self.assertIsNone(screens.dock_edge(OFFSET, 0, (1915, 600)))
        self.assertEqual(screens.dock_edge(OFFSET, 1, (4475, 600)), "right")

    def test_corner_tries_outer_edge_after_shared_edge(self):
        self.assertEqual(screens.dock_edge(SIDE, 0, (2559, 5)), "top")
        self.assertEqual(screens.dock_edge(OFFSET, 0, (1919, 1060)), "bottom")

    def test_narrow_middle_is_still_a_shared_edge(self):
        geoms = [(0, 0, 100, 100), (100, 0, 20, 100), (120, 0, 100, 100)]
        self.assertIsNone(screens.dock_edge(geoms, 0, (99, 50)))
        self.assertIsNone(screens.dock_edge(geoms, 1, (119, 50)))

    def test_drag_by_crosses_shared_edge_and_collects_outer_overflow(self):
        ball = (170, 165)
        self.assertEqual(screens.outer_clamp(SIDE, 0, 2500, 300, 340, 460, ball),
                         (2500, 300, 0, 0))
        self.assertEqual(screens.mon_strict(SIDE, 2500 + ball[0], 300 + ball[1]), 1)
        self.assertEqual(screens.outer_clamp(SIDE, 1, 4820, 300, 340, 460, ball),
                         (4780, 300, 40, 0))
        self.assertEqual(screens.outer_clamp(SIDE, 0, -45, -20, 340, 460, ball),
                         (0, 0, -45, -20))
        self.assertEqual(screens.outer_clamp(OFFSET, 0, 1600, 0, 340, 460, ball),
                         (1580, 0, 20, 0))
        self.assertEqual(screens.outer_clamp(OFFSET, 0, 1800, 400, 340, 460, ball),
                         (1800, 400, 0, 0))

    def test_saved_name_and_stale_name(self):
        names = [("DP-3", 0), ("DP-1", 1)]
        p = screens.pos_dict({"other": 7}, 1, 42, 51, "DP-3", False)
        self.assertEqual(p, {"other": 7, "mon": 1, "x": 42, "y": 51,
                             "name": "DP-3", "mons": {"DP-3": [42, 51]}})
        self.assertEqual(screens.pick_monitor(p, names, 2), 0)
        self.assertIsNone(screens.pick_monitor({"mon": 1, "name": "disconnected"}, names, 2))
        self.assertEqual(screens.pick_monitor({"mon": 1}, names, 2), 1)
        self.assertIsNone(screens.pick_monitor({"mon": 3}, names, 2))
        self.assertIsNone(screens.pick_monitor({"mon": -1}, names, 2))
        self.assertIsNone(screens.pick_monitor({}, names, 2))
        screens.pos_dict(p, 0, 80, 90, None, False)
        self.assertNotIn("name", p)
        self.assertEqual(p["mons"]["DP-3"], [42, 51])
        screens.pos_dict(p, 0, 100, 110, "DP-1", True)
        self.assertNotIn("DP-1", p["mons"])

    def test_focus_blocked_during_and_after_drag(self):
        blocked = screens.focus_blocked
        self.assertTrue(blocked(True, False, None, 10, None))
        self.assertTrue(blocked(False, True, None, 10, None))
        self.assertTrue(blocked(False, False, (0, 0), 10, None))
        self.assertTrue(blocked(False, False, None, 10.599, 10))
        self.assertFalse(blocked(False, False, None, 10.6, 10))
        self.assertFalse(blocked(False, False, None, 10, None))

    @unittest.expectedFailure
    def test_hypr_exists_before_first_load_pos(self):
        # until plan step 3
        source = (ROOT / "app/window.py").read_text()
        self.assertLess(source.index("self.hypr = Hypr()"), source.index("self._load_pos()"))


if __name__ == "__main__":
    unittest.main()
