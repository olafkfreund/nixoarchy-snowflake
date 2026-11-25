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
import aside  # noqa: E402
import size  # noqa: E402
import termfont  # noqa: E402
from size import page_zoom, step, text_clamp, text_step, zooms  # noqa: E402


def window_methods(*names):
    """Load selected methods without importing window.py's GTK dependencies."""
    tree = ast.parse((ROOT / "app/window.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "NixiWindow")
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in (*names, "_px", "_css", "_region_rect")]
    code = compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(
        name="Window", bases=[], keywords=[], body=methods, decorator_list=[])], type_ignores=[])),
        str(ROOT / "app/window.py"), "exec")
    ns = dict(split_room=room.split_room, W=340, H=460, BALL=(170, 165), WIDE=470, GLIDE=0.3, CODE_SIDE=100,
              BAR_SIDE=70, json=json, os=__import__("os"), GLib=SimpleNamespace(
                  timeout_add=Mock(return_value=1), source_remove=Mock()),
              time=__import__("time"), math=__import__("math"), size=size, termfont=termfont,
              window_size=size.clamp,
              GtkLayerShell=SimpleNamespace(Edge=SimpleNamespace(LEFT=0, TOP=1),
                                            set_margin=Mock(), set_monitor=Mock()),
              screens=__import__("screens"), threading=SimpleNamespace(Thread=Mock()), log=Mock())
    ns["idle"] = []                                  # queued like GTK's: run with run_idle()
    ns["GLib"].idle_add = lambda fn, *args: ns["idle"].append((fn, args))
    exec(code, ns)
    return ns


def run_idle(ns):
    while ns["idle"]:
        fn, args = ns["idle"].pop(0)
        fn(*args)


ZOOM = ("_apply_zoom", "_zoom_spot", "_page_at", "_size_page", "_apply_page", "_push_zoom")
PLACE = ("_size_spot", "_page_at", "_size_page", "_apply_page")


def zoom_window(ns, x0=0, layer=True):
    """A free window on a 1280x720 monitor at 16px / Card text 200%."""
    w = ns["Window"]()
    w.size, w.card_text, w.term_px, w.z = 0.75, 2.0, 16, 1.0
    w.layer, w.mon_i, w.mx, w.my, w.wide_shift, w.top_shift = layer, 0, x0, 0, 0, 0
    w.bar, w.hover, w.hover_return, w.zoom_spot = None, False, False, None
    w.want_xw = w.want_h = 0
    w.mon = SimpleNamespace(x=0, y=0, width=1280, height=720)
    w._geom = lambda i=None: (None, w.mon)
    w.view = SimpleNamespace(set_zoom_level=Mock())
    w.win = SimpleNamespace(set_size_request=Mock(), resize=Mock())
    w.set_wide, w.set_bar, w._apply_region, w._js = Mock(), Mock(), Mock(), Mock()
    return w


def startup(ns, tmp, saved, *mons, layer=True):
    """A window as __init__ has it when it loads the saved spot: unplaced, zoomed for no monitor."""
    w = zoom_window(ns, layer=layer)
    w.z = 32 / 14
    w.hypr = SimpleNamespace(ok=lambda: False)
    w._monitors = lambda: [SimpleNamespace(get_geometry=lambda g=g: g) for g in mons]
    w._geom = lambda i=None: (None, mons[w.mon_i if i is None else i])
    w._set_monitor = Mock()
    w.win.move = Mock()
    if layer:
        del w.view
    ns["POS_FILE"] = str(Path(tmp) / "pos.json")
    if saved is not None:
        Path(ns["POS_FILE"]).write_text(json.dumps(saved))
    return w


def screen(x, width, height):
    return SimpleNamespace(x=x, y=0, width=width, height=height)


def pushed(w):
    script = w._js.call_args.args[0]
    return json.loads(script.removeprefix("window.nixiZoom&&nixiZoom(").removesuffix(")"))


class RoomTest(unittest.TestCase):
    def test_window_zoom_applies_only_changed_page_and_always_pushes(self):
        ns = window_methods(*ZOOM)
        w = zoom_window(ns, x0=900)
        w.card_text, w.z = 1.0, 16 / 14
        w.mon = SimpleNamespace(x=0, y=0, width=2560, height=1440)
        w._push_zoom = Mock()
        w._apply_zoom()
        w.view.set_zoom_level.assert_not_called()
        w._push_zoom.assert_called_once()
        w.card_text = 1.2
        w._apply_zoom()
        w.view.set_zoom_level.assert_called_once_with(19.2 / 14)
        self.assertEqual(w.z, 19.2 / 14)
        self.assertEqual(w._push_zoom.call_count, 2)

    def test_window_pushes_zoom_values_for_current_monitor(self):
        ns = window_methods("_push_zoom")
        w = ns["Window"]()
        w.size, w.card_text, w.term_px, w.layer, w.zoom_spot = 0.75, 1.0, 16, True, None
        w.mx = w.my = w.wide_shift = w.top_shift = 0
        w._geom = lambda: (None, SimpleNamespace(width=2560, height=1440))
        w._js = Mock()
        w._push_zoom()
        script = w._js.call_args.args[0]
        self.assertEqual(json.loads(script.removeprefix("window.nixiZoom&&nixiZoom(").removesuffix(")")),
                         {"page": 16 / 14, "nk": 0.75 / (16 / 14), "cardPx": 16,
                          "monW": 2560, "size": 0.75, "cardText": 1.0})

    def test_zoom_and_text_messages_update_separate_settings(self):
        ns = window_methods("_on_msg", "set_zoom", "set_text")
        w = ns["Window"]()
        w.size, w.card_text = 0.75, 1.0
        w._apply_zoom = Mock()
        for msg in ("zoom:1.25", "text:1.5", "rezoom"):
            w._on_msg(None, SimpleNamespace(get_js_value=lambda msg=msg: SimpleNamespace(to_string=lambda: msg)))
        self.assertEqual((w.size, w.card_text), (1.25, 1.5))
        self.assertEqual(w._apply_zoom.call_count, 3)
        w._apply_zoom.assert_called_with(reread=True)

    def test_aside_plan_uses_scaled_strip_and_visible_width(self):
        self.assertEqual(aside.plan(1920, True), "monitor")
        self.assertEqual(aside.plan(1920, True, 340 * 0.75, aside.VISIBLE_W * 0.75), "side")

    def test_keyboard_size_steps_and_limits(self):
        self.assertEqual(step(1.2, "up"), 1.25)
        self.assertEqual(step(0.55, "down"), 0.5)
        self.assertEqual(step(0.6, "reset"), 0.75)

    def test_card_zoom(self):
        page, nixi, target = zooms(0.75, 1.0, 16, 2560, 1440)
        self.assertAlmostEqual(page, 16 / 14)
        self.assertAlmostEqual(nixi, 0.75 / page)
        self.assertEqual(target, 16)
        self.assertEqual(zooms(1.25, 1.0, 16, 2560, 1440)[:2], (1.25, 1.0))
        self.assertEqual(zooms(0.75, 1.0, None, 2560, 1440)[2], 16)
        self.assertAlmostEqual(zooms(0.75, 2.0, 16, 1280, 720)[0], 720 / 460)
        self.assertEqual(zooms(1.25, 1.0, 16, 960, 540)[:2], (1.25, 1.0))
        self.assertEqual(zooms(0.75, 2.0, 28, None, None)[0], 2.5)
        for size in (0.5, 0.75, 1.0, 1.25):
            for card_text in (0.6, 1.0, 2.0):
                for monitor in ((None, None), (960, 540), (1280, 720), (2560, 1440)):
                    with self.subTest(size=size, card_text=card_text, monitor=monitor):
                        page, nixi, _ = zooms(size, card_text, 16, *monitor)
                        self.assertLessEqual(nixi, 1.0)
                        self.assertAlmostEqual(page * nixi, size)

    def test_card_zoom_position_cap(self):
        self.assertEqual(zooms(0.75, 2.0, 16, 1280, 720, None),
                         zooms(0.75, 2.0, 16, 1280, 720))
        self.assertEqual(zooms(0.75, 2.0, 16, None, None, 500),
                         zooms(0.75, 2.0, 16, None, None))
        for mon_w, mon_h, size_value, x0, expected in (
            (1280, 720, 0.75, 0, 1.565),
            (1280, 720, 0.75, 748, 1.565),
            (1280, 720, 0.75, 374, 1.224),
            (1280, 720, 0.75, 100, 1.565),
            (2560, 1440, 0.75, 900, 2.25),
            (1024, 768, 1.25, 320, 1.25),
        ):
            with self.subTest(monitor=(mon_w, mon_h), size=size_value, x0=x0):
                page, nixi, target = zooms(size_value, 2.0, 16, mon_w, mon_h, x0)
                self.assertAlmostEqual(page, expected, places=3)
                self.assertAlmostEqual(page * nixi, size_value)
                self.assertEqual(target, 32)

    def test_card_text_steps_and_limits(self):
        self.assertEqual((text_step(1.0, "up"), text_step(1.0, "down")), (1.1, 0.9))
        self.assertEqual(text_step(1.5, "reset"), 1.0)
        self.assertEqual((text_step(2.0, "up"), text_step(0.6, "down")), (2.0, 0.6))
        self.assertEqual((text_clamp("bad"), text_clamp(float("inf"))), (1.0, 1.0))
        self.assertEqual((text_clamp(0.1), text_clamp(3)), (0.6, 2.0))
        self.assertEqual((page_zoom("bad"), page_zoom(float("nan"))), (1.0, 1.0))
        self.assertEqual((page_zoom(0.1), page_zoom(3)), (0.5, 2.5))
        with self.assertRaises(ValueError):
            text_step(1.0, "sideways")

    def test_layer_size_growth_clamps_base_before_room(self):
        ns = window_methods("set_wide")
        w = ns["Window"]()
        w.z = 1.0
        w.layer, w.mx, w.my = True, 1706, 794
        w.wide_shift = w.top_shift = 0
        w.cur_w, w.cur_h = 204, 276  # 60% size before growing to 100%
        w.want_panel = w.want_code = w.want_bar = w.hover = False
        w.want_xw = w.want_h = 0
        w._geom = lambda: (None, SimpleNamespace(width=1920, height=1080))
        w.win = SimpleNamespace(set_size_request=Mock(), resize=Mock(), queue_draw=Mock())
        w._place, w._js = Mock(), Mock()

        w.set_wide((0, 0), "size")

        self.assertEqual((w.cur_w, w.cur_h), (340, 460))
        w._place.assert_called_once_with(1580, 620)

    def test_zoom_converts_regions_and_room_requests(self):
        ns = window_methods("set_wide")
        w = ns["Window"]()
        w.z = 0.6
        self.assertEqual((w._px(340), w._px(460)), (204, 276))
        self.assertEqual(w._region_rect((10, 20, 101, 51)), (6, 12, 61, 31))
        w.layer, w.mx, w.my = True, 300, 200
        w.wide_shift = w.top_shift = 0
        w.cur_w, w.cur_h = 204, 276
        w.want_panel = w.want_code = w.want_bar = w.hover = False
        w.want_xw = w.want_h = 0
        w._geom = lambda: (None, SimpleNamespace(width=1000, height=900))
        w.win = SimpleNamespace(set_size_request=Mock(), resize=Mock(), queue_draw=Mock())
        w._place, w._js = Mock(), Mock()
        w.set_wide((200, 100), "size")
        self.assertEqual((w.want_xw, w.want_h), (120, 60))
        self.assertEqual((w.wide_shift, w.top_shift, w.cur_w, w.cur_h), (60, 0, 324, 336))
        w._js.assert_called_with("window.nixiLayout&&nixiLayout(100.0,0.0)")

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
        ns = window_methods("_moved", "_arm_settle", "_settle_xpos", "_save_xpos", "_send_corner")
        w = ns["Window"]()
        w._button_held = lambda: False
        w.mx, w.my, w.wide_shift, w.top_shift = 1920, 540, 100, 100
        w.hover = w.bar = False
        w.save_t = None
        w.layer = False
        w._mon_at = lambda x, y: (1, SimpleNamespace(x=1920, y=200, width=1000, height=900))
        w._js = Mock()
        w._apply_zoom = Mock()
        with tempfile.TemporaryDirectory() as tmp:
            ns["POS_FILE"] = str(Path(tmp) / "pos.json")
            self.assertFalse(w._moved(SimpleNamespace(get_position=lambda: (1940, 550)), None))
            w._save_xpos()
            self.assertEqual(json.loads(Path(ns["POS_FILE"]).read_text()), {"gx": 2040, "gy": 650})
            w.wide_shift = w.top_shift = 0
            w.mx, w.my = 2040, 650
            self.assertEqual((w.mx, w.my), (2040, 650))

    def _settle_window(self, held):
        ns = window_methods("_moved", "_arm_settle", "_settle_xpos")
        live = set()
        ids = iter(range(1, 100))

        def add(ms, fn):
            i = next(ids)
            live.add(i)
            return i
        ns["GLib"] = SimpleNamespace(timeout_add=add, source_remove=lambda i: live.discard(i))
        w = ns["Window"]()
        w.mx = w.my = 0
        w.hover = w.bar = False
        w.save_t = None
        w._button_held = lambda: held[0]
        w._save_xpos = Mock()
        return w, live

    def test_settle_waits_for_release_with_one_timer(self):
        held = [True]
        w, live = self._settle_window(held)
        w._moved(SimpleNamespace(get_position=lambda: (10, 10)), None)
        w._moved(SimpleNamespace(get_position=lambda: (20, 10)), None)
        self.assertEqual(len(live), 1)                       # a second move replaces the timer
        for _ in range(3):
            self.assertTrue(w._settle_xpos())                 # still held: the same source runs again
            self.assertEqual(len(live), 1)
        w._save_xpos.assert_not_called()
        held[0] = False
        live.discard(w.save_t)                               # (GLib drops a source that returns False)
        self.assertFalse(w._settle_xpos())
        w._save_xpos.assert_called_once()
        self.assertIsNone(w.save_t)

    def test_settle_skips_the_save_once_docked(self):
        held = [False]
        w, live = self._settle_window(held)
        w._moved(SimpleNamespace(get_position=lambda: (10, 10)), None)
        w.bar = "top"                                         # a quick drop into the notch before the timer fired
        self.assertFalse(w._settle_xpos())
        w._save_xpos.assert_not_called()

    def test_undock_save_polls_at_50ms(self):
        src = (ROOT / "app/window.py").read_text()
        self.assertIn("self._arm_settle(50)), False)[1])", src)  # (0 ms would spin the main loop while the button is held)

    def test_undock_settle_and_direct_save_keep_one_timer(self):
        held = [True]
        w, live = self._settle_window(held)
        w._moved(SimpleNamespace(get_position=lambda: (10, 10)), None)
        w._arm_settle(0)                                     # the delayed undock save while a configure timer is pending
        self.assertEqual(len(live), 1)
        self.assertTrue(w._settle_xpos())                    # pulling him out of the notch: still held, no save
        w._save_xpos.assert_not_called()
        pending = w.save_t
        w._save_xpos()                                       # a direct save (go_monitor) leaves the pending timer alone
        self.assertEqual(w.save_t, pending)
        self.assertIn(pending, live)

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
        w._hmons, w._send_corner, w._apply_zoom = Mock(return_value=[]), Mock(), Mock()
        with tempfile.TemporaryDirectory() as tmp:
            ns["POS_FILE"] = str(Path(tmp) / "pos.json")
            w._place(80, 340)
            w._save_pos()
            saved = json.loads(Path(ns["POS_FILE"]).read_text())
            self.assertEqual((saved["x"], saved["y"]), (180, 440))
            self.assertEqual((w.mx, w.my), (80, 340))
            w._apply_zoom.assert_called_once_with()

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
        ns = window_methods("set_hover", "go_monitor", *PLACE)
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
        w._apply_zoom = Mock()
        w.set_wide = Mock()
        w._js, w.cursor_hidden, w._follow = Mock(), Mock(), Mock()
        w.glide_n = 0
        w.hover_return, w.zoom_spot, w.hover_n = True, None, 0
        w.size, w.card_text, w.term_px, w.z = 0.75, 1.0, 14, 1.0
        w.win = SimpleNamespace(set_size_request=Mock(), resize=Mock())
        with tempfile.TemporaryDirectory() as tmp:
            ns["POS_FILE"] = str(Path(tmp) / "pos.json")
            self.assertTrue(w.go_monitor("second"))
        self.assertIsNone(w.zoom_spot)               # (not docked: _apply_zoom tracks it)
        w._mon_at.assert_called_with(2190, 870)
        w._xmove.assert_called_with(3550, 530)
        w.set_hover(True)
        self.assertEqual(w.home, (0, 2020, 640))
        self.assertFalse(w.hover_return)             # hovering again ends a return

    def test_hover_collapses_upward_growth_and_restores_at_home(self):
        ns = window_methods("set_hover", "set_wide", "_glide_home", "_rewide", "_hover_landed")
        geom = SimpleNamespace(x=0, y=0, width=1000, height=900)
        ns["Gdk"] = SimpleNamespace(Display=SimpleNamespace(get_default=lambda: SimpleNamespace(
            get_monitor_at_point=lambda x, y: SimpleNamespace(get_geometry=lambda: geom))))
        w = ns["Window"]()
        w.layer, w.mon_i, w.mx, w.my = False, 0, 200, 340
        w.wide_shift, w.top_shift, w.cur_w, w.cur_h = 100, 100, 540, 560
        w.want_panel = w.want_code = w.want_bar = w.bar = False
        w.want_xw, w.want_h = 200, 100
        w.hover, w.hover_return, w.hover_n, w.hpos = False, False, 0, None
        w._apply_zoom = Mock(side_effect=lambda: self.assertFalse(w.hover_return))
        w.hypr = SimpleNamespace(ok=lambda: True, addr=None)
        w.win = SimpleNamespace(set_size_request=Mock(), resize=Mock(), queue_draw=Mock(), move=Mock())
        w._x11, w._js, w.cursor_hidden, w._follow = lambda: False, Mock(), Mock(), Mock()
        w._xmove = lambda x, y: (setattr(w, "mx", x), setattr(w, "my", y))
        w._glide_home = Mock(side_effect=lambda n, home: ns["Window"]._glide_home(w, n, home))
        ns["threading"].Thread = Mock(side_effect=lambda target, daemon, args=(): SimpleNamespace(start=lambda: target(*args)))
        w.set_hover(True)
        self.assertEqual((w.wide_shift, w.top_shift, w.cur_w, w.cur_h), (0, 0, 340, 460))
        self.assertEqual(w.home, (0, 300, 440))
        w.set_hover(False)
        self.assertTrue(w.hover_return)              # queued, not run inline: still returning
        w._apply_zoom.assert_not_called()
        run_idle(ns)
        self.assertFalse(w.hover_return)
        w._apply_zoom.assert_called_once_with()
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
        w._apply_zoom = Mock()
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

    def test_zoom_spot_tracks_only_while_free(self):
        ns = window_methods("_zoom_spot")
        for state in ("bar", "hover", "hover_return"):
            with self.subTest(state=state):
                w = zoom_window(ns, x0=100)
                w.wide_shift = 40
                self.assertEqual(w._zoom_spot(), (w.mon, 140))
                w.mx = 200
                self.assertEqual(w._zoom_spot(), (w.mon, 240))
                setattr(w, state, True)
                w.mx = 500
                self.assertEqual(w._zoom_spot(), (w.mon, 240))
                w.zoom_spot = None                   # nothing cached: computed even when not free
                self.assertEqual(w._zoom_spot(), (w.mon, 540))

    def test_zoom_spot_window_mode_is_monitor_relative(self):
        ns = window_methods("_zoom_spot")
        w = zoom_window(ns, x0=2000, layer=False)
        w.wide_shift = 20
        right = SimpleNamespace(x=1920, y=0, width=1280, height=720)
        w._mon_at = Mock(return_value=(1, right))
        self.assertEqual(w._zoom_spot(), (right, 100))
        w._mon_at.assert_called_once_with(2020 + 170, w.my + w.top_shift + 165)   # the unscaled ball: a zoom change can't flip it

    def test_push_zoom_uses_cached_spot_or_falls_back(self):
        ns = window_methods("_push_zoom")
        w = zoom_window(ns)
        for spot, expected in (((w.mon, 374), 1.224), (None, 720 / 460)):
            with self.subTest(spot=spot):
                w.zoom_spot = spot
                w._push_zoom()
                self.assertAlmostEqual(pushed(w)["page"], expected, places=3)

    def test_size_page_does_no_room_work_and_apply_page_always_refits(self):
        ns = window_methods("_size_page", "_apply_page")
        w = zoom_window(ns)
        del w.view                                   # before the view exists
        w._size_page(1.5)
        self.assertEqual((w.z, w.cur_w, w.cur_h), (1.5, 510, 690))
        w.win.set_size_request.assert_called_with(510, 690)
        w.win.resize.assert_called_with(510, 690)
        w.set_wide.assert_not_called()
        w._apply_region.assert_not_called()
        # set_wide returns early on an unchanged size: it must not see the new base size already in place
        w.set_wide.side_effect = lambda *a: self.assertNotEqual(w.cur_w, w._px(340))
        w.bar = "top"
        w._apply_page(1.2)
        w.set_wide.assert_called_once()
        w.set_bar.assert_called_once_with("top", glide=False)
        w._apply_region.assert_called_once_with()

    def test_page_change_without_extra_room_still_reclamps_and_tells_page(self):
        ns = window_methods("_size_page", "_apply_page", "set_wide")
        w = zoom_window(ns, x0=940)
        del w.set_wide
        w.cur_w, w.cur_h = 340, 460
        w.want_panel = w.want_code = w.want_bar = False
        w.want_css = (0, 0)
        w.win.queue_draw, w._place = Mock(), Mock()
        w._apply_page(1.5)
        self.assertEqual((w.cur_w, w.cur_h), (510, 690))
        w._place.assert_called_once_with(770, 0)
        w._js.assert_called_once_with("window.nixiLayout&&nixiLayout(0.0,0.0)")

    def test_drag_to_dock_keeps_zoom_on_same_monitor(self):
        ns = window_methods(*ZOOM, "_dock_if_edge")
        w = zoom_window(ns, x0=374)
        w._apply_zoom()
        page = w.z
        self.assertAlmostEqual(page, 1.224, places=3)
        w.set_bar = Mock(side_effect=lambda edge, **kw: setattr(w, "bar", edge))
        w._cursor_or_none, w._mon_at = lambda: (1279, 300), lambda *c: (0, w.mon)
        w._geoms = lambda: [(0, 0, 1280, 720)]
        w.mx = 740                                   # where he was dropped
        w._dock_if_edge()
        w._apply_zoom()
        self.assertEqual(w.z, page)
        w.set_bar.assert_called_once_with("right")

    def test_drag_to_dock_on_another_monitor_sets_spot(self):
        ns = window_methods("_dock_if_edge")
        w = zoom_window(ns, x0=374)
        other = SimpleNamespace(x=1280, y=0, width=1920, height=1080)
        w._cursor_or_none, w._mon_at = lambda: (3199, 300), lambda *c: (1, other)
        w._geoms = lambda: [(0, 0, 1280, 720), (1280, 0, 1920, 1080)]
        w._place = Mock(side_effect=lambda *a: setattr(w, "mon", other))   # (placing him there moves him onto it)
        w.set_bar = Mock(side_effect=lambda edge: self.assertEqual(w.zoom_spot, (other, None)))
        w._dock_if_edge()
        w.set_bar.assert_called_once_with("right")
        # the drag already carried him over (mon_i is the dock screen): the kept spot is still the old screen's
        w = zoom_window(ns, x0=374)
        w.zoom_spot = (SimpleNamespace(x=0, y=0, width=2560, height=1440), 900)
        w.mon, w.mon_i = other, 1
        w._cursor_or_none, w._mon_at = lambda: (3199, 300), lambda *c: (1, other)
        w._geoms = lambda: [(0, 0, 1280, 720), (1280, 0, 1920, 1080)]
        w._place = Mock()
        w.set_bar = Mock(side_effect=lambda edge: self.assertEqual(w.zoom_spot, (other, None)))
        w._dock_if_edge()
        w.set_bar.assert_called_once_with("right")
        w._place.assert_not_called()

    def test_parked_rezooms_before_recording_the_spot(self):
        ns = window_methods("_parked", "_spot")
        w = zoom_window(ns, x0=854)
        w.aside, w._send_corner, w._remap = {"parked": None}, Mock(), Mock()
        w._apply_zoom = Mock(side_effect=lambda: setattr(w, "mx", 748))      # grown page, re-clamped
        w._parked()
        w._apply_zoom.assert_called_once_with()
        self.assertEqual(w.aside["parked"], (0, 748, 0))

    def test_docked_monitor_move_sets_destination_spot(self):
        ns = window_methods("go_monitor", *PLACE)
        dest = SimpleNamespace(x=1280, y=0, width=1920, height=1080)
        for memory, expected in (({"mons": {"second": [600, 20]}}, 600), ({}, None)):
            with self.subTest(memory=memory), tempfile.TemporaryDirectory() as tmp:
                w = zoom_window(ns)
                w.bar, w.bar_home, w.glide_n = "top", None, 0
                w.hypr = SimpleNamespace(ok=lambda: True)
                w._hmons = lambda: [("first", 0, False), ("second", 1, True)]
                w._monitors = lambda: [SimpleNamespace(get_geometry=lambda g=g: g) for g in (w.mon, dest)]
                w._save_pos, w._place, w._rewide, w._send_corner = Mock(), Mock(), Mock(), Mock()
                seen = []
                w._apply_zoom = lambda: seen.append(w.zoom_spot)
                ns["POS_FILE"] = str(Path(tmp) / "pos.json")
                Path(ns["POS_FILE"]).write_text(json.dumps(memory))
                self.assertTrue(w.go_monitor("second"))
                self.assertEqual(seen, [(dest, expected)])

    def test_only_the_latest_hover_return_frees_him(self):
        ns = window_methods("set_hover", "_hover_landed")
        w = zoom_window(ns)
        w.hover_n, w.cur_w, w.cur_h = 0, 340, 460
        w.hypr = SimpleNamespace(ok=lambda: True)
        w.cursor_hidden, w._follow, w._glide_home = Mock(), Mock(), Mock()
        w._rewide, w._apply_zoom = Mock(), Mock()
        for on in (True, False, True, False):
            w.set_hover(on)
        w._hover_landed(2)                           # the first return's landing: stale, does nothing at all
        self.assertTrue(w.hover_return)
        w._apply_zoom.assert_not_called()
        w._rewide.assert_not_called()
        w._hover_landed(4)
        self.assertFalse(w.hover_return)
        w._apply_zoom.assert_called_once_with()
        self.assertEqual(w._rewide.call_count, 1)
        w.set_hover(True)                            # back on during a return: that return is stale too
        w.set_hover(False)
        w.set_hover(True)
        w._hover_landed(6)
        self.assertTrue(w.hover)
        self.assertEqual(w._apply_zoom.call_count, 1)

    def test_layer_startup_sizes_for_the_saved_spot_before_placing(self):
        ns = window_methods("_load_pos", "_place", *PLACE)
        with tempfile.TemporaryDirectory() as tmp:
            w = startup(ns, tmp, {"mon": 0, "x": 748, "y": 0}, screen(0, 1280, 720))
            w._load_pos()
        self.assertEqual((w.mx, w.my, w.cur_w), (748, 0, 532))
        self.assertAlmostEqual(w.z, 1.565, places=3)
        w.win.set_size_request.assert_called_once_with(532, 720)
        w.set_wide.assert_not_called()
        w.set_bar.assert_not_called()

    def test_window_startup_sizes_for_the_saved_spot(self):
        ns = window_methods("_load_xpos", *PLACE)
        with tempfile.TemporaryDirectory() as tmp:
            w = startup(ns, tmp, {"gx": 748, "gy": 0}, screen(0, 1280, 720), layer=False)
            w._load_xpos()
        self.assertEqual((w.mx, w.my, w.cur_w), (748, 0, 532))
        w.view.set_zoom_level.assert_called_once_with(w.z)
        self.assertAlmostEqual(w.z, 1.565, places=3)
        w.win.set_size_request.assert_called_once_with(532, 720)
        w.win.move.assert_called_once_with(748, 0)

    def test_default_corner_is_placed_once_and_stable(self):
        for layer in (True, False):
            ns = window_methods("_load_pos" if layer else "_load_xpos", "_place", *PLACE, *ZOOM)
            # 600x800: the corner's own page is smaller than the one it was placed at, so the gap is 12, not 10
            for mon, page, x, gap in ((screen(0, 1280, 720), 1.565, 738, 10), (screen(0, 600, 800), 0.795, 318, 12)):
                with self.subTest(layer=layer, mon=mon), tempfile.TemporaryDirectory() as tmp:
                    w = startup(ns, tmp, None, mon, layer=layer)
                    (w._load_pos if layer else w._load_xpos)()
                    w._mon_at = lambda *c: (0, mon)
                    self.assertEqual((w.mx, mon.width - w.mx - w.cur_w), (x, gap))
                    self.assertAlmostEqual(w.z, page, places=3)
                    z = w.z
                    w._apply_zoom()
                    self.assertEqual(w.z, z)
                    w.set_wide.assert_not_called()

    def test_window_startup_keeps_a_spot_on_a_seam(self):
        ns = window_methods("_load_xpos", "_zoom_spot", *PLACE)
        mons = screen(0, 2560, 1440), screen(2560, 1280, 720)
        # 2400: the right monitor's own page puts the centre on it. 2260: neither monitor's own page does.
        for gx, page in ((2400, 720 / 460), (2260, 32 / 14)):
            with self.subTest(gx=gx), tempfile.TemporaryDirectory() as tmp:
                w = startup(ns, tmp, {"gx": gx, "gy": 0}, *mons, layer=False)
                w._load_xpos()
                self.assertEqual((w.mx, w.my), (gx, 0))
                self.assertAlmostEqual(w.z, page)
                w._mon_at = lambda x, y: next((i, g) for i, g in enumerate(mons) if g.x <= x < g.x + g.width)
                w.wide_shift = w.top_shift = 0
                self.assertAlmostEqual(w._page_at(*w._zoom_spot()), w.z)   # the first re-zoom keeps it: no flip

    def test_window_startup_falls_back_when_the_monitor_is_gone(self):
        ns = window_methods("_load_xpos", *PLACE)
        with tempfile.TemporaryDirectory() as tmp:
            w = startup(ns, tmp, {"gx": 4000, "gy": 0}, screen(0, 1280, 720), layer=False)
            w._load_xpos()
        self.assertEqual((w.mx, w.my), (738, 0))      # (never above the monitor: 720 px tall at this page)

    def test_monitor_move_sizes_for_the_destination_before_placing(self):
        ns = window_methods("go_monitor", "_place", *PLACE, *ZOOM)
        source, dest = screen(0, 2560, 1440), screen(2560, 1280, 720)
        for bar in (None, "right"):
            with self.subTest(bar=bar), tempfile.TemporaryDirectory() as tmp:
                w = startup(ns, tmp, {"mons": {"second": [748, 0]}}, source, dest)
                w.bar, w.bar_home, w.glide_n = bar, None, 0
                w.zoom_spot = (source, 0) if bar else None
                w.hypr = SimpleNamespace(ok=lambda: True)
                w._hmons = lambda: [("first", 0, False), ("second", 1, True)]
                w._save_pos, w._rewide, w._send_corner = Mock(), Mock(), Mock()
                events = []
                ns["GtkLayerShell"].set_margin.side_effect = lambda *a: events.append(("place", w.cur_w))
                w.set_wide.side_effect = lambda *a: events.append(("set_wide", w.mon_i))
                w.set_bar.side_effect = lambda *a, **k: events.append(("set_bar", w.mon_i))
                self.assertTrue(w.go_monitor("second"))
                self.assertEqual(events[0], ("place", 532))
                self.assertEqual((w.mon_i, w.mx), (1, 748))
                self.assertAlmostEqual(w.z, 1.565, places=3)
                # the room, dock and region work of a page change still happens, once, on the destination
                self.assertEqual([e for e in events if e[0] != "place"],
                                 [("set_wide", 1)] + ([("set_bar", 1)] if bar else []))
                w._apply_region.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
