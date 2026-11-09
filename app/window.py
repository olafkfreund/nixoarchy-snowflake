#!/usr/bin/env python3
"""Nixi overlay: a see-through GTK + WebKit surface that is *just* the little guy.

On Wayland desktops that support layer-shell (Hyprland, sway, KDE Plasma, river, niri, Wayfire, labwc, COSMIC…) he's
an *overlay* (like a bar or a notification), not an app window: he sits on top of every app on every workspace, never
gets tiled, has no taskbar entry and needs no window rules. Where there's no layer-shell (GNOME, or X11 window managers:
i3, Openbox, XFCE, Cinnamon, MATE…) he's a borderless always-on-top window on every workspace instead — on a Wayland
desktop without layer-shell he restarts himself under XWayland for that, since only X11 lets an app stay on top.

Runs with the system Python (needs PyGObject + WebKit2GTK 4.1).

    window.py URL [toggle|show|hide|quit|listen|look|hover|hover-on|hover-off]
    window.py URL --selftest-bar EDGE out.png   (dock as the top bar on EDGE, print where, save a picture — for CI)

The first instance owns the window; later calls just send it a command over a unix socket,
so binding `nixi-companion` (or `nixi-companion listen`) to a hotkey pops him in and out like a quick-shell.

Only the parts of the window you can see take clicks (the ball, open menus/panels); everything else clicks
through to whatever is underneath. In hover mode he floats along next to your mouse cursor
(Hyprland: through its control socket; X11/XWayland: by moving the window).
"""
import json
import math
import os
import socket
import sys
import threading
import time
from urllib.parse import urlparse

import aside
from room import split_room
import screens

# He's an overlay (a layer-shell surface, like a bar or a notification), which only works when GTK talks Wayland.
# Lots of setups (NVIDIA ones especially) set GDK_BACKEND=x11, or start apps without WAYLAND_DISPLAY — then GTK quietly
# uses XWayland and he ends up as an ordinary app window. Fix that up before GTK loads.
LAYER_WHY = []
if os.environ.get("NIXI_COMPANION_NO_LAYER") != "1":
    _rt = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    if not os.environ.get("WAYLAND_DISPLAY") and os.path.isdir(_rt):
        _socks = sorted(f for f in os.listdir(_rt) if f.startswith("wayland-") and not f.endswith(".lock"))
        if _socks:
            os.environ["WAYLAND_DISPLAY"] = _socks[0]
            LAYER_WHY.append(f"WAYLAND_DISPLAY wasn't set — found {_socks[0]}")
    _be = os.environ.get("GDK_BACKEND", "")
    if os.environ.get("WAYLAND_DISPLAY") and _be and _be.split(",")[0].strip() not in ("wayland", "*"):
        LAYER_WHY.append(f"GDK_BACKEND was '{_be}' — using wayland for Nixi so it can be an overlay")
        os.environ["GDK_BACKEND"] = "wayland"

# His face (this window + WebKit's processes, which inherit this) on the first half of the CPU cores; the server
# (voice + brain) takes the other half — drawing can never starve his voice. Off with "cpu_split": false.
def _cpu_split():
    try:
        conf = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "nixi-companion", "config.json")
        try:
            if json.load(open(conf)).get("cpu_split", True) is False:
                return
        except (OSError, ValueError):
            pass
        cores = sorted(os.sched_getaffinity(0))
        if len(cores) >= 4:
            os.sched_setaffinity(0, set(cores[:max(1, len(cores) // 2)]))
    except (AttributeError, OSError):
        pass


_cpu_split()

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import GLib  # noqa: E402

GLib.set_prgname("Nixi")                # before Gtk loads → X11 WM_CLASS + Wayland app_id "Nixi"
GLib.set_application_name("Nixi")
from gi.repository import Gdk, Gtk, WebKit2  # noqa: E402

# We restarted under XWayland (see below) but can't reach it (no XWayland, no permission…): go back to Wayland as a
# plain window rather than not showing up at all.
if os.environ.get("NIXI_COMPANION_LAYER_WHY") and os.environ.get("GDK_BACKEND") == "x11" and not Gtk.init_check(sys.argv)[0]:
    os.environ.update(GDK_BACKEND="wayland", NIXI_COMPANION_NO_XWAYLAND="1",
                      NIXI_COMPANION_LAYER_WHY=os.environ["NIXI_COMPANION_LAYER_WHY"].replace(" — running under XWayland so he can stay on top",
                                                                           "") + " — and XWayland couldn't be opened")
    os.execv(sys.executable, [sys.executable] + sys.argv)

GtkLayerShell = None
if os.environ.get("NIXI_COMPANION_LAYER_WHY"):            # we restarted ourselves under XWayland (below): keep the reason for the log
    LAYER_WHY.append(os.environ["NIXI_COMPANION_LAYER_WHY"])
elif os.environ.get("NIXI_COMPANION_NO_LAYER") == "1":
    LAYER_WHY.append("NIXI_COMPANION_NO_LAYER=1 is set")
elif not os.environ.get("WAYLAND_DISPLAY"):
    LAYER_WHY.append("not running on Wayland (no WAYLAND_DISPLAY)")
else:
    try:
        gi.require_version("GtkLayerShell", "0.1")
        from gi.repository import GtkLayerShell  # noqa: E402
        if not GtkLayerShell.is_supported():
            GtkLayerShell = None
            LAYER_WHY.append("the compositor doesn't support layer-shell (or GTK isn't on Wayland)")
    except (ValueError, ImportError, AttributeError) as _e:
        GtkLayerShell = None
        LAYER_WHY.append(f"gtk-layer-shell isn't installed ({_e}) — install gtk-layer-shell (Debian/Ubuntu: "
                         "gir1.2-gtklayershell-0.1)")
# A Wayland desktop without layer-shell (GNOME…): a plain Wayland window can't stay on top or place itself, so start
# over under XWayland, where it can (always-on-top, on every workspace, remembered position, hover mode).
if GtkLayerShell is None and os.environ.get("WAYLAND_DISPLAY") and os.environ.get("DISPLAY") \
        and os.environ.get("GDK_BACKEND", "").split(",")[0] != "x11" and os.environ.get("NIXI_COMPANION_NO_XWAYLAND") != "1":
    os.environ.update(GDK_BACKEND="x11", NIXI_COMPANION_NO_LAYER="1",
                      NIXI_COMPANION_LAYER_WHY="; ".join(LAYER_WHY) + " — running under XWayland so he can stay on top")
    os.execv(sys.executable, [sys.executable] + sys.argv)

try:                                          # python-cairo + gi's cairo bridge: input regions
    gi.require_foreign("cairo")
    import cairo
except (ImportError, Exception):  # noqa: BLE001
    cairo = None

W, H = 340, 460
WIDE = 470                   # while settings / history / memory are open the window widens to this
CODE_SIDE = 100              # room on each side for the code panel when he swings it out to his side
BAR_SIDE = 70                # docked at the top / bottom: room either side of the notch, so his glow fades out in it
GLIDE = 0.26                 # seconds the window takes to glide into the notch and back (quick: it should feel snappy)
SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", f"nixi-companion-{os.getuid()}.sock")
BALL = (170, 165)            # where the ball's centre sits inside the window (CSS px)
CONF_FILE = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "nixi-companion", "config.json")


def window_size(raw):
    try:
        z = float(raw)
        return max(0.5, min(1.0, z)) if math.isfinite(z) else 0.6
    except (TypeError, ValueError):
        return 0.6


def saved_size():
    try:
        return window_size(json.load(open(CONF_FILE)).get("size", 0.6))
    except (OSError, ValueError):
        return 0.6

POS_FILE = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "nixi-companion", "pos.json")


_logged = set()
SELFTEST = "--selftest-bar" in sys.argv[2:3]


def log(msg):
    """→ `nixi-companion log`. Each distinct message once, so a loop can't flood the log."""
    if msg not in _logged:
        _logged.add(msg)
        print(f"[nixi] {msg}", file=sys.stderr, flush=True)


def token_script(tok, port):
    """The user script that gives the page its token. WebKit's allow-list matches the host only, never the port, so
    the script itself checks the exact origin: no other page on 127.0.0.1 gets it."""
    origin = f"http://127.0.0.1:{port}"
    return f"if(location.origin==={json.dumps(origin)})window.__nixiT={json.dumps(tok)};", ["http://127.0.0.1/*"]


def send(cmd):
    try:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(1)
        s.connect(SOCK)
        s.sendall(cmd.encode())
        s.close()
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- Hyprland control socket
class Hypr:
    def __init__(self):
        sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
        self.path = None
        if sig:
            for base in (os.environ.get("XDG_RUNTIME_DIR", ""), "/tmp"):
                p = os.path.join(base, "hypr", sig, ".socket.sock")
                if os.path.exists(p):
                    self.path = p
                    break
        self.addr = None

    def ok(self):
        return bool(self.path)

    def req(self, msg):
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(0.5)
        try:
            s.connect(self.path)
            s.sendall(msg.encode())
            out = b""
            while True:
                b = s.recv(65536)
                if not b:
                    break
                out += b
            return out.decode(errors="replace")
        finally:
            s.close()

    def cursor(self):
        j = json.loads(self.req("j/cursorpos"))
        return j["x"], j["y"]

    def find(self):
        for c in json.loads(self.req("j/clients")):
            if c.get("class") == "Nixi" or c.get("initialClass") == "Nixi":
                self.addr = c["address"]
                return c
        return None

    def dispatch(self, what):
        r = self.req(f"dispatch {what}").strip()
        if r != "ok":
            log(f"hyprland: '{what}' -> {r!r}")
        return r == "ok"

    def setup(self, width=W, height=H):
        """Don't trust window rules (their syntax keeps changing): make him floating, pinned and exactly W×H directly."""
        c = self.find()
        if not c:
            log("hyprland: couldn't find the Nixi window in `hyprctl clients`")
            return False
        a = f"address:{self.addr}"
        if not c.get("floating"):
            self.dispatch(f"setfloating {a}") or self.dispatch(f"togglefloating {a}")
        if not c.get("pinned"):
            self.dispatch(f"pin {a}")
        if list(c.get("size") or []) != [width, height]:
            self.dispatch(f"resizewindowpixel exact {width} {height},{a}")
        c = self.find() or {}
        log(f"hyprland: window {self.addr} floating={c.get('floating')} pinned={c.get('pinned')} "
            f"size={c.get('size')} at={c.get('at')}")
        return True

    def monitors(self):
        out = []
        for m in json.loads(self.req("j/monitors")):
            sc = float(m.get("scale") or 1)
            w, h = m["width"] / sc, m["height"] / sc
            if m.get("transform", 0) % 2:
                w, h = h, w
            out.append((m["x"], m["y"], w, h))
        return out

    def move(self, x, y):
        if not self.addr:
            self.find()
        if self.addr:
            r = self.req(f"dispatch movewindowpixel exact {int(x)} {int(y)},address:{self.addr}").strip()
            if r != "ok":
                log(f"hyprland: move failed ({r!r}) — looking for the window again")
                self.addr = None


class Ghost:
    """The notch left on the wall when he's pulled out of it: it melts back into the screen edge on its own (black,
    shrinking into the edge) while he goes wherever you take him. Click-through, never takes focus, gone in 0.3 s.
    x, y: margins on monitor `mon` (layer-shell) or screen coordinates (X11)."""
    def __init__(self, x, y, w, h, edge, mon=None, z=1.0):
        self.edge, self.k, self.t0, self.z = edge, 1.0, time.monotonic(), z
        g = self.win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL if mon is not None else Gtk.WindowType.POPUP)
        g.set_decorated(False)
        g.set_app_paintable(True)
        g.set_accept_focus(False)
        g.set_default_size(w, h)
        g.set_size_request(w, h)
        visual = g.get_screen().get_rgba_visual()
        if visual is not None:
            g.set_visual(visual)
        if mon is not None:
            L = GtkLayerShell
            L.init_for_window(g)
            L.set_layer(g, L.Layer.OVERLAY)
            L.set_namespace(g, "nixi-ghost")
            L.set_monitor(g, mon)
            L.set_anchor(g, L.Edge.TOP, True)
            L.set_anchor(g, L.Edge.LEFT, True)
            L.set_margin(g, L.Edge.LEFT, int(x))
            L.set_margin(g, L.Edge.TOP, int(y))
            L.set_exclusive_zone(g, -1)
        else:
            g.set_keep_above(True)
            g.move(int(x), int(y))
        g.connect("draw", self._draw)
        g.show_all()
        g.get_window().input_shape_combine_region(cairo.Region(), 0, 0)   # clicks go straight through it
        GLib.timeout_add(10, self._step)

    def _step(self):
        p = min(1.0, (time.monotonic() - self.t0) / 0.3)
        self.k = 1 - p * p                                 # eases in: it lets go, then is drawn away
        if p >= 1:
            self.win.destroy()
            return False
        self.win.queue_draw()
        return True

    def _draw(self, win, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        w, h, k, o = win.get_allocated_width(), win.get_allocated_height(), self.k, round(24 * self.z)   # o: runs off the edge
        if self.edge in ("top", "bottom"):
            rw, rh = w * (0.55 + 0.45 * k), h * k
            x, y, bw, bh, r = (w - rw) / 2, (-o if self.edge == "top" else h - rh), rw, rh + o, min(18 * self.z, rh)
        else:
            rw, rh = w * k, h * (0.55 + 0.45 * k)
            x, y, bw, bh, r = (-o if self.edge == "left" else w - rw), (h - rh) / 2, rw + o, rh, min(18 * self.z, rw)
        if bw > 0 and bh > 0:
            r = max(0.0, min(r, bw / 2, bh / 2))
            cr.new_sub_path()
            cr.arc(x + bw - r, y + r, r, -math.pi / 2, 0)
            cr.arc(x + bw - r, y + bh - r, r, 0, math.pi / 2)
            cr.arc(x + r, y + bh - r, r, math.pi / 2, math.pi)
            cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
            cr.close_path()
            cr.set_source_rgb(0, 0, 0)
            cr.fill()
        return True


class NixiWindow:
    def __init__(self, url):
        self.z = saved_size()
        w = self.win = Gtk.Window(title="Nixi")
        w.set_decorated(False)
        w.set_resizable(False)
        w.set_default_size(self._px(W), self._px(H))
        w.set_size_request(self._px(W), self._px(H))
        w.set_keep_above(True)
        w.set_type_hint(Gdk.WindowTypeHint.UTILITY)       # i3/sway(X) float utility windows by default
        w.set_app_paintable(True)
        visual = w.get_screen().get_rgba_visual()
        if visual is not None and w.get_screen().is_composited():
            w.set_visual(visual)
        else:
            print("[nixi] no compositor/RGBA visual — window won't be see-through", file=sys.stderr)
        # (no draw handler that clears the window: with GPU rendering WebKit only repaints what changed,
        #  so clearing here made everything outside the animating ball vanish until the mouse moved)
        self.cur_w, self.wide_shift = self._px(W), 0
        self.cur_h, self.top_shift, self.want_xw, self.want_h = self._px(H), 0, 0, 0   # the page asks for room for a long approval card / terminal sheet
        self.want_css = (0, 0)
        self.want_panel = self.want_code = self.want_bar = False
        self.glide_n = 0                        # the current window glide (a newer one cancels it)
        self.glide_end = 0.0
        self.follow_focus = False               # move to the monitor you focus (the page tells us; Hyprland only)
        self.follow_t = None
        self.drag_t_end = None
        self.step_aside = True                  # slide out of the way of nixi's card (the page tells us)
        self.aside = None                       # while aside: {"home": (mon, x, y), "mode": side|monitor|hover, "parked": (mon, x, y)|None}
        self.dpos = None                        # drag_by: his unclamped global position while dragged
        self.grab_ball = False                  # the drag started by pulling the notch: the ball is the grab point
        self.dragging = False                   # (set before _place() can run — it checks this)
        self.hover = False
        self.bar, self.bar_home = None, None    # top bar: merged into a screen edge as a notch (None = the blob)
        self.pmoving = False                    # moving a panel by its header: no docking, no undocking
        self.hypr = Hypr()                      # (before _load_pos: a saved connector name needs it)
        self.layer = GtkLayerShell is not None
        self.mon_i, self.mx, self.my = 0, 0, 0
        if self.layer:
            L = GtkLayerShell
            L.init_for_window(w)
            L.set_layer(w, L.Layer.OVERLAY)
            L.set_namespace(w, "nixi-companion")
            L.set_anchor(w, L.Edge.TOP, True)
            L.set_anchor(w, L.Edge.LEFT, True)
            L.set_exclusive_zone(w, -1)                    # don't push other things around, and may sit over bars
            try:
                L.set_keyboard_mode(w, L.KeyboardMode.ON_DEMAND)   # takes the keyboard when you click him
            except AttributeError:
                L.set_keyboard_interactivity(w, True)
            self._load_pos()
            for why in LAYER_WHY:
                log(f"overlay: {why}")
            log(f"overlay: layer-shell on monitor {self.mon_i} at {self.mx},{self.my}")
        else:
            log("overlay: no layer-shell — always-on-top window instead, because: " + ("; ".join(LAYER_WHY) or "unknown"))
            w.set_skip_taskbar_hint(True)
            w.set_skip_pager_hint(True)
            w.stick()                                       # on every workspace
            self.save_t = None
            w.connect("configure-event", self._moved)

        ucm = self.ucm = WebKit2.UserContentManager()
        ucm.register_script_message_handler("nixiui")
        ucm.connect("script-message-received::nixiui", self._on_msg)
        v = self.view = WebKit2.WebView.new_with_user_content_manager(ucm)
        v.set_background_color(Gdk.RGBA(0, 0, 0, 0))
        v.set_zoom_level(self.z)
        st = v.get_settings()
        st.set_enable_webaudio(True)
        st.set_media_playback_requires_user_gesture(False)
        st.set_enable_developer_extras(os.environ.get("NIXI_COMPANION_DEVTOOLS") == "1")
        st.set_enable_back_forward_navigation_gestures(False)
        try:
            st.set_enable_write_console_messages_to_stdout(True)   # page errors land in `nixi-companion log`
        except AttributeError:
            pass
        if os.environ.get("NIXI_COMPANION_DEVTOOLS") != "1":
            v.connect("context-menu", lambda *a: True)   # right-click is his own menu
        v.connect("permission-request", lambda _v, req: (req.deny(), True)[1])   # the server records the mic, not the page
        # if the page's renderer crashes (GPU drivers…), bring him straight back instead of leaving an empty window
        try:
            v.connect("web-process-terminated", lambda _v, why: (log(f"page renderer stopped ({why}) — reloading"),
                                                                 GLib.timeout_add(400, lambda: (_v.reload(), False)[1]))[1] and False)
        except TypeError:
            pass
        self.url = url
        self._start_page()
        w.add(v)
        w.connect("delete-event", lambda *a: (self.hide(), True)[1])
        if not self.layer:
            self._load_xpos()
        w.show_all()
        v.grab_focus()
        # Redraw the whole window on every frame. WebKit only reports the bits that changed, and on some GPU/compositor
        # combos (NVIDIA + layer-shell especially) the untouched parts of the see-through window come back from an older
        # buffer: menus and panels around him flicker or vanish until something moves. A full redraw is cheap at this size.
        if os.environ.get("NIXI_COMPANION_PARTIAL_REDRAW") != "1":
            v.add_tick_callback(lambda wid, _clock: (wid.queue_draw(), True)[1])

        self.shown = True
        self.mons = None
        if self.hypr.ok() and not self.layer:
            GLib.timeout_add(400, self._hypr_setup)
        GLib.timeout_add(1500, self._tell_page)
        self.hpos = None          # where the window is (hover mode), smoothed
        self.last_sent = None
        self.rects = None
        self.region_on = False
        if not SELFTEST:                     # (a test window must not take over the real one's socket: `nixi-companion stop`)
            threading.Thread(target=self._serve, daemon=True).start()
            if self.hypr.ok():
                threading.Thread(target=self._watch_focus, daemon=True).start()

    def _px(self, value):
        return round(value * getattr(self, "z", 1.0))

    def _css(self, value):
        return value / getattr(self, "z", 1.0)

    def _region_rect(self, rect):
        x, y, w, h = rect
        z = getattr(self, "z", 1.0)
        left, top = math.floor(x * z), math.floor(y * z)
        return left, top, math.ceil((x + w) * z) - left, math.ceil((y + h) * z) - top

    def set_zoom(self, value):
        z = window_size(value)
        if z == self.z:
            return
        self.z = z
        self.view.set_zoom_level(z)
        self.set_wide(getattr(self, "want_css", (self.want_xw / z, self.want_h / z)), "size")
        if self.bar:
            self.set_bar(self.bar, glide=False)
        self._apply_region()

    # ---- where he is (layer mode: margins from the top-left of a monitor)
    @staticmethod
    def _monitors():
        d = Gdk.Display.get_default()
        return [d.get_monitor(i) for i in range(d.get_n_monitors())]

    @classmethod
    def _geoms(cls):
        return [(g.x, g.y, g.width, g.height) for g in (m.get_geometry() for m in cls._monitors())]

    def _geom(self, i=None):
        ms = self._monitors()
        m = ms[min(self.mon_i if i is None else i, len(ms) - 1)]
        return m, m.get_geometry()

    def _load_pos(self):
        try:
            p = json.load(open(POS_FILE))
            ok = self.hypr.ok()                              # a saved connector name only means something to Hyprland
            pairs = [(n, i) for n, i, _ in self._hmons()] if ok else []
            # (an empty list is "Hyprland didn't answer", not "that screen is gone": fall back to the saved index)
            i = screens.pick_monitor(p if pairs else dict(p, name=None), pairs, len(self._monitors()))
            if i is None:
                raise ValueError
            self.mon_i, self.mx, self.my = i, int(p["x"]), int(p["y"])
        except Exception:  # noqa: BLE001
            self.mon_i = 0
            _, g = self._geom()
            self.mx, self.my = g.width - self._px(W) - 10, g.height - self._px(H) - 10       # default: bottom-right corner
        GtkLayerShell.set_monitor(self.win, self._geom()[0])
        self._place(self.mx, self.my, clamp=True)

    # ---- where he is (window mode: global screen position, saved after you drag him)
    def _load_xpos(self):
        try:
            p = json.load(open(POS_FILE))
            x, y = int(p["gx"]), int(p["gy"])
            if not any(g.x <= x + self._px(W) // 2 < g.x + g.width and g.y <= y + self._px(H) // 2 < g.y + g.height
                       for g in (m.get_geometry() for m in self._monitors())):
                raise ValueError                              # that monitor is gone
        except Exception:  # noqa: BLE001
            g = self._geom(0)[1]
            x, y = g.x + g.width - self._px(W) - 10, g.y + g.height - self._px(H) - 10     # default: bottom-right corner
        self.mx, self.my = x, y
        self.win.move(x, y)

    def _moved(self, win, _ev):
        x, y = win.get_position()
        if (x, y) == (self.mx, self.my) or self.hover:
            return False
        self.mx, self.my = x, y
        if self.bar:                                      # docked: his blob spot (bar_home) stays where it was
            return False
        if self.save_t:
            GLib.source_remove(self.save_t)
        self.save_t = GLib.timeout_add(700, self._save_xpos)
        return False

    def _save_xpos(self):
        self.save_t = None
        try:
            try:
                p = json.load(open(POS_FILE))
            except (OSError, ValueError):
                p = {}
            p.update(gx=self.mx + self.wide_shift, gy=self.my + self.top_shift)
            os.makedirs(os.path.dirname(POS_FILE), exist_ok=True)
            json.dump(p, open(POS_FILE, "w"))
        except OSError:
            pass
        self._send_corner()
        return False

    def _save_pos(self):
        try:
            os.makedirs(os.path.dirname(POS_FILE), exist_ok=True)
            try:
                p = json.load(open(POS_FILE))
            except (OSError, ValueError):
                p = {}
            name = next((n for n, i, _ in self._hmons() if i == self.mon_i), None) if self.hypr.ok() else None
            screens.pos_dict(p, self.mon_i, self.mx + self.wide_shift, self.my + self.top_shift, name, self.bar)
            json.dump(p, open(POS_FILE, "w"))
        except OSError:
            pass
        self._send_corner()

    def _send_corner(self):
        """Tell the page which corner of his screen he sits in (tl/tr/bl/br), from the middle of his own 340px strip."""
        cx, cy = self.mx + self.wide_shift + self._px(W) / 2, self.my + self.top_shift + self._px(H) / 2
        if self.layer:                                   # layer mode: mx/my are margins from this monitor's top-left
            g = self._geom()[1]
        else:                                            # X11: mx/my are global screen coordinates
            g = self._mon_at(cx, cy)[1]
            cx, cy = cx - g.x, cy - g.y
        c = ("t" if cy < g.height / 2 else "b") + ("l" if cx < g.width / 2 else "r")
        self._js(f"window.nixiCorner&&nixiCorner('{c}')")

    def _place(self, x, y, clamp=False, mon=None):
        if mon is not None and mon != self.mon_i:
            self.mon_i = mon
            GtkLayerShell.set_monitor(self.win, self._geom()[0])
        _, g = self._geom()
        if clamp:                                  # keep the whole surface on screen
            x, y = screens.clamp_on((0, 0, g.width, g.height), x, y, self.cur_w, self.cur_h)
        nx, ny = int(round(x)), int(round(y))
        self.mx, self.my = nx, ny
        GtkLayerShell.set_margin(self.win, GtkLayerShell.Edge.LEFT, self.mx)
        GtkLayerShell.set_margin(self.win, GtkLayerShell.Edge.TOP, self.my)
        return False

    def keyboard(self, grab):
        """While his password card is up, take the keyboard so you can just type (layer-shell windows normally only get
        it when clicked)."""
        if not self.layer:
            self.win.present()
            return
        L = GtkLayerShell
        try:
            L.set_keyboard_mode(self.win, L.KeyboardMode.EXCLUSIVE if grab else L.KeyboardMode.ON_DEMAND)
        except AttributeError:
            L.set_keyboard_interactivity(self.win, bool(grab))
        if grab:
            self.view.grab_focus()

    def set_wide(self, on, kind="panel"):
        """Make room: panels (settings / history) widen him to the left; the code panel wants room on both sides.
        The page is told how far he moved inside the window so he stays exactly where he was on screen."""
        if kind == "size":                         # on = (extra width, extra height) the page wants for its card / sheet
            self.want_css = on
            self.want_xw, self.want_h = (self._px(v) for v in on)
        elif kind == "panel":
            self.want_panel = on
        elif kind == "bar":
            self.want_bar = on
        else:
            self.want_code = on
        L = max(self._px(WIDE - W) if self.want_panel else 0, self._px(CODE_SIDE) if self.want_code else 0, self._px(BAR_SIDE) if self.want_bar else 0)
        R = max(self._px(CODE_SIDE) if self.want_code else 0, self._px(BAR_SIDE) if self.want_bar else 0)
        xw, eh = (0, 0) if (self.hover or self.want_bar) else (self.want_xw, self.want_h)
        if self.hover:
            L = R = 0
        base, basey = self.mx + self.wide_shift, self.my + self.top_shift
        if self.layer:
            g = self._geom()[1]
            mon = (0, 0, g.width, g.height)
        else:
            g = Gdk.Display.get_default().get_monitor_at_point(base, basey).get_geometry()
            mon = (g.x, g.y, g.width, g.height)
        L, R, T, extra_h = split_room(base, basey, self._px(W), self._px(H), xw, eh, (L, R), mon)
        if self.hover:
            L = R = 0
        if self._px(W) + L + R == self.cur_w and L == self.wide_shift and self._px(H) + extra_h == self.cur_h and T == self.top_shift:
            return
        old, old_top = self.wide_shift, self.top_shift
        self.wide_shift, self.cur_w, self.top_shift, self.cur_h = L, self._px(W) + L + R, T, self._px(H) + extra_h
        self.win.set_size_request(self.cur_w, self.cur_h)
        self.win.resize(self.cur_w, self.cur_h)
        if self.layer:
            self._place(base - L, basey - T)
        elif (L, T) != (old, old_top):
            self._xmove(base - L, basey - T)
        if not self.layer and self.hypr.ok() and self.hypr.addr:
            try:
                self.hypr.dispatch(f"resizewindowpixel exact {self.cur_w} {self.cur_h},address:{self.hypr.addr}")
            except Exception:  # noqa: BLE001
                pass
        self._js(f"window.nixiLayout&&nixiLayout({self._css(self.wide_shift)},{self._css(self.top_shift)})")
        self.win.queue_draw()

    def _mon_at(self, gx, gy):
        for i, m in enumerate(self._monitors()):
            g = m.get_geometry()
            if g.x <= gx < g.x + g.width and g.y <= gy < g.y + g.height:
                return i, g
        return self.mon_i, self._geom()[1]

    # ---- between screens: `monitor:next|prev|focused|<name>` (socket, key binds, voice) and "follow my focused screen"
    def _hmons(self):
        """Hyprland's monitors joined to GDK's by their position: [(name, gdk index, focused)], left to right."""
        try:
            hm = json.loads(self.hypr.req("j/monitors"))
        except Exception:  # noqa: BLE001
            return []
        gm = [m.get_geometry() for m in self._monitors()]
        out = [(m["name"], i, bool(m.get("focused"))) for m in hm for i, g in enumerate(gm) if (g.x, g.y) == (m["x"], m["y"])]
        return sorted(out, key=lambda t: (gm[t[1]].x, gm[t[1]].y))

    def go_monitor(self, arg):
        """Move him to another screen, to the spot he had there last (bottom-right the first time). Docked, he re-docks on
        the same edge. False if there is nowhere to go."""
        ms = self._hmons() if self.hypr.ok() else []
        cur = self.mon_i if self.layer else self._mon_at(self.mx + self.wide_shift + self._px(W) // 2,
                                                        self.my + self.top_shift + self._px(H) // 2)[0]
        k = next((j for j, m in enumerate(ms) if m[1] == cur), 0)
        arg = (arg or "").strip()
        if arg in ("next", "prev") and len(ms) > 1:
            tgt = ms[(k + (1 if arg == "next" else -1)) % len(ms)]
        elif arg == "focused":
            tgt = next((m for m in ms if m[2]), None)
        else:
            tgt = next((m for m in ms if m[0].lower() == arg.lower()), None)
        if not tgt or tgt[1] == cur:
            return False
        if self.bar and not self.layer:
            log("monitor: a docked notch only moves between screens with layer-shell")
            return False
        self._save_pos() if self.layer else self._save_xpos()                   # remember where he was here
        g = self._monitors()[tgt[1]].get_geometry()
        try:
            mem = json.load(open(POS_FILE)).get("mons", {}).get(tgt[0])
            x, y = int(mem[0]), int(mem[1])
        except Exception:  # noqa: BLE001
            x, y = g.width - self._px(W) - 10, g.height - self._px(H) - 10
        self.glide_n += 1                                                      # (cancel any glide in progress)
        if self.bar:
            gw, gh = g.width, g.height
            if self.bar_home:
                self.bar_home = (tgt[1], x, y)
            bx = {"top": (gw - self._px(W)) // 2, "bottom": (gw - self._px(W)) // 2, "left": 0, "right": gw - self._px(W)}[self.bar]
            by = {"top": 0, "bottom": gh - self._px(H), "left": (gh - self._px(H)) // 2, "right": (gh - self._px(H)) // 2}[self.bar]
            self._place(bx - self.wide_shift, by - self.top_shift, True, tgt[1])
        elif self.layer:
            self._place(x - self.wide_shift, y - self.top_shift, True, tgt[1])
        else:
            self._xmove(g.x + x - self.wide_shift, g.y + y - self.top_shift)
        self._rewide()
        self._send_corner()
        GLib.timeout_add(100, lambda: (self._save_pos() if self.layer else self._save_xpos(), False)[1])
        return True

    def _watch_focus(self):
        """Hyprland's event socket: `focusedmon>>NAME,WS` → follow it (if asked to), debounced, never mid-drag or glide."""
        sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
        p = next((q for b in (os.environ.get("XDG_RUNTIME_DIR", ""), "/tmp") for q in [os.path.join(b, "hypr", sig or "-", ".socket2.sock")]
                  if os.path.exists(q)), None)
        if not p:
            return
        while True:
            try:
                s = socket.socket(socket.AF_UNIX)
                s.connect(p)
                buf = b""
                while True:
                    d = s.recv(4096)
                    if not d:
                        break
                    buf += d
                    *lines, buf = buf.split(b"\n")
                    for ln in lines:
                        ev = aside.layer_event(ln)
                        if ev:
                            GLib.idle_add(self.aside_on if ev == "open" else self.aside_off, *([True] if ev == "open" else []))
                        if ln.startswith(b"focusedmon>>") and self.follow_focus:
                            GLib.idle_add(self._follow_focus, ln[12:].decode(errors="replace").split(",")[0])
            except OSError:
                pass
            time.sleep(2)

    def aside_on(self, hypr=False):
        """The card opened: slide to the nearer side of this screen, beside it (or to another screen, or hover mode if there
        is no room), then re-map so he stacks above the card. `hypr`: the event came from Hyprland, so check the card's screen."""
        if self.aside and aside.may_return(self._spot(), self.aside["parked"]):
            return False                                           # already aside
        self.aside = None                                          # (he was moved since: start afresh)
        if not (self.step_aside and self.layer and self.win.get_visible()) or self.dragging or self.pmoving or self.dpos is not None or self.bar or self.hover:
            return False
        ms = self._hmons() if self.hypr.ok() else []
        if hypr:
            try:
                cm = aside.card_monitor(json.loads(self.hypr.req("j/layers")))
            except Exception:  # noqa: BLE001
                return False
            if cm != next((n for n, i, _ in ms if i == self.mon_i), cm):
                return False                                       # the card is on another screen
        g = self._geom()[1]
        home = self._spot()
        mode = aside.plan(g.width, len(ms) > 1)
        self.aside = {"home": home, "mode": mode, "parked": None}
        if mode == "side":
            tx, ty = aside.target(g.width, g.height, home[1], self._px(W), self._px(H))
            self._save_pos()
            self._glide_to(tx - self.wide_shift, ty - self.top_shift, self._parked)
            self.aside["glide"] = self.glide_n                     # (closed before it lands: still ours to undo)
        elif mode == "monitor" and self.go_monitor("next"):
            self.aside["parked"] = self._spot()
        elif self.hypr.ok():
            self.aside["mode"] = "hover"
            self.set_hover(True)
            self._remap()                                          # above the card, or its veil hides the pointer he shows
        else:
            self.aside = None
        return False

    def _spot(self):
        return (self.mon_i, self.mx + self.wide_shift, self.my + self.top_shift)

    def _parked(self):
        if self.aside:
            self.aside["parked"] = self._spot()
            self._remap()
        self._send_corner()

    def _remap(self):
        """Re-map at the GTK level only (no page callbacks: nixiHidden would put him to sleep) → stacks above the card."""
        self.win.hide()
        GLib.timeout_add(30, lambda: (self.win.show_all(), self._apply_region(), False)[2])

    def aside_off(self):
        a, self.aside = self.aside, None
        if not a:
            return False
        if a["mode"] == "hover":
            self.set_hover(False)
        elif aside.may_return(self._spot(), a["parked"]) or (a["parked"] is None and a.get("glide") == self.glide_n):
            h = a["home"]
            if a["mode"] == "monitor":
                name = next((n for n, i, _ in self._hmons() if i == h[0]), None)
                if name:
                    self.go_monitor(name)
            else:
                self._glide_to(h[1] - self.wide_shift, h[2] - self.top_shift, self._send_corner)
                GLib.timeout_add(int(GLIDE * 1000) + 300, lambda: (self.aside or self._save_pos(), False)[1])   # (not if aside again)
        return False

    def _follow_focus(self, name):
        if screens.focus_blocked(self.dragging, self.pmoving, self.dpos, time.monotonic(), self.drag_t_end):
            return False
        if self.follow_t:
            GLib.source_remove(self.follow_t)

        def go():
            self.follow_t = None
            if self.follow_focus and not self.dragging and not self.pmoving and not screens.focus_blocked(
                    self.dragging, self.pmoving, self.dpos, time.monotonic(), self.drag_t_end) and time.monotonic() >= self.glide_end:
                self.go_monitor(name)
            return False
        self.follow_t = GLib.timeout_add(300, go)
        return False

    def _tell_page(self):
        # X11 / XWayland: always-on-top window is the normal mode there, nothing to complain about. Only a plain Wayland
        # window (no layer-shell and no XWayland) can end up behind other apps — then say why on screen.
        why = "" if self.layer or self._x11() else ("; ".join(LAYER_WHY) or "layer-shell isn't available")
        self._js(f"window.nixiMode&&nixiMode({json.dumps({'layer': self.layer, 'cursor': self.hypr.ok() or self._x11(), 'why': why})})")
        return False

    def _hypr_setup(self):
        try:
            self.hypr.setup(self.cur_w, self.cur_h)
        except Exception as e:  # noqa: BLE001
            log(f"hyprland setup failed: {e}")
        return False

    # ---- window plumbing
    def _js(self, code):
        try:
            self.view.evaluate_javascript(code, -1, None, None, None, None, None)
        except (AttributeError, TypeError):
            self.view.run_javascript(code, None, None, None)

    def _doze_show(self):
        """Wake from a doze: reappear where he was, without stealing focus or announcing himself."""
        if self.hover:
            return
        self.win.show_all()
        self._apply_region()

    def show(self):
        if self.hover:
            self.cursor_hidden(True)
        self.shown = True
        self.win.show_all()
        if self.hypr.ok() and not self.layer:
            GLib.timeout_add(250, self._hypr_setup)
        self.win.present()
        self.view.grab_focus()
        self._apply_region()
        self._js("window.nixiShown&&nixiShown()")

    def quit(self):
        if self.hover:
            self.cursor_hidden(False)
        Gtk.main_quit()

    def hide(self):
        if self.hover:
            self.cursor_hidden(False)
        self.shown = False
        self._js("window.nixiHidden&&nixiHidden()")
        self.win.hide()

    def toggle(self):
        if self.hover:                       # he's being the cursor: calling him brings him home instead of hiding him
            self._js("window.nixiCmd&&nixiCmd('home')")
            return
        if self.win.get_visible() and (self.layer or self.win.is_active() or self.hover):
            self.hide()
        else:
            self.show()

    def cmd(self, name):
        """Something for the page to do (listen, look…) — make sure he's visible first."""
        if not self.win.get_visible():
            self.show()
        self._js(f"window.nixiCmd&&nixiCmd({json.dumps(name)})")

    def drag(self, panel=False):
        """Move him with the mouse. Pulling the notch away pops the blob out under the mouse; dropping the blob at a
        screen edge docks him there. panel=True: a panel's header is being dragged, so neither happens."""
        if self.hover:
            return
        self.glide_n += 1                               # grabbed: any glide stops right here
        self.pmoving = panel
        if self.bar and not panel:
            c = self._cursor_or_none()
            # the notch stays on the wall and melts away (not on Hyprland without layer-shell: a new window gets tiled)
            if c and cairo is not None and (self.layer or not self.hypr.ok()):
                bx, e = self.mx + self.wide_shift, self.bar
                nx, ny, nw, nh = {"top": (bx + self._px(30), self.my, self._px(280), self._px(52)),
                                  "bottom": (bx + self._px(30), self.my + self._px(H - 52), self._px(280), self._px(52)),
                                  "left": (bx, self.my + self._px(115), self._px(68), self._px(230)),
                                  "right": (bx + self._px(W - 68), self.my + self._px(115), self._px(68), self._px(230))}[e]
                mon = self._geom()[0] if self.layer else None

                def ghost():
                    try:
                        self.ghost = Ghost(nx, ny, nw, nh, e, mon, self.z)
                    except Exception as ex:  # noqa: BLE001
                        log(f"ghost notch: {ex}")
                    return False
                GLib.timeout_add(30, ghost)          # (a moment later: a new window right as the drag starts can upset it)
            self.grab_ball = bool(c)                 # (the loop then keeps the ball under the cursor)
            self.set_bar(None, to=(c[0] - self._px(BALL[0]), c[1] - self._px(BALL[1])) if c else "here")
        if not self.layer:
            seat = Gdk.Display.get_default().get_default_seat()
            _, x, y = seat.get_pointer().get_position()
            self.win.begin_move_drag(1, x, y, Gtk.get_current_event_time())
            if not panel:
                self._watch_release()
            return
        if self.hypr.ok() and not self.dragging:       # layer surface: follow the real cursor until the button is let go
            self.dragging = True
            threading.Thread(target=self._drag_loop, daemon=True).start()
        elif not self.hypr.ok():                       # (no global cursor: the page sends dragby; judged at dragend)
            self.over = [0, 0]
            g = self._geom()[1]
            self.dpos = [g.x + self.mx, g.y + self.my]

    def _watch_release(self):
        """X11: the window manager moves the window while you drag; poll for the mouse button coming up, then see
        whether he was dropped at a screen edge."""
        t0 = time.monotonic()

        def check():
            gw = self.win.get_window()
            try:
                dev = Gdk.Display.get_default().get_default_seat().get_pointer()
                held = bool(gw.get_device_position(dev)[3] & Gdk.ModifierType.BUTTON1_MASK)
            except Exception:  # noqa: BLE001
                held = False
            if held and time.monotonic() - t0 < 30:
                return True
            self._dock_if_edge()
            return False
        GLib.timeout_add(50, check)

    def _cursor_or_none(self):
        """The global mouse position where the desktop tells apps (Hyprland, X11/XWayland), else None."""
        if not (self.hypr.ok() or self._x11()):
            return None
        try:
            return self._cursor()
        except Exception:  # noqa: BLE001
            return None

    def _dock_if_edge(self, edge=None):
        """After you drop the blob: pushed into a screen edge? He merges into it as the bar. Judged by the mouse (a
        window can't always go past the screen's edge, so his ball can never reach it)."""
        if self.bar or self.hover:
            return False
        if edge is None:
            c = self._cursor_or_none()
            if not c:
                return False
            i, g = self._mon_at(*c)
            edge = screens.dock_edge(self._geoms(), i, c)
            if not edge:
                return False
            if self.layer and i != self.mon_i:             # dropped on the next screen: dock there, same spot on screen
                o = self._geom()[1]
                self._place(self.mx + o.x - g.x, self.my + o.y - g.y, False, i)
        self.set_bar(edge)
        return False

    # ---- the bar: merged into a screen edge as a notch (the page draws it on the matching side of the window)
    def _xmove(self, x, y):
        self.mx, self.my = int(x), int(y)               # (known now, not only when the WM confirms it)
        if self.hypr.ok():
            self.hypr.move(x, y)
        else:
            self.win.move(int(x), int(y))

    def _glide_to(self, x, y, done=None):
        """Move him to (x, y) over GLIDE seconds, easing out: layer-shell margins on his monitor, or a window's screen
        position. A newer glide (or move) cancels this one."""
        self.glide_n += 1
        n, sx, sy, t0 = self.glide_n, self.mx, self.my, time.monotonic()
        self.glide_end = t0 + GLIDE + 0.2                 # (follow-focus waits for a glide to finish)

        def step():
            if n != self.glide_n:
                return False
            k = min(1.0, (time.monotonic() - t0) / GLIDE)
            e = 1 - (1 - k) ** 3
            nx, ny = sx + (x - sx) * e, sy + (y - sy) * e
            if self.layer:
                self._place(nx, ny)
            else:
                self._xmove(nx, ny)
            if k >= 1:
                if done:
                    done()
                return False
            return True
        GLib.timeout_add(10, step)

    def set_bar(self, edge, to=None, glide=True):
        """Dock on `edge` (top / bottom / left / right) of the monitor he's on, or undock (None): back to the blob's
        own spot, to `to` (global x, y: he's pulled out by the mouse) or "here" (stay put). Tells the page.
        The window glides while the page morphs; docked at the top or bottom it grows round the notch for its glow."""
        edge = edge if edge in ("top", "bottom", "left", "right") else None
        if edge and not (self.layer or self._x11() or self.hypr.ok()):
            log("top bar: needs layer-shell or X11/XWayland — this desktop doesn't let apps place their window")
            self._js("window.nixiBarUnsupported&&nixiBarUnsupported()")
            return
        if edge:
            if not self.bar:
                self.bar_home = (self.mon_i, self.mx + self.wide_shift, self.my + self.top_shift)
            self.bar = edge
            if self.layer:                                        # margins from the monitor's top-left
                _, g = self._geom()
                ox, oy, gw_, gh_ = 0, 0, g.width, g.height        # (over any panels: exclusive zone -1)
            else:                                                 # a window: the monitor's work area (above taskbars)
                gx, gy = self.win.get_position()
                i, _ = self._mon_at(gx + self._px(W) // 2, gy + self._px(H) // 2)
                wa = self._monitors()[i].get_workarea()
                ox, oy, gw_, gh_ = wa.x, wa.y, wa.width, wa.height
            x = {"top": (gw_ - self._px(W)) // 2, "bottom": (gw_ - self._px(W)) // 2, "left": 0, "right": gw_ - self._px(W)}[edge]
            y = {"top": 0, "bottom": gh_ - self._px(H), "left": (gh_ - self._px(H)) // 2, "right": (gh_ - self._px(H)) // 2}[edge]
            room = None                                           # (no growing round the notch: it flickered)
            tx, ty = ox + x - self.wide_shift, oy + y - self.top_shift
            if not glide:
                self.glide_n += 1
                if self.layer:
                    self._place(tx, ty)
                else:
                    self._xmove(tx, ty)
            else:
                self._glide_to(tx, ty, room)
        else:
            was, self.bar = self.bar, None
            self.set_wide(False, "bar")
            if to == "here":
                pass
            elif to:
                self.glide_n += 1
                if self.layer:
                    i, g = self._mon_at(to[0] + self._px(BALL[0]), to[1] + self._px(BALL[1]))      # the cursor's screen, not the corner's
                    self._place(to[0] - g.x, to[1] - g.y, True, i)
                else:
                    self._xmove(*to)
            elif was and self.bar_home:
                m, hx, hy = self.bar_home
                if self.layer and m != self.mon_i or not glide:      # (another monitor, or right now: no glide)
                    self.glide_n += 1
                    if self.layer:
                        self._place(hx - self.wide_shift, hy - self.top_shift, True, m)
                    else:
                        self._xmove(hx - self.wide_shift, hy - self.top_shift)
                else:
                    self._glide_to(hx - self.wide_shift, hy - self.top_shift)
            if was:
                GLib.timeout_add(int(GLIDE * 1000) + 150, lambda: (None if self.dragging or self.pmoving or self.dpos else (self._save_pos() if self.layer else self._save_xpos()), False)[1])
        # (pulled out by the mouse: the page just pops him out under it, nothing trailing behind)
        pulled = bool(to) and to != "here" and not edge
        self._js("window.nixiDock&&nixiDock(%s,%s)" % (json.dumps(edge or ""), json.dumps("pull" if pulled else "")))

    def _drag_loop(self):
        try:
            sx, sy = self.hypr.cursor()
        except Exception as e:  # noqa: BLE001
            log(f"drag: can't read the cursor ({e})")
            self.dragging = False
            return
        g = self._geom()[1]
        if self.grab_ball:                               # pulled off the notch: the ball is under the cursor
            off = (self._px(BALL[0]) + self.wide_shift, self._px(BALL[1]) + self.top_shift)
        else:
            off = (sx - (g.x + self.mx), sy - (g.y + self.my))
        self.grab_ball = False
        t0 = time.monotonic()
        while self.dragging and time.monotonic() - t0 < 30:
            time.sleep(0.008)
            try:
                cx, cy = self.hypr.cursor()
            except Exception:  # noqa: BLE001
                continue
            GLib.idle_add(self._drag_tick, cx, cy, off)
        self.dragging = False
        GLib.idle_add(self._drag_finished)

    def _drag_tick(self, cx, cy, off):
        """On the cursor's screen, glued to the grab point, no clamp (the release clamps)."""
        if self.dragging:
            i, x, y = screens.drag_place(self._geoms(), (cx, cy), off, self.mon_i)
            self._place(x, y, False, i)
        return False

    def _drag_finished(self, edge=None):
        self.drag_t_end = time.monotonic()
        self.dpos = None
        if not self.pmoving:
            self._dock_if_edge(edge)
        self.pmoving = False
        self._rewide()
        if self.layer:
            self._place(self.mx, self.my, True)          # the whole surface (cards, a panel moved while docked) inside its screen
        if not self.bar:                                 # docked: his blob spot (bar_home) stays where it was
            self._save_pos()
        return False

    def _rewide(self):
        """After a drag the room either side of him has changed: re-fit the widened window."""
        if self.want_panel or self.want_code or self.want_xw or self.want_h:
            self.set_wide(self.want_panel)
        return False

    def drag_by(self, dx, dy):                      # no global cursor (e.g. sway): the page sends how far you dragged
        if self.layer and not self.hover:
            if self.bar and not self.pmoving:
                self.set_bar(None, to="here")             # pulling the notch away: the blob pops out right there
            geoms = self._geoms()
            # (dx,dy) is relative to where the window is now (the page measures from its own grab point), so the wanted
            # spot is today's spot plus it, never a running sum: held at an outer edge, it doesn't pile up overflow
            self.dpos = [geoms[self.mon_i][0] + self.mx + self._px(dx), geoms[self.mon_i][1] + self.my + self._px(dy)]
            ball = (self.wide_shift + self._px(BALL[0]), self.top_shift + self._px(BALL[1]))
            i = screens.mon_strict(geoms, self.dpos[0] + ball[0], self.dpos[1] + ball[1])
            i = self.mon_i if i is None else i
            nx, ny, ox, oy = screens.outer_clamp(geoms, i, self.dpos[0], self.dpos[1], self.cur_w, self.cur_h, ball)
            self._place(nx - geoms[i][0], ny - geoms[i][1], False, i)
            if getattr(self, "over", None) is not None:   # how far you pushed past an outer edge (he's clamped there)
                self.over = [ox, oy]

    def drag_end(self):
        if self.dragging:
            self.dragging = False
        elif self.layer:
            o, self.over = getattr(self, "over", None), None
            if o is None and self.dpos is None:            # no drag of ours is running (it ended already, or hover): nothing to release
                return
            edge = None
            if o and not self.pmoving:                     # pushed 40px+ past an edge: dock there
                if abs(o[1]) >= self._px(40) and abs(o[1]) >= abs(o[0]):
                    edge = "top" if o[1] < 0 else "bottom"
                elif abs(o[0]) >= self._px(40):
                    edge = "left" if o[0] < 0 else "right"
            self._drag_finished(edge)

    # ---- click-through: only what the page says is solid takes the mouse
    def _apply_region(self):
        gw = self.win.get_window()
        if gw is None:
            return
        if self.rects is None:                       # click-through off: the whole window takes clicks again
            if self.region_on:
                self.region_on = False
                try:
                    self.win.input_shape_combine_region(None)
                except (TypeError, AttributeError):
                    pass
            return
        if cairo is None or not hasattr(cairo, "Region"):
            return
        self.region_on = True
        reg = cairo.Region()
        for rect in self.rects:
            x, y, w, h = self._region_rect(rect)
            if w > 0 and h > 0:
                reg.union(cairo.RectangleInt(x, y, w, h))
        try:
            self.win.input_shape_combine_region(reg)
        except (TypeError, AttributeError):
            pass

    # ---- hover mode
    def set_hover(self, on):
        if on and not (self.hypr.ok() or (self._x11() and not self.layer)):
            log("hover mode: needs Hyprland or X11/XWayland — this Wayland desktop doesn't tell apps where the mouse is")
            self._js("window.nixiHoverUnsupported&&nixiHoverUnsupported()")
            return
        if self.hover == on:
            return
        if on and self.bar:                                        # hover mode is the blob: leave the edge first
            self.set_bar(None, glide=False)                        # (at once: the cursor-following starts here)
        home = (self.mon_i, self.mx + self.wide_shift, self.my + self.top_shift) if on else None
        self.hover = on
        if on and (self.cur_w > self._px(W) or self.cur_h > self._px(H) or self.top_shift):
            self.want_code = False
            self.set_wide(False)
        log(f"hover mode {'on' if on else 'off'}")
        self.cursor_hidden(on)
        if on:
            self.hpos = None
        self.mons = None
        if on:
            self.home = home
            threading.Thread(target=self._follow, daemon=True).start()
        elif getattr(self, "home", None):                          # glide from the cursor back to where he was parked
            threading.Thread(target=self._glide_home, daemon=True).start()
        self._js(f"window.nixiHover&&nixiHover({'true' if on else 'false'})")

    def _glide_home(self):
        m, hx, hy = self.home
        if not self.layer:                                 # window mode: plain screen coordinates
            start, (sx, sy) = self.hpos, (self.hpos or (hx, hy))
            t0, dur = time.monotonic(), 0.65
            while start:
                k = min(1.0, (time.monotonic() - t0) / dur)
                e = 1 - (1 - k) ** 3
                GLib.idle_add(self.win.move, int(sx + (hx - sx) * e), int(sy + (hy - sy) * e - math.sin(math.pi * k) * self._px(40)))
                if k >= 1:
                    break
                time.sleep(0.008)
            GLib.idle_add(self._xmove, int(hx), int(hy))
            GLib.idle_add(self._rewide)
            return
        _, g = self._geom(m)
        start = self.hpos                     # global position he was at as the cursor
        if not start:
            GLib.idle_add(self._place, hx, hy, True, m)
            GLib.idle_add(self._rewide)
            return
        sx, sy = start[0] - g.x, start[1] - g.y      # in home-monitor coordinates
        t0, dur = time.monotonic(), 0.65
        while True:
            k = min(1.0, (time.monotonic() - t0) / dur)
            e = 1 - (1 - k) ** 3                          # ease out
            arc = -math.sin(math.pi * k) * self._px(40)   # a little swoop up on the way
            GLib.idle_add(self._place, sx + (hx - sx) * e, sy + (hy - sy) * e + arc, False, m)
            if k >= 1:
                break
            time.sleep(0.008)
        GLib.idle_add(self._place, hx, hy, True, m)
        GLib.idle_add(self._rewide)

    def cursor_hidden(self, hide):
        """In hover mode he *is* the mouse pointer, so hide the real one (Hyprland's cursor:invisible; elsewhere it stays)."""
        if not self.hypr.ok():
            return
        try:
            v = "true" if hide else "false"
            r = self.hypr.req(f"keyword cursor:invisible {v}").strip()
            if r != "ok":                                  # Hyprland 0.56+ (Lua config): options are set through eval
                r = self.hypr.req(f"eval hl.config({{ cursor = {{ invisible = {v} }} }})").strip()
            if r != "ok":
                log(f"hyprland: couldn't {'hide' if hide else 'show'} the real cursor ({r!r}) — your Hyprland may be too old")
        except Exception as e:  # noqa: BLE001
            log(f"hyprland: cursor:invisible failed ({e})")

    @staticmethod
    def _x11():
        return Gdk.Display.get_default().__class__.__name__.startswith("X11")

    def _cursor(self):
        if self.hypr.ok():
            return self.hypr.cursor()
        seat = Gdk.Display.get_default().get_default_seat()
        _, x, y = seat.get_pointer().get_position()
        return x, y

    def _screen_of(self, cx, cy):
        if self.hypr.ok():
            try:
                if self.mons is None:
                    self.mons = self.hypr.monitors()
                for m in self.mons:
                    if m[0] <= cx < m[0] + m[2] and m[1] <= cy < m[1] + m[3]:
                        return m
            except Exception as e:  # noqa: BLE001
                log(f"hover: couldn't read monitors ({e})")
        scr = self.win.get_screen()
        return (0, 0, scr.get_width(), scr.get_height())

    def _follow(self):
        """Hover mode: he is the mouse pointer. ~120 times a second the window is moved so the centre of the ball sits
        right on the cursor; his eyes look the way you're moving."""
        fails = 0
        last = None
        vx = vy = 0.0
        while self.hover:
            time.sleep(0.008)
            if not self.shown:
                continue
            try:
                cx, cy = self._cursor()
            except Exception as e:  # noqa: BLE001
                fails += 1
                if fails in (1, 200):
                    log(f"hover: can't read the cursor position ({e})")
                continue
            now = time.monotonic()
            if last:
                dtt = max(1e-3, now - last[2])
                vx = vx * 0.8 + (cx - last[0]) / dtt * 0.2
                vy = vy * 0.8 + (cy - last[1]) / dtt * 0.2
            last = (cx, cy, now)
            x, y = cx - self._px(BALL[0]), cy - self._px(BALL[1])
            if self.hpos is None:
                self.hpos = [x, y]
            self.hpos[0] += (x - self.hpos[0]) * 0.7          # tiny bit of lag so he feels alive, not glued
            self.hpos[1] += (y - self.hpos[1]) * 0.7
            x, y = self.hpos
            GLib.idle_add(self._js, f"window.nixiLook&&nixiLook({max(-1, min(1, vx / 900)):.3f},{max(-1, min(1, vy / 900)):.3f})")
            if self.last_sent and abs(self.last_sent[0] - x) < 0.5 and abs(self.last_sent[1] - y) < 0.5:
                continue
            self.last_sent = (x, y)
            try:
                if self.layer:
                    i, g = self._mon_at(cx, cy)
                    GLib.idle_add(self._place, x - g.x, y - g.y, False, i)
                elif self.hypr.ok():
                    self.hypr.move(x, y)
                else:
                    GLib.idle_add(self.win.move, int(x), int(y))
            except Exception as e:  # noqa: BLE001
                log(f"hover: moving the window failed ({e})")

    # ---- messages from the page
    def _token(self, tries=50):
        rt = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "nixi-companion", "runtime.json")
        for _ in range(tries):                                         # (a just-started server writes it in a moment)
            try:
                with open(rt) as f:
                    return json.load(f)["token"]
            except (OSError, ValueError, KeyError):
                time.sleep(0.1)
        log("couldn't read the server's token (runtime.json)")
        return ""

    def _hand_token(self, tries=50):
        self.ucm.remove_all_scripts()
        tok = self._token(tries)
        if tok:
            src, allow = token_script(tok, urlparse(self.url).port)
            self.ucm.add_script(WebKit2.UserScript.new(src, WebKit2.UserContentInjectedFrames.TOP_FRAME,
                                                       WebKit2.UserScriptInjectionTime.START, allow, None))

    def _start_page(self):
        self.view.connect("load-changed", lambda _v, ev: self._send_corner() if ev == WebKit2.LoadEvent.FINISHED else None)
        origin = f"http://127.0.0.1:{urlparse(self.url).port}/"

        def retry():
            self._hand_token(tries=1)                                  # (no waiting on the main thread: it retries anyway)
            self.view.load_uri(self.url)
            return False

        def failed(_view, _ev, uri, err):
            if not uri.startswith(origin) or (err is not None and err.matches(WebKit2.network_error_quark(),
                                                                                WebKit2.NetworkError.CANCELLED)):
                return False                                       # (a newer load replaced this one: not a failure)
            GLib.timeout_add(1000, retry)
            return True

        self.view.connect("load-failed", failed)
        self._hand_token()
        self.view.load_uri(self.url)

    def _on_msg(self, _ucm, res):
        try:
            msg = res.get_js_value().to_string()
        except AttributeError:
            msg = res.to_string()
        if msg == "reauth":                                            # the server restarted: hand over its new token
            self._hand_token()
            self.view.load_uri(self.url)
            return
        if msg.startswith("zoom:"):
            self.set_zoom(msg[5:])
            return
        if msg.startswith("region:"):
            try:
                self.rects = json.loads(msg[7:])
            except ValueError:
                self.rects = None
            self._apply_region()
            return
        if msg.startswith("dragby:"):
            try:
                dx, dy = (float(v) for v in msg[7:].split(","))
                self.drag_by(dx, dy)
            except ValueError:
                pass
            return
        {"drag": self.drag, "pmove": lambda: self.drag(panel=True), "dragend": self.drag_end,
         "hide": self.hide, "show": self.show,
         "hover:on": lambda: self.set_hover(True), "hover:off": lambda: self.set_hover(False),
         "bar:top": lambda: self.set_bar("top"), "bar:bottom": lambda: self.set_bar("bottom"),
         "bar:left": lambda: self.set_bar("left"), "bar:right": lambda: self.set_bar("right"),
         "bar:off": lambda: self.set_bar(None),
         "wide:on": lambda: self.set_wide(True), "wide:off": lambda: self.set_wide(False),
         "kbd:grab": lambda: self.keyboard(True), "kbd:release": lambda: self.keyboard(False),
         "code:on": lambda: self.set_wide(True, "code"), "code:off": lambda: self.set_wide(False, "code"),
         "peek:hide": self.win.hide, "peek:show": self.show,
         "doze:hide": self.win.hide, "doze:show": self._doze_show,
         "follow:on": lambda: setattr(self, "follow_focus", True), "follow:off": lambda: setattr(self, "follow_focus", False),
         "aside:set-on": lambda: setattr(self, "step_aside", True), "aside:set-off": lambda: setattr(self, "step_aside", False),
         }.get(msg, (lambda: self.go_monitor(msg[8:])) if msg.startswith("monitor:") else
               (lambda: self.set_wide((int(msg[5:].split(",")[0]), int(msg[5:].split(",")[1])), "size")) if msg.startswith("size:") else (lambda: None))()

    def _serve(self):
        try:
            os.unlink(SOCK)
        except FileNotFoundError:
            pass
        srv = socket.socket(socket.AF_UNIX)
        srv.bind(SOCK)
        os.chmod(SOCK, 0o600)
        srv.listen(4)
        while True:
            c, _ = srv.accept()
            try:
                cmd = c.recv(64).decode().strip()
            finally:
                c.close()
            fn = (lambda: (self.go_monitor(cmd[8:]), False)[1]) if cmd.startswith("monitor:") else {"toggle": self.toggle, "show": self.show, "hide": self.hide, "quit": self.quit,
                  "aside:on": self.aside_on, "aside:off": self.aside_off, "listen": lambda: self.cmd("listen"), "look": lambda: self.cmd("look"), "live": lambda: self.cmd("live"),
                  "hover": lambda: self.cmd("hover"), "hover-on": lambda: self.cmd("hover-on"),
                  "hover-off": lambda: self.cmd("hover-off"),
                  "ptt-down": lambda: self.cmd("ptt-down"), "ptt-up": lambda: self._js("window.nixiCmd&&nixiCmd('ptt-up')")}.get(cmd)
            if fn:
                GLib.idle_add(fn)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--check":          # `nixi-companion doctor`: can he be an overlay here?
        notes = "; ".join(LAYER_WHY)
        if GtkLayerShell is not None:
            print("overlay: yes — he floats on a layer above your apps" + (f"  ({notes})" if notes else ""))
        else:
            print("overlay: no — he'll be an always-on-top window instead, because: " + (notes or "unknown"))
        return
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    url, cmd = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "toggle")
    if cmd == "--selftest-bar" and len(sys.argv) > 4:            # dock on an edge, report where, save a picture (CI)
        edge, out = sys.argv[3], sys.argv[4]
        win = NixiWindow(url)

        def report():
            gw = win.win.get_window()
            x, y = gw.get_root_origin() if not win.layer else (win.mx, win.my)
            w, h = win.win.get_size()
            if win.layer:
                a = win._geom()[1]
            else:
                a = win._monitors()[win._mon_at(x + win._px(W) // 2, y + win._px(H) // 2)[0]].get_workarea()
            try:
                Gdk.pixbuf_get_from_window(gw, 0, 0, w, h).savev(out, "png", [], [])
            except Exception as e:  # noqa: BLE001
                log(f"selftest-bar: no picture ({e})")

            def done(view, res):
                try:
                    cls = view.evaluate_javascript_finish(res).to_string()
                except Exception:  # noqa: BLE001
                    cls = "?"
                print(f"selftest-bar: {edge} x={x} y={y} w={w} h={h} area={a.x},{a.y},{a.width},{a.height} "
                      f"layer={win.layer} page={cls}", flush=True)
                Gtk.main_quit()
            try:
                win.view.evaluate_javascript("document.body.className", -1, None, None, None, done)
            except (AttributeError, TypeError):                     # (older WebKitGTK)
                print(f"selftest-bar: {edge} x={x} y={y} w={w} h={h} area={a.x},{a.y},{a.width},{a.height} "
                      f"layer={win.layer} page=?", flush=True)
                Gtk.main_quit()
            return False
        GLib.timeout_add(12000, lambda: (win.set_bar(edge), False)[1])     # (slow test machines: let the page load)
        GLib.timeout_add(15000, report)
        Gtk.main()
        return
    if send(cmd):
        return
    if cmd in ("hide", "quit"):
        return
    win = NixiWindow(url)
    if cmd in ("listen", "look", "live", "hover", "hover-on"):
        GLib.timeout_add(1800, lambda: (win.cmd(cmd), False)[1])     # first launch: let the page load, then do it
    try:
        Gtk.main()
    finally:
        if win.hover:
            win.cursor_hidden(False)
        try:
            os.unlink(SOCK)
        except OSError:
            pass


if __name__ == "__main__":
    main()
