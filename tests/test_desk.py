import json
import os
import shutil
import socket
import socketserver
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from test_speakable import _ServerEnv


def serve(path, handler):
    class S(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

    class H(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                handler(self.request)
            except OSError:                                   # (the liveness probe hangs up at once)
                pass

    srv = S(str(path), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class DeskTest(_ServerEnv):
    """#133b: Hyprland's event socket and lock state; titles are never kept."""

    def setUp(self):
        self.rt = tempfile.mkdtemp(prefix="nixi-desk-", dir="/tmp")
        self.addCleanup(shutil.rmtree, self.rt, True)
        env = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.rt, "HYPRLAND_INSTANCE_SIGNATURE": "live"})
        env.start()
        self.addCleanup(env.stop)
        D = self.server.Desk
        D.fullscreen, D.last_switch, D.last_event, D.dir = False, 0.0, 0.0, None
        self.servers = []
        self.addCleanup(lambda: [x.shutdown() or x.server_close() for x in self.servers])

    def inst(self, sig, events=None, monitors=None):
        d = Path(self.rt) / "hypr" / sig
        d.mkdir(parents=True)
        if events is not None:
            self.servers.append(serve(d / ".socket2.sock", lambda c: c.sendall(events)))
        if monitors is not None:
            def answer(c):
                assert c.recv(64) == b"j/monitors"
                c.sendall(json.dumps(monitors).encode())
            self.servers.append(serve(d / ".socket.sock", answer))
        return d

    def test_fullscreen_on_and_off(self):
        D = self.server.Desk
        D.on_event("fullscreen>>1")
        self.assertTrue(D.fullscreen)
        D.on_event("fullscreen>>0")
        self.assertFalse(D.fullscreen)

    def test_reads_a_stream_and_keeps_no_titles(self):
        D = self.server.Desk
        self.addCleanup(self.server.CFG.__setitem__, "proactive", self.server.CFG.get("proactive"))
        self.server.CFG["proactive"] = True                   # (Desk reads only for those who opted in)
        d = self.inst("live", b"activewindow>>kitty,SECRET TITLE\nfullscreen>>1\nworkspacev2>>2,two\nopenwindow>>1,2,3,SECRET\n")
        D.read(d / ".socket2.sock")
        self.assertTrue(D.fullscreen)
        self.assertGreater(D.last_switch, 0)
        self.assertGreater(D.last_event, 0)
        for k, v in vars(D).items():
            self.assertNotIn("SECRET", repr(v), k)

    def test_stale_signature_falls_back_to_a_live_one(self):
        D = self.server.Desk
        os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = "stale"
        stale = Path(self.rt) / "hypr" / "stale"
        stale.mkdir(parents=True)
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(stale / ".socket2.sock"))
        s.close()                                              # a socket file nobody listens on
        live = self.inst("other", b"")
        self.assertEqual(D.instance(), live)

    def test_no_instance(self):
        self.assertIsNone(self.server.Desk.instance())

    def test_lock_detection(self):
        D = self.server.Desk
        self.inst("live", b"", [{"name": "DP-1", "solitaryBlockedBy": ["WINDOWED"]}])
        self.assertFalse(D.locked())
        shutil.rmtree(Path(self.rt) / "hypr")
        for x in self.servers:
            x.shutdown()
            x.server_close()
        self.servers.clear()
        self.inst("live", b"", [{"name": "DP-1", "solitaryBlockedBy": ["LOCK", "X"]}, {"name": "DP-2", "solitaryBlockedBy": []}])
        D.dir = None
        self.assertTrue(D.locked())

    def test_locked_is_false_without_hyprland(self):
        self.assertFalse(self.server.Desk.locked())


if __name__ == "__main__":
    unittest.main()
