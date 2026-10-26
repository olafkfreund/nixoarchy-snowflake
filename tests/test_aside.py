import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import aside  # noqa: E402


class AsideTest(unittest.TestCase):
    def test_layer_event_exact(self):
        self.assertEqual(aside.layer_event(b"openlayer>>nixi"), "open")
        self.assertEqual(aside.layer_event(b"closelayer>>nixi"), "close")
        for bad in (b"openlayer>>nixi-companion", b"closelayer>>nixi-companion", b"openlayer>>xnixi", b"focusedmon>>DP-1,1", b""):
            self.assertIsNone(aside.layer_event(bad), bad)

    def test_card_monitor(self):
        L = {"DP-1": {"levels": {"0": [], "3": [{"namespace": "nixi-companion"}]}},
             "DP-2": {"levels": {"3": [{"namespace": "waybar"}, {"namespace": "nixi"}]}}}
        self.assertEqual(aside.card_monitor(L), "DP-2")
        self.assertIsNone(aside.card_monitor({"DP-1": L["DP-1"]}))
        self.assertIsNone(aside.card_monitor(None))

    def test_side_and_target(self):
        self.assertEqual(aside.side(100, 340, 1920), "left")
        self.assertEqual(aside.side(1500, 340, 1920), "right")
        self.assertEqual(aside.target(1920, 1080, 1500, 340, 460), (1570, int(1080 * 0.38 - 230)))
        self.assertEqual(aside.target(1920, 1080, 0, 340, 460)[0], 10)
        self.assertEqual(aside.target(1920, 300, 0, 340, 460)[1], 0)      # clamped to a short monitor

    def test_plan(self):
        self.assertEqual(aside.plan(2560, False), "side")      # 15% each side of a card capped at 70%: 384
        self.assertEqual(aside.plan(1920, True), "monitor")    # 288 < 290: his padded strip, a margin in
        self.assertEqual(aside.plan(1280, True), "monitor")    # 192 < 220
        self.assertEqual(aside.plan(1280, False), "hover")

    def test_return_unless_moved(self):
        self.assertTrue(aside.may_return((0, 10, 5), (0, 10, 5)))
        self.assertFalse(aside.may_return((0, 12, 5), (0, 10, 5)))
        self.assertFalse(aside.may_return((1, 10, 5), (0, 10, 5)))
        self.assertFalse(aside.may_return((0, 10, 5), None))


if __name__ == "__main__":
    unittest.main()
