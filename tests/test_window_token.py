"""The window hands the page its token through a WebKit user script, never in the URL (#181).

No display: gi and its repository are stubbed with recording fakes before window.py is imported."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import nixi_env

APP = str(Path(__file__).resolve().parent.parent / "app")
URL = "http://127.0.0.1:47777/?native=1"
window = None
_undo = []


def setUpModule():
    global window
    gi, repo = mock.MagicMock(), mock.MagicMock()
    mods = {"gi": gi, "gi.repository": repo}
    for n in ("Gtk", "Gdk", "GLib", "WebKit2", "GtkLayerShell"):
        mods[f"gi.repository.{n}"] = getattr(repo, n)
    gi.repository = repo
    tmp = tempfile.TemporaryDirectory()
    _undo.append(tmp.cleanup)
    env = {"NIXI_COMPANION_NO_LAYER": "1", "NIXI_COMPANION_NO_XWAYLAND": "1", "XDG_CONFIG_HOME": tmp.name}
    patches = [mock.patch.dict(sys.modules, mods), mock.patch.dict(os.environ, env), mock.patch.object(sys, "path", [APP] + sys.path)]
    cores = os.sched_getaffinity(0)
    for p in patches:
        p.start()
    for k in ("NIXI_COMPANION_LAYER_WHY", "WAYLAND_DISPLAY"):
        os.environ.pop(k, None)
    try:
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": nixi_env.run_dir()}):
            import window as w
        window = w
    finally:
        os.sched_setaffinity(0, cores)                  # _cpu_split() may have halved it
        for p in reversed(patches):
            p.stop()
        for m in ("window", "aside", "screens"):
            sys.modules.pop(m, None)


def tearDownModule():
    for f in _undo:
        f()


class WindowToken(unittest.TestCase):
    def setUp(self):
        self.m = mock.MagicMock()
        self.w = window.NixiWindow.__new__(window.NixiWindow)
        self.w.view, self.w.ucm, self.w.url = self.m.view, self.m.ucm, URL
        window.GLib.timeout_add.side_effect = lambda ms, fn, *a: fn(*a) and 0
        p = mock.patch.object(window.NixiWindow, "_token", return_value="tok", create=True)
        p.start()
        self.addCleanup(p.stop)
        window.WebKit2.UserScript.new.reset_mock()
        window.WebKit2.NetworkError.CANCELLED = 302      # a distinct int, so a MagicMock never equals it by accident

    def err(self, cancelled):
        """A GLib.Error stand-in: matches() is true only for (WebKit's network domain, CANCELLED)."""
        q = window.WebKit2.network_error_quark.return_value
        return mock.Mock(**{"matches.side_effect": lambda d, c: cancelled and d is q and c == 302})

    def order(self):
        names = [c[0] for c in self.m.mock_calls]
        return [n for n in names if n in ("ucm.remove_all_scripts", "ucm.add_script", "view.load_uri")]

    def assert_handed(self):
        self.assertEqual(self.order(), ["ucm.remove_all_scripts", "ucm.add_script", "view.load_uri"])
        uri = self.m.view.load_uri.call_args[0][0]
        self.assertEqual(uri, URL)
        self.assertNotIn("#", uri)
        self.assertEqual(window.WebKit2.UserScript.new.call_args[0][0], 'if(location.origin==="http://127.0.0.1:47777")window.__nixiT="tok";')
        self.assertEqual(window.WebKit2.UserScript.new.call_args[0][3], ["http://127.0.0.1/*"])   # WebKit's allow-list ignores ports

    def callback(self):
        cbs = [c[0][1] for c in self.m.view.connect.call_args_list if c[0][0] == "load-failed"]
        self.assertEqual(len(cbs), 1, "_start_page must connect load-failed once")
        return cbs[0]

    def test_token_script(self):
        self.assertEqual(window.token_script("abc", 47777),
                         ('if(location.origin==="http://127.0.0.1:47777")window.__nixiT="abc";', ["http://127.0.0.1/*"]))
        self.assertIn('\\"', window.token_script('a"b', 1)[0])

    def test_start_page(self):
        self.w._start_page()
        self.callback()
        self.assert_handed()

    def test_load_failed_retries(self):
        self.w._start_page()
        cb = self.callback()
        self.m.reset_mock()
        window.WebKit2.UserScript.new.reset_mock()
        self.assertIs(cb(self.m.view, None, "http://127.0.0.1:47777/?native=1", self.err(False)), True)
        self.assert_handed()
        self.assertEqual(window.NixiWindow._token.call_args[0], (1,))   # a retry never waits on the main thread

    def test_load_failed_elsewhere_is_left_alone(self):
        self.w._start_page()
        cb = self.callback()
        self.m.reset_mock()
        for uri in ("https://example.com/", "http://127.0.0.1:477770/"):   # the second would prefix-match without the slash
            self.assertIsNot(cb(self.m.view, None, uri, None), True)
        self.assertEqual(self.order(), [])

    def test_cancelled_load_is_left_alone(self):
        self.w._start_page()
        cb = self.callback()
        self.m.reset_mock()
        self.assertIs(cb(self.m.view, None, URL, self.err(True)), False)
        self.assertEqual(self.order(), [])

    def test_reauth(self):
        self.w._on_msg(None, mock.MagicMock(**{"get_js_value.return_value.to_string.return_value": "reauth"}))
        self.assert_handed()


if __name__ == "__main__":
    unittest.main()
