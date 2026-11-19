"""`size` reads shared.json under config.json in the window and in `nixi-companion size` (#99)."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

import nixi_env

ROOT = Path(__file__).resolve().parent.parent
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
    patches = [mock.patch.dict(sys.modules, mods), mock.patch.dict(os.environ, env), mock.patch.object(sys, "path", [str(ROOT / "app")] + sys.path)]
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
        os.sched_setaffinity(0, cores)
        for p in reversed(patches):
            p.stop()
        for m in ("window", "aside", "screens"):
            sys.modules.pop(m, None)


def tearDownModule():
    for u in _undo:
        u()


class SharedSizeTest(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.conf = Path(self.t.name) / "config" / "nixi-companion"
        self.conf.mkdir(parents=True)

    def put(self, name, text):
        (self.conf / name).write_text(text)

    def test_window_layers(self):
        with mock.patch.object(window, "CONF_FILE", str(self.conf / "config.json")):
            self.assertEqual(window.saved_size(), 0.75)
            self.put("shared.json", '{"size": 1.0}')
            self.assertEqual(window.saved_size(), 1.0)
            self.put("config.json", '{"size": 0.5}')
            self.assertEqual(window.saved_size(), 0.5)
            self.put("config.json", "{")
            self.assertEqual(window.saved_size(), 1.0)
            self.put("shared.json", "{")
            self.assertEqual(window.saved_size(), 0.75)

    def test_cli_size_up_uses_shared(self):
        got = []

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                got.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass
        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        home = Path(self.t.name)
        data = home / "data" / "nixi-companion"
        data.mkdir(parents=True)
        (data / "runtime.json").write_text(json.dumps({"port": srv.server_port, "token": "t"}))
        run = Path(nixi_env.run_dir())
        sock = run / f"nixi-companion-{os.getuid()}.sock"
        sock.unlink(missing_ok=True)
        ls = socket.socket(socket.AF_UNIX)
        ls.bind(str(sock))
        self.addCleanup(sock.unlink, True)
        self.addCleanup(ls.close)
        self.put("shared.json", '{"size": 1.0}')
        env = {**os.environ, "HOME": str(home), "XDG_CONFIG_HOME": str(home / "config"), "XDG_DATA_HOME": str(home / "data"),
               "XDG_RUNTIME_DIR": str(run), "NIXI_COMPANION_APP": str(ROOT / "app"), "NIXI_COMPANION_PYTHON": sys.executable}
        subprocess.run([str(ROOT / "bin" / "nixi-companion"), "size", "up"], env=env, timeout=30, check=False)
        self.assertEqual(len(got), 1)
        self.assertGreater(got[0]["size"], 1.0)

    def test_cli_text_up_uses_shared(self):
        got = []

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                got.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass
        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        home = Path(self.t.name)
        data = home / "data" / "nixi-companion"
        data.mkdir(parents=True)
        (data / "runtime.json").write_text(json.dumps({"port": srv.server_port, "token": "t"}))
        run = Path(nixi_env.run_dir())
        sock = run / f"nixi-companion-{os.getuid()}.sock"
        sock.unlink(missing_ok=True)
        ls = socket.socket(socket.AF_UNIX)
        ls.bind(str(sock))
        self.addCleanup(sock.unlink, True)
        self.addCleanup(ls.close)
        self.put("shared.json", '{"card_text": 1.0}')
        env = {**os.environ, "HOME": str(home), "XDG_CONFIG_HOME": str(home / "config"), "XDG_DATA_HOME": str(home / "data"),
               "XDG_RUNTIME_DIR": str(run), "NIXI_COMPANION_APP": str(ROOT / "app"), "NIXI_COMPANION_PYTHON": sys.executable}
        subprocess.run([str(ROOT / "bin" / "nixi-companion"), "text", "up"], env=env, timeout=30, check=False)
        self.assertEqual(len(got), 1)
        self.assertGreater(got[0]["card_text"], 1.0)


if __name__ == "__main__":
    unittest.main()
