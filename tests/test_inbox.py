import json
import os
import socketserver
import tempfile
import threading
import time
import unittest
from unittest import mock

from test_speakable import _ServerEnv


class _Shell(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def serve(path, reply):
    """A fake shell: `reply(method, args)` is the text after OK (None: SKIP)."""
    calls = []

    class H(socketserver.BaseRequestHandler):
        def handle(self):
            buf = b""
            while not buf.endswith(b"\x1e"):
                buf += self.request.recv(4096)
            _, method, *args = buf[:-1].decode().split("\x1f")
            calls.append((method, args))
            out = reply(method, args)
            self.request.sendall(b"SKIP\x1e" if out is None else b"OK\x1f" + out.encode() + b"\x1e")

    srv = _Shell(path, H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, calls


class InboxTest(_ServerEnv):
    """#133: the lease on the shell's socket, and what may reach the page."""

    def setUp(self):
        S = self.server
        self.rt = tempfile.mkdtemp(prefix="nixi-inbox-", dir="/tmp")
        self.addCleanup(__import__("shutil").rmtree, self.rt, True)
        env = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.rt, "OMARCHY_PATH": "/o", "WAYLAND_DISPLAY": "w-1"})
        env.start()
        self.addCleanup(env.stop)
        saved = dict(S.CFG)
        self.addCleanup(lambda: (S.CFG.clear(), S.CFG.update(saved)))
        S.CFG.update(proactive=True, notifications_takeover=True, notify_details=False)
        S.Inbox.path, S.Inbox.wanted = None, False
        S.Inbox.unseen.clear()
        self.servers = []
        self.addCleanup(lambda: [x.shutdown() or x.server_close() for x in self.servers])

    def shell(self, reply, path=None):
        srv, calls = serve(path or self.server.Inbox._derived()[1], reply)
        self.servers.append(srv)
        return calls

    def test_path_derivation(self):
        import hashlib
        h = hashlib.md5(b"/o/shell\nw-1").hexdigest()[:16]
        self.assertEqual(self.server.Inbox._derived()[1], f"{self.rt}/omarchy-shell-{h}.sock")

    def test_fallback_skips_a_dead_socket(self):
        dead = f"{self.rt}/omarchy-shell-0000000000000000.sock"
        import socket
        s = socket.socket(socket.AF_UNIX)
        s.bind(dead)
        s.close()                                              # a file nobody listens on: ECONNREFUSED
        live = f"{self.rt}/omarchy-shell-1111111111111111.sock"
        self.shell(lambda m, a: "ok", live)
        self.assertEqual(self.server.Inbox.sock_path(), live)

    def test_oversized_reply_is_refused(self):
        self.shell(lambda m, a: "x" * (70 * 1024) if m == "delegate" else "ok")
        self.assertIsNone(self.server.Inbox.call("delegate", "5000"))

    def test_skip_means_no_lease(self):
        self.shell(lambda m, a: "ok" if m == "ping" else None)
        self.assertIsNone(self.server.Inbox.call("delegate", "5000"))

    def row(self, **kw):
        return {"key": "nabc12", "app": "teams", "source": "", "summary": "Ana", "body": "hi", "urgency": 1, "category": "chat", **kw}

    def test_bad_rows_are_dropped(self):
        rows = [self.row(key="../x"), self.row(category="evil"), "str", self.row(key="n" + "a" * 64), self.row()]
        self.assertEqual([r["key"] for r in self.server.Inbox.rows(json.dumps(rows))], ["nabc12"])

    def test_text_only_with_details(self):
        S = self.server
        out = json.dumps([self.row()])
        self.assertEqual((S.Inbox.rows(out)[0]["summary"], S.Inbox.rows(out)[0]["body"]), ("", ""))
        S.CFG["notify_details"] = True
        self.assertEqual(S.Inbox.rows(out)[0]["summary"], "Ana")
        secret = json.dumps([self.row(summary="Bank", body="Your code is 482910")])
        self.assertEqual(S.Inbox.rows(secret)[0]["body"], "")
        for txt in ("482910 is your Signal PIN", "Your sign-in code: 482 910", "Use X7K92B to log in", "one-time password 12345678"):
            self.assertEqual(S.Inbox.rows(json.dumps([self.row(summary=txt, body="")]))[0]["summary"], "", txt)
        for txt in ("Lunch at 12?", "Ana sent 3 photos", "Build 2026 passed"):
            self.assertEqual(S.Inbox.rows(json.dumps([self.row(summary=txt, body="")]))[0]["summary"], txt, txt)

    def test_want_false_while_asleep(self):
        S = self.server
        with mock.patch.object(S.BUS, "subs", [object()]), mock.patch.object(S.Wake, "asleep", False):
            self.assertTrue(S.Inbox.want())
        with mock.patch.object(S.BUS, "subs", [object()]), mock.patch.object(S.Wake, "asleep", True):
            self.assertFalse(S.Inbox.want())

    def test_a_row_unseen_for_5s_is_shown_by_the_shell(self):
        S = self.server
        calls = self.shell(lambda m, a: "[]")
        S.Inbox.unseen.update({"nold": time.monotonic() - 6, "nnew": time.monotonic()})
        with mock.patch.object(S.BUS, "subs", []):          # (given back even when no lease is wanted)
            S.Inbox.tick()
        self.assertIn(("showKey", ["nold"]), calls)
        self.assertNotIn(("showKey", ["nnew"]), calls)
        self.assertEqual(list(S.Inbox.unseen), ["nnew"])
        S.Inbox.seen("nnew")
        self.assertFalse(S.Inbox.unseen)


if __name__ == "__main__":
    unittest.main()
