import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
import room  # noqa: E402


def window_methods(*names):
    """Load selected methods without importing window.py's GTK dependencies."""
    tree = ast.parse((ROOT / "app/window.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "NixiWindow")
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
    code = compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(
        name="Window", bases=[], keywords=[], body=methods, decorator_list=[])], type_ignores=[])),
        str(ROOT / "app/window.py"), "exec")
    ns = dict(split_room=room.split_room, W=340, H=460, WIDE=470, GLIDE=0.3, CODE_SIDE=100,
              BAR_SIDE=70, json=json, os=__import__("os"), GLib=SimpleNamespace(
                  timeout_add=Mock(return_value=1), source_remove=Mock()),
              time=__import__("time"), math=__import__("math"),
              GtkLayerShell=SimpleNamespace(Edge=SimpleNamespace(LEFT=0, TOP=1),
                                            set_margin=Mock(), set_monitor=Mock()),
              screens=__import__("screens"), threading=SimpleNamespace(Thread=Mock()), log=Mock())
    exec(code, ns)
    return ns


class RoomTest(unittest.TestCase):
    def test_monitor_edges_and_height(self):
        mon = (0, 0, 1000, 900)
        cases = [
            ((300, 100, 340, 460, 200, 100, (0, 0), mon), (100, 100, 0, 100)),
            ((0, 100, 340, 460, 200, 100, (0, 0), mon), (0, 200, 0, 100)),
            ((660, 100, 340, 460, 200, 100, (0, 0), mon), (200, 0, 0, 100)),
            ((300, 440, 340, 460, 200, 100, (0, 0), mon), (100, 100, 100, 100)),
            ((0, 0, 340, 460, 2000, 2000, (0, 0), mon), (0, 660, 0, 440)),
            ((2020, 300, 340, 460, 200, 200, (0, 0), (1920, 200, 1000, 900)),
             (100, 100, 0, 200)),
        ]
        for args, expected in cases:
            with self.subTest(args=args):
                self.assertEqual(room.split_room(*args), expected)

    def test_side_room_overflow_and_panel_only(self):
        mon = (0, 0, 1000, 900)
        self.assertEqual(room.split_room(0, 100, 340, 460, 0, 0, (100, 100), mon), (0, 200, 0, 0))
        self.assertEqual(room.split_room(0, 100, 340, 460, 0, 0, (130, 100), mon), (0, 230, 0, 0))
        for x, expected in ((0, (0, 0, 0, 0)), (330, (130, 0, 0, 0)),
                            (660, (130, 0, 0, 0))):
            with self.subTest(x=x):
                self.assertEqual(room.split_room(x, 100, 340, 460, 0, 0, (130, 0), mon), expected)

    def test_panel_only_wide_on_and_code_overflow(self):
        ns = window_methods("set_wide")
        for x, expected in ((0, (0, 340)), (330, (130, 470)), (660, (130, 470))):
            with self.subTest(x=x):
                w = ns["Window"]()
                w.layer, w.mx, w.my = True, x, 100
                w.wide_shift = w.top_shift = 0
                w.cur_w, w.cur_h = 340, 460
                w.want_panel = w.want_code = w.want_bar = w.hover = False
                w.want_xw = w.want_h = 0
                w._geom = lambda: (None, SimpleNamespace(width=1000, height=900))
                w.win = SimpleNamespace(set_size_request=Mock(), resize=Mock(), queue_draw=Mock())
                w._place, w._js = Mock(), Mock()
                w.set_wide(True)
                self.assertEqual((w.wide_shift, w.cur_w), expected)
                if x == 0:
                    w.set_wide(True, "code")
                    self.assertEqual((w.wide_shift, w.cur_w), (0, 570))

    def test_layer_and_floating_moves_and_restores(self):
        ns = window_methods("set_wide")
        geom = SimpleNamespace(x=1920, y=200, width=1000, height=900)
        ns["Gdk"] = SimpleNamespace(Display=SimpleNamespace(get_default=lambda: SimpleNamespace(
            get_monitor_at_point=lambda x, y: SimpleNamespace(get_geometry=lambda: geom))))
        for layer in (True, False):
            with self.subTest(layer=layer):
                w = ns["Window"]()
                w.layer, w.mx, w.my = layer, 100 if layer else 2020, 440 if layer else 640
                w.wide_shift = w.top_shift = 0
                w.cur_w, w.cur_h = 340, 460
                w.want_panel = w.want_code = w.want_bar = w.hover = False
                w.want_xw = w.want_h = 0
                w.win = SimpleNamespace(set_size_request=Mock(), resize=Mock(), queue_draw=Mock())
                w.hypr = SimpleNamespace(ok=lambda: False, addr=None)
                w._geom = lambda: (None, SimpleNamespace(width=1000, height=900))
                w._place, w._xmove, w._js = Mock(), Mock(), Mock()
                w.set_wide((200, 100), "size")
                self.assertEqual((w.wide_shift, w.top_shift, w.cur_w, w.cur_h), (100, 100, 540, 560))
                move = w._place if layer else w._xmove
                move.assert_called_with(0 if layer else 1920, 340 if layer else 540)
                w.mx, w.my = (0, 340) if layer else (1920, 540)
                w.set_wide((0, 0), "size")
                move.assert_called_with(100 if layer else 2020, 440 if layer else 640)

    def test_floating_drag_saves_base_after_upward_growth(self):
        ns = window_methods("_moved", "_save_xpos", "_send_corner")
        w = ns["Window"]()
        w.mx, w.my, w.wide_shift, w.top_shift = 1920, 540, 100, 100
        w.hover = w.bar = False
        w.save_t = None
        w.layer = False
        w._mon_at = lambda x, y: (1, SimpleNamespace(x=1920, y=200, width=1000, height=900))
        w._js = Mock()
        with tempfile.TemporaryDirectory() as tmp:
            ns["POS_FILE"] = str(Path(tmp) / "pos.json")
            self.assertFalse(w._moved(SimpleNamespace(get_position=lambda: (1940, 550)), None))
            w._save_xpos()
            self.assertEqual(json.loads(Path(ns["POS_FILE"]).read_text()), {"gx": 2040, "gy": 650})
            w.wide_shift = w.top_shift = 0
            w.mx, w.my = 2040, 650
            self.assertEqual((w.mx, w.my), (2040, 650))

    def test_layer_place_and_saved_base(self):
        ns = window_methods("_place", "_save_pos")
        w = ns["Window"]()
        w.layer, w.mon_i = True, 0
        w.mx, w.my, w.wide_shift, w.top_shift = 100, 440, 100, 100
        w.cur_w, w.cur_h = 540, 560
        w.win = object()
        w.hypr = SimpleNamespace(ok=lambda: False)
        w.bar = False
        w._geom = lambda: (None, SimpleNamespace(width=1000, height=900))
        w._hmons, w._send_corner = Mock(return_value=[]), Mock()
        with tempfile.TemporaryDirectory() as tmp:
            ns["POS_FILE"] = str(Path(tmp) / "pos.json")
            w._place(80, 340)
            w._save_pos()
            saved = json.loads(Path(ns["POS_FILE"]).read_text())
            self.assertEqual((saved["x"], saved["y"]), (180, 440))
            self.assertEqual((w.mx, w.my), (80, 340))

    def test_corner_uses_base_position(self):
        ns = window_methods("_send_corner")
        w = ns["Window"]()
        w.mx, w.my, w.wide_shift, w.top_shift = 100, 340, 100, 100
        w.layer = True
        w._geom = lambda: (None, SimpleNamespace(width=1000, height=900))
        w._js = Mock()
        w._send_corner()
        w._js.assert_called_with("window.nixiCorner&&nixiCorner('bl')")

    def test_hover_and_monitor_use_base(self):
        ns = window_methods("set_hover", "go_monitor")
        w = ns["Window"]()
        w.mx, w.my, w.wide_shift, w.top_shift = 1920, 540, 100, 100
        w.mon_i, w.layer, w.hover, w.bar, w.cur_w, w.cur_h = 0, False, False, False, 340, 460
        w.hypr = SimpleNamespace(ok=lambda: True)
        w._x11, w._hmons = lambda: False, lambda: [("first", 0, False), ("second", 1, True)]
        w._mon_at = Mock(return_value=(0, None))
        w._monitors = lambda: [SimpleNamespace(get_geometry=lambda: None),
                               SimpleNamespace(get_geometry=lambda: SimpleNamespace(
                                   x=3000, y=200, width=1000, height=900))]
        w._save_xpos, w._xmove, w._rewide, w._send_corner = Mock(), Mock(), Mock(), Mock()
        w.set_wide = Mock()
        w._js, w.cursor_hidden, w._follow = Mock(), Mock(), Mock()
        w.glide_n = 0
        with tempfile.TemporaryDirectory() as tmp:
            ns["POS_FILE"] = str(Path(tmp) / "pos.json")
            self.assertTrue(w.go_monitor("second"))
        w._mon_at.assert_called_with(2190, 870)
        w._xmove.assert_called_with(3550, 530)
        w.set_hover(True)
        self.assertEqual(w.home, (0, 2020, 640))

    def test_hover_collapses_upward_growth_and_restores_at_home(self):
        ns = window_methods("set_hover", "set_wide", "_glide_home", "_rewide")
        geom = SimpleNamespace(x=0, y=0, width=1000, height=900)
        ns["Gdk"] = SimpleNamespace(Display=SimpleNamespace(get_default=lambda: SimpleNamespace(
            get_monitor_at_point=lambda x, y: SimpleNamespace(get_geometry=lambda: geom))))
        ns["GLib"].idle_add = Mock(side_effect=lambda fn, *args: fn(*args))
        w = ns["Window"]()
        w.layer, w.mon_i, w.mx, w.my = False, 0, 200, 340
        w.wide_shift, w.top_shift, w.cur_w, w.cur_h = 100, 100, 540, 560
        w.want_panel = w.want_code = w.want_bar = w.bar = False
        w.want_xw, w.want_h = 200, 100
        w.hover, w.hpos = False, None
        w.hypr = SimpleNamespace(ok=lambda: True, addr=None)
        w.win = SimpleNamespace(set_size_request=Mock(), resize=Mock(), queue_draw=Mock(), move=Mock())
        w._x11, w._js, w.cursor_hidden, w._follow = lambda: False, Mock(), Mock(), Mock()
        w._xmove = lambda x, y: (setattr(w, "mx", x), setattr(w, "my", y))
        w._glide_home = Mock(side_effect=lambda: ns["Window"]._glide_home(w))
        ns["threading"].Thread = Mock(side_effect=lambda target, daemon: SimpleNamespace(start=target))
        w.set_hover(True)
        self.assertEqual((w.wide_shift, w.top_shift, w.cur_w, w.cur_h), (0, 0, 340, 460))
        self.assertEqual(w.home, (0, 300, 440))
        w.set_hover(False)
        self.assertEqual((w.mx + w.wide_shift, w.my + w.top_shift), (300, 440))
        self.assertEqual((w.wide_shift, w.top_shift, w.cur_w, w.cur_h), (100, 100, 540, 560))

    def test_bar_uses_base_top_for_dock_and_restore(self):
        ns = window_methods("set_bar")
        w = ns["Window"]()
        w.layer, w.mon_i, w.mx, w.my = True, 0, 200, 340
        w.wide_shift, w.top_shift = 100, 100
        w.glide_n = 0
        w.bar, w.dragging, w.pmoving, w.dpos = None, False, False, None
        w.hypr = SimpleNamespace(ok=lambda: False)
        w._geom = lambda: (None, SimpleNamespace(width=1000, height=900))
        w._glide_to, w._place, w._js, w.set_wide = Mock(), Mock(), Mock(), Mock()
        w.set_bar("top")
        self.assertEqual(w.bar_home, (0, 300, 440))
        w._glide_to.assert_called_with(230, -100, None)
        w.set_bar(None)
        w._glide_to.assert_called_with(200, 340)
        w.set_bar("top")
        w.set_bar(None, glide=False)
        w._place.assert_called_with(200, 340, True, 0)

        w.layer, w.bar, w.mx, w.my = False, None, 2020, 540
        w._x11 = lambda: True
        area = SimpleNamespace(x=1920, y=200, width=1000, height=900)
        w.win = SimpleNamespace(get_position=lambda: (2020, 540))
        w._mon_at = lambda x, y: (0, None)
        w._monitors = lambda: [SimpleNamespace(get_workarea=lambda: area)]
        w._xmove = Mock()
        w.set_bar("top")
        self.assertEqual(w.bar_home, (0, 2120, 640))
        w._glide_to.assert_called_with(2150, 100, None)
        w.set_bar(None, glide=False)
        w._xmove.assert_called_with(2020, 540)


if __name__ == "__main__":
    unittest.main()
