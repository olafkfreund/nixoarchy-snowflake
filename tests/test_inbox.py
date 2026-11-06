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
        S.Inbox.origin.clear()
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

    def test_feeds_are_relabelled(self):
        rows = [self.row(key="n1", category="other", source="www.reddit.com"), self.row(key="n2", category="other", app="freetube"),
                self.row(key="n3", category="mail", source="reddit.com"), self.row(key="n4", category="other", source="example.org"),
                self.row(key="n5", category="other", app="tubafont")]
        self.assertEqual([r["category"] for r in self.server.Inbox.rows(json.dumps(rows))], ["video", "video", "mail", "other", "other"])

    def test_mail_and_chat_the_shell_misses(self):
        rows = [self.row(key="o1", category="other", app="Omamail", source="Omamail"),
                self.row(key="o2", category="other", app="Google Chrome", source="outlook.cloud.microsoft"),
                self.row(key="w1", category="other", app="Google Chrome", source="web.whatsapp.com"),
                self.row(key="f1", category="other", app="Google Chrome", source="www.messenger.com"),
                self.row(key="m1", category="meeting", app="teams-for-linux", source="outlook"),
                self.row(key="x1", category="other", app="Google Chrome", source="claude.ai")]
        self.assertEqual([r["category"] for r in self.server.Inbox.rows(json.dumps(rows))], ["mail", "mail", "chat", "chat", "meeting", "other"])

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

    def post(self, key="nabc12", how="open"):
        S = self.server
        handler = mock.Mock()
        handler.path = "/api/notify/act"
        handler.headers = {"Host": "127.0.0.1", "X-Nixi-Token": S.TOKEN}
        handler._body.return_value = json.dumps({"key": key, "how": how}).encode()
        handler._host_ok = lambda: S.Handler._host_ok(handler)
        S.Handler.do_POST(handler)
        return handler._json.call_args.args

    def test_origin_only_native_mail_chat_and_expires_without_rows(self):
        S = self.server
        rows = [self.row(key=f"k{i}") for i in range(66)]
        rows += [self.row(key="browser", app="google-chrome"), self.row(key="brave", app="brave-browser"),
                 self.row(key="host", source="web.whatsapp.com"), self.row(key="job", category="other", app="nixi-job"),
                 self.row(key="notify", category="other", app="notify-send")]
        with mock.patch.object(S.Inbox, "want", return_value=True), mock.patch.object(S.Inbox, "call", return_value=json.dumps(rows)), mock.patch.object(S.BUS, "pub"):
            S.Inbox.tick()
        self.assertEqual(len(S.Inbox.origin), 64)
        self.assertNotIn("k0", S.Inbox.origin)
        self.assertEqual(S.Inbox.origin["k65"][:2], ("teams", ""))
        self.assertTrue(all(len(value) == 3 and "Ana" not in value and "hi" not in value for value in S.Inbox.origin.values()))
        for key in ("browser", "brave", "host", "job", "notify"):
            self.assertNotIn(key, S.Inbox.origin)
        with mock.patch.object(S.Inbox, "want", return_value=False), mock.patch.object(S.Inbox, "call"), mock.patch.object(S.time, "monotonic", return_value=time.monotonic() + 601):
            S.Inbox.tick()
        self.assertFalse(S.Inbox.origin)

    def test_route_uses_focus_before_shell_and_only_once(self):
        S = self.server
        S.Inbox.origin["nabc12"] = ("Teams", "", time.monotonic())
        order = []
        def focused():
            order.append("focus")
            return "0x1"
        def call_shell(method, key):
            order.append("shell")
            return "ok"
        with mock.patch.object(S, "_focused_addr", side_effect=focused), mock.patch.object(S.threading, "Thread") as thread, mock.patch.object(S.Inbox, "call", side_effect=call_shell) as call:
            self.assertEqual(self.post(), ({"ok": True},))
            self.assertEqual(self.post(), ({"ok": True},))
            self.assertEqual(order, ["focus", "shell", "shell"])
            thread.assert_called_once()
            self.assertEqual(thread.call_args.kwargs["args"], ("Teams", "", "0x1"))
        self.assertEqual(call.call_args_list, [mock.call("activateKey", "nabc12"), mock.call("activateKey", "nabc12")])
        self.assertFalse(S.Inbox.origin)

    def test_route_skips_follow_up_without_focus_or_shell_success(self):
        S = self.server
        with mock.patch.object(S, "_focused_addr", return_value=None), mock.patch.object(S.threading, "Thread") as thread, mock.patch.object(S.Inbox, "call", return_value="ok"):
            S.Inbox.origin["nabc12"] = ("Foo", "", time.monotonic())
            self.assertEqual(self.post(), ({"ok": True},))
            thread.assert_not_called()
        with mock.patch.object(S, "_focused_addr", return_value="0x1"), mock.patch.object(S.threading, "Thread") as thread, mock.patch.object(S.Inbox, "call", return_value=None):
            S.Inbox.origin["nabc12"] = ("Foo", "", time.monotonic())
            self.assertEqual(self.post(), ({"ok": False},))
            thread.assert_not_called()

    def test_route_refuses_bad_action_and_dismiss_drops_origin(self):
        S = self.server
        S.Inbox.origin["nabc12"] = ("Teams", "", time.monotonic())
        with mock.patch.object(S, "_focused_addr") as focus, mock.patch.object(S.threading, "Thread") as thread, mock.patch.object(S.Inbox, "call", return_value="ok") as call:
            self.assertEqual(self.post(how="bad"), ({"error": "bad request"}, 400))
            self.assertEqual(self.post(how="dismiss"), ({"ok": True},))
            self.assertEqual(self.post(key="unknown"), ({"ok": True},))
            focus.assert_not_called()
            thread.assert_not_called()
        self.assertFalse(S.Inbox.origin)
        self.assertEqual(call.call_args_list, [mock.call("dismissKey", "nabc12"), mock.call("activateKey", "unknown")])

    def test_focus_helpers_never_treat_failure_as_empty_workspace(self):
        S = self.server
        with mock.patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": ""}), mock.patch.object(S.shutil, "which", return_value="hyprctl"), mock.patch.object(S, "_run") as run:
            self.assertIsNone(S._focused_addr())
            run.assert_not_called()
        with mock.patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "test"}), mock.patch.object(S.shutil, "which", return_value="hyprctl"), mock.patch.object(S, "_run") as run:
            for code, out, want in ((1, b"{}", None), (0, b"", None), (0, b"bad", None), (0, b"{}", ""), (0, b'{"address":"0x1"}', "0x1")):
                run.return_value = mock.Mock(returncode=code, stdout=out)
                self.assertEqual(S._focused_addr(), want)

    def test_capture_window_keeps_using_position_helper(self):
        S = self.server
        def shot(cmd, **kw):
            if cmd[0] == "grim":
                __import__("pathlib").Path(cmd[-1]).write_bytes(b"image")
            return mock.Mock(returncode=0)
        with mock.patch.object(S, "SHOTS", __import__("pathlib").Path(self.rt)), mock.patch.object(S, "_active_window", return_value=(1, 2, 3, 4)) as active, \
             mock.patch.object(S, "_focused_addr") as focused, mock.patch.object(S.shutil, "which", side_effect=lambda x: x if x == "grim" else None), \
             mock.patch.object(S, "_run", side_effect=shot) as run, mock.patch.object(S, "_shrink", side_effect=lambda p: p):
            self.assertEqual(S.capture("window")["kind"], "window")
            self.assertEqual(run.call_args.args[0][:3], ["grim", "-g", "1,2 3x4"])
            active.assert_called_once()
            focused.assert_not_called()

    def test_follow_up_launch_focus_and_failure(self):
        S = self.server
        entry = {"id": "org.foo.Bar", "wmclass": "foo"}
        with mock.patch.object(S.time, "sleep"), mock.patch.object(S, "_focused_addr", return_value="0x1") as focused, \
             mock.patch.object(S.Icons, "desktop_for", return_value=entry) as desktop, \
             mock.patch.object(S, "_window_for", return_value=None) as window, \
             mock.patch.object(S.shutil, "which", return_value="/bin/gtk-launch"), \
             mock.patch.object(S.quick, "_spawn") as spawn, mock.patch.object(S, "_focus") as focus, \
             mock.patch.object(S.BUS, "pub") as pub:
            S.Inbox.follow_up("Foo", "", "0x2")
            desktop.assert_not_called()
            focused.return_value = None
            S.Inbox.follow_up("Foo", "", "0x1")
            desktop.assert_not_called()
            focused.return_value = "0x1"
            S.Inbox.follow_up("Foo", "", "0x1")
            spawn.assert_called_once_with(["gtk-launch", "org.foo.Bar"])
            focused.return_value = ""
            S.Inbox.follow_up("Foo", "", "")
            self.assertEqual(spawn.call_count, 2)
            focused.return_value = "0x1"
            window.return_value = "0x1"
            S.Inbox.follow_up("Foo", "", "0x1")
            self.assertEqual(spawn.call_count, 2)
            window.return_value = "0x2"
            S.Inbox.follow_up("Foo", "", "0x1")
            focus.assert_called_once_with("0x2")
            window.side_effect = S.subprocess.CalledProcessError(1, "hyprctl")
            S.Inbox.follow_up("Foo", "", "0x1")
            self.assertEqual(spawn.call_count, 2)
            desktop.return_value = None
            S.Inbox.follow_up("Missing", "", "0x1")
            pub.assert_called_once_with(t="toast", text="I couldn't find Missing on this machine.")

    def test_launch_without_gtk_launch_toasts(self):
        S = self.server
        with mock.patch.object(S.shutil, "which", return_value=None), mock.patch.object(S.quick, "_spawn") as spawn, mock.patch.object(S.BUS, "pub") as pub:
            S._launch("org.foo.Bar")
            spawn.assert_not_called()
            pub.assert_called_once_with(t="toast", text="I can't start apps here: gtk-launch isn't installed.")

    def test_window_match_and_focus_commands_are_address_only(self):
        S = self.server
        entry = {"id": "org.foo.Bar", "wmclass": "foowm"}
        clients = [{"address": "0x3", "class": "Foo", "focusHistoryID": 5},
                   {"address": "0x2", "initialClass": "FooWM", "focusHistoryID": 1}]
        with mock.patch.object(S, "_run") as run:
            run.return_value = mock.Mock(stdout=json.dumps(clients).encode(), returncode=0, check_returncode=lambda: None)
            self.assertEqual(S._window_for(entry, "Foo", ""), "0x2")
            run.return_value.stdout = json.dumps(clients[:1]).encode()
            self.assertEqual(S._window_for(entry, "Foo", ""), "0x3")
            run.return_value = mock.Mock(returncode=1)
            S._focus("bad; command")
            self.assertEqual(run.call_count, 2)
            S._focus("0xabc")
            self.assertEqual(run.call_args.args[0], ["hyprctl", "dispatch", "focuswindow", "address:0xabc"])


if __name__ == "__main__":
    unittest.main()
