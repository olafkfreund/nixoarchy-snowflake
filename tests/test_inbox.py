import subprocess
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
        S.Inbox.acts.clear()
        S.Inbox.legacy = False
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
        self.shell(lambda m, a: "x" * (1024 * 1024 + 1) if m == "delegate" else "ok" if m != "big" else "x" * (300 * 1024))
        self.assertIsNone(self.server.Inbox.call("delegate", "5000"))
        self.assertEqual(len(self.server.Inbox.call("big")), 300 * 1024)

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

    def post(self, key="nabc12", how="open", **extra):
        S = self.server
        handler = mock.Mock()
        handler.path = "/api/notify/act"
        handler.headers = {"Host": "127.0.0.1", "X-Nixi-Token": S.TOKEN}
        handler._body.return_value = json.dumps({"key": key, "how": how, **extra}).encode()
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

    def test_window_for_ignores_never_focused_and_unmapped(self):
        S = self.server
        entry = {"id": "foo", "wmclass": ""}
        clients = [{"address": "0x9", "class": "foo", "focusHistoryID": -1}, {"address": "0x8", "class": "foo", "mapped": False, "focusHistoryID": 0},
                   {"address": "0x1", "class": "foo", "focusHistoryID": 2}]
        with mock.patch.object(S, "_run", return_value=mock.Mock(stdout=json.dumps(clients).encode(), returncode=0, check_returncode=lambda: None)):
            self.assertEqual(S._window_for(entry, "", ""), "0x1")

    def test_a_failing_clients_call_starts_nothing(self):
        S = self.server
        failed = subprocess.CompletedProcess(["hyprctl"], 1, b"", b"")
        with mock.patch.object(S.time, "sleep"), mock.patch.object(S, "_focused_addr", return_value="0x1"), mock.patch.object(S, "_run", return_value=failed), \
             mock.patch.object(S.Icons, "desktop_for", return_value={"id": "foo", "wmclass": ""}), mock.patch.object(S.quick, "_spawn") as spawn, mock.patch.object(S.BUS, "pub") as pub:
            S.Inbox.follow_up("foo", "", "0x1")
        spawn.assert_not_called()
        pub.assert_not_called()

    def test_focus_falls_back_when_hyprctl_says_it_failed_with_exit_0(self):
        S = self.server
        bad, ok = mock.Mock(returncode=0, stdout=b"warning: nope\n"), mock.Mock(returncode=0, stdout=b"ok\n")
        with mock.patch.object(S, "_run", side_effect=[bad, ok]) as run:
            S._focus("0xabc")
        self.assertIn('hl.dsp.focus({ window = "address:0xabc" })', run.call_args_list[0].args[0])
        self.assertEqual(run.call_args_list[1].args[0][:3], ["hyprctl", "dispatch", "focuswindow"])
        with mock.patch.object(S, "_run", return_value=ok) as run:
            S._focus("0xabc")
        run.assert_called_once()

    def test_a_native_app_with_a_dotted_name_still_follows_up(self):
        S = self.server
        row = {"key": "d1", "app": "org.foo.Bar", "source": "org.foo.Bar", "category": "chat", "summary": "", "body": ""}
        with mock.patch.object(S.Inbox, "want", return_value=True), mock.patch.object(S.Inbox, "call", return_value="[]"), \
             mock.patch.object(S.Inbox, "rows", return_value=[row]), mock.patch.object(S.BUS, "pub"):
            S.Inbox.tick()
        self.assertIn("d1", S.Inbox.origin)

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

    # --- rich cards (#214) ---

    def rich_row(self, **kw):
        return self.row(**{"actions": [{"id": "more", "text": "Tell me more"}, {"id": "no", "text": "No"}], **kw})

    def rows(self, *rows, details=True, image=None):
        S = self.server
        S.CFG["notify_details"] = details
        with mock.patch.object(S.Inbox, "call") as call, mock.patch.object(S.NImage, "add", return_value=image) as add:
            out = S.Inbox.rows(json.dumps(list(rows)))
        return out, call, add

    def test_a_card_only_with_an_image_or_buttons(self):
        out, _, _ = self.rows(self.row(rich="<b>hi</b>"))
        self.assertNotIn("card", out[0])
        out, _, _ = self.rows(self.rich_row(rich="<b>hi</b>"))
        card = out[0]["card"]
        self.assertEqual((card["buttons"], card["runs"][0]["t"], card["runs"][0]["b"]), (["Tell me more", "No"], "hi", True))
        self.assertEqual(self.server.Inbox.acts["nabc12"][1], ["more", "no"])
        out, _, add = self.rows(self.row(image="/p.png"), image="abcd")
        self.assertEqual((out[0]["card"]["image"], "rev" in out[0]["card"]), ("abcd", False))
        out, _, _ = self.rows(self.row(image="/p.png"))              # NImage said no: today's row
        self.assertNotIn("card", out[0])

    def test_the_gate_sees_everything_and_sends_buttoned_rows_back(self):
        S = self.server
        late = "x" * 130 + " your code is 482910"
        for kw in ({"rich": late}, {"rich": "your code is <b>48</b>2910"}, {"summary": late}):
            out, call, add = self.rows(self.rich_row(image="/p.png", **kw), image="abcd")
            self.assertEqual(out, [])
            call.assert_called_once_with("showKey", "nabc12")
            add.assert_not_called()
            self.assertFalse(S.Inbox.acts)
        out, call, _ = self.rows(self.rich_row(actions=[{"id": "a", "text": "Your code 482910"}]))
        self.assertEqual(out, [])
        out, call, add = self.rows(self.rich_row(image="/p.png"), details=False, image="abcd")
        self.assertEqual((out, call.call_args_list), ([], [mock.call("showKey", "nabc12")]))
        out, call, add = self.rows(self.row(image="/p.png", rich="your code is <b>48</b>2910"), image="abcd")   # image only: shown, empty, no card
        self.assertEqual((out[0]["summary"], "card" in out[0]), ("", False))
        call.assert_not_called()
        add.assert_not_called()

    def test_the_image_is_read_after_the_gate(self):
        order = []
        S = self.server
        S.CFG["notify_details"] = True
        with mock.patch.object(S.Inbox, "runs", side_effect=lambda r: order.append("runs") or []), \
             mock.patch.object(S.NImage, "add", side_effect=lambda p: order.append("image") or None):
            S.Inbox.rows(json.dumps([self.row(image="/p.png")]))
        self.assertEqual(order, ["runs", "image"])

    def test_acts_hold_no_text_are_capped_replaced_and_expire(self):
        S = self.server
        rows = [self.rich_row(key=f"k{i}", summary="Secretish name") for i in range(66)]
        out, _, _ = self.rows(*rows)
        self.assertEqual(len(S.Inbox.acts), 64)
        self.assertNotIn("k0", S.Inbox.acts)
        self.assertTrue(all("Secretish" not in repr(v) and "Tell me more" not in repr(v) for v in S.Inbox.acts.values()))
        old = S.Inbox.acts["k65"][0]
        self.rows(self.rich_row(key="k65"))
        self.assertNotEqual(S.Inbox.acts["k65"][0], old)
        self.rows(self.row(key="k65"))                                  # an update with no buttons drops them
        self.assertNotIn("k65", S.Inbox.acts)
        with mock.patch.object(S.Inbox, "want", return_value=False), mock.patch.object(S.Inbox, "call"), mock.patch.object(S.time, "monotonic", return_value=time.monotonic() + 31):
            S.Inbox.tick()
        self.assertFalse(S.Inbox.acts)

    def test_action_route_takes_a_real_index_and_a_live_rev_once(self):
        S = self.server
        with mock.patch.object(S.Inbox, "call", return_value="ok") as call:
            S.Inbox.acts["nabc12"] = ("r1", ["more", "no"], time.monotonic())
            for bad in (True, "0", -1, 3, None, 1.0):
                self.assertEqual(self.post(how="action", i=bad, rev="r1"), ({"error": "bad request"}, 400), bad)
            self.assertEqual(self.post(how="action", i=0, rev="stale"), ({"ok": False},))
            self.assertEqual(self.post(how="action", i=2, rev="r1"), ({"ok": False},))
            self.assertIn("nabc12", S.Inbox.acts)
            self.assertEqual(self.post(how="action", i=1, rev="r1"), ({"ok": True},))
            self.assertEqual(self.post(how="action", i=1, rev="r1"), ({"ok": False},))
            call.assert_called_once_with("invokeKey", "nabc12", "no")
            S.Inbox.acts["nabc12"] = ("r2", ["more"], time.monotonic())
            self.post(how="dismiss")
            self.assertFalse(S.Inbox.acts)
            S.Inbox.acts["nabc12"] = ("r3", ["more"], time.monotonic())
            self.post(how="open")
            self.assertFalse(S.Inbox.acts)

    def test_delegate_rich_falls_back_to_delegate(self):
        S = self.server
        calls = self.shell(lambda m, a: "[]" if m == "delegate" else "ok" if m == "ping" else None)
        with mock.patch.object(S.BUS, "subs", [object()]), mock.patch.object(S.Wake, "asleep", False), mock.patch.object(S.Desk, "fullscreen", False):
            S.Inbox.tick()
            S.Inbox.tick()
        self.assertEqual([m for m, _ in calls if m != "ping"], ["delegateRich", "delegate", "delegate"])
        self.assertTrue(S.Inbox.wanted)

    def test_a_300kb_reply_is_accepted(self):
        S = self.server
        big = json.dumps([self.row(key=f"k{i}", body="b" * 1600) for i in range(32)])
        self.assertGreater(len(big), 50 * 1024)
        self.shell(lambda m, a: big if m == "delegateRich" else "ok")
        self.assertEqual(len(S.Inbox.rows(S.Inbox.call("delegateRich", "5000"))), 32)

    def runs(self, rich):
        return self.server.Inbox.runs(rich)

    def test_runs_allowed_tags(self):
        r = self.runs('a <b>b</b><strong>s</strong><i>i</i><u>u</u><s>x</s>y<br/>z <a href="https://Ex.com/p?q=1&amp;r">l</a> m<br>n')
        self.assertEqual([(x["t"], x["b"], x["i"], x["u"], x["host"]) for x in r],
                         [("a ", 0, 0, 0, ""), ("b", 1, 0, 0, ""), ("s", 1, 0, 0, ""), ("i", 0, 1, 0, ""), ("u", 0, 0, 1, ""), ("x", 0, 0, 0, ""),
                          ("y", 0, 0, 0, ""), ("\n", 0, 0, 0, ""), ("z ", 0, 0, 0, ""), ("l", 0, 0, 0, "ex.com"), (" m", 0, 0, 0, ""),
                          ("\n", 0, 0, 0, ""), ("n", 0, 0, 0, "")])
        self.assertEqual(self.runs('<a href="mailto:me@x.org?subject=1">m</a>')[0]["host"], "x.org")
        self.assertEqual(self.runs('<a href="ftp://h/">m</a>')[0]["host"], "")
        self.assertEqual(self.runs('<a href="javascript:alert(1)">m</a>')[0]["host"], "")
        self.assertNotIn("href", json.dumps(self.runs('<a href="https://e.com/secret">m</a>')))

    def test_runs_drop_unknown_tags_and_keep_text(self):
        text = lambda rich: "".join(x["t"] for x in self.runs(rich))
        self.assertEqual(text("a<script>alert(1)</script>b"), "aalert(1)b")
        self.assertEqual(text('a<img src=x onerror=y>b'), "ab")
        self.assertEqual(text('<a onclick="x()">c</a>'), "c")
        self.assertEqual(text('<b onclick="x()">c</b>'), "c")
        self.assertFalse(self.runs('<b onclick="x()">c</b>')[0]["b"])
        self.assertEqual(text('<a href="javascript:x">c</a>'), "c")
        self.assertEqual(self.runs('<a href="javascript:x">c</a>')[0]["host"], "")

    def test_runs_entities_stay_text(self):
        r = self.runs("&lt;b&gt;x&lt;/b&gt; &amp;lt; &quot;q&quot; &#60;")
        self.assertEqual([(x["t"], x["b"]) for x in r], [('<b>x</b> &lt; "q" &#60;', False)])
        self.assertEqual(self.runs("<b>&lt;script&gt;</b>")[0]["t"], "<script>")

    def test_runs_unclosed_stray_and_cut_tags(self):
        self.assertEqual([(x["t"], x["b"]) for x in self.runs("a</b>b</i></a></u>c")], [("a", False), ("b", False), ("c", False)])
        self.assertEqual([x["b"] for x in self.runs("</b><b>x")], [True])
        self.assertEqual([x["t"] for x in self.runs("hello <b")], ["hello "])
        self.assertEqual([x["t"] for x in self.runs('hello <a href="https://e.com')], ["hello "])
        cut = ("x" * 595 + '<a href="https://e.com">y</a>')[:600]
        self.assertEqual("".join(x["t"] for x in self.runs(cut)), "x" * 595)

    def test_runs_limits(self):
        r = self.runs("x" * 700)
        self.assertEqual(sum(len(x["t"]) for x in r), 600)
        r = self.runs("<b>a</b>" * 100)
        self.assertEqual(len(r), 64)
        r = self.runs("a<br/>" * 100)
        self.assertEqual(len(r), 64)
        self.assertEqual(self.runs(None), [])


if __name__ == "__main__":
    unittest.main()
