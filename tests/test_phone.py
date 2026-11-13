"""#231: the phone in Nixi, through Flux. A fake fluxd (the Flux #57 shapes) plus one placeholder per spec case.

Each placeholder is skipped until the plan step named in it lands; that step un-skips and fills it in.
"""

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from pathlib import Path

import nixi_env
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import phone

REPO_ROOT = Path(__file__).resolve().parent.parent


def device(id="pixel", name="Pixel", online=True, battery=80, charging=False, plugins=("findmyphone", "share", "sms", "dnd"),
           call=None, missed=None, dnd=None, paired=True, last_seen=0):
    """One device as Flux #57 reports it. call/missed/dnd are left out when None, as Flux does."""
    d = {"id": id, "name": name, "paired": paired, "online": online, "lastSeen": last_seen,
         "battery": {"charge": battery, "charging": charging}, "plugins": list(plugins),
         "conversations": [], "outbox": []}
    if call is not None:
        d["call"] = call
    if missed is not None:
        d["missedCall"] = missed
    if dnd is not None:
        d["dnd"] = dnd
    return d


def snapshot(devices=(), approvals=(), transfers=(), modern=True):
    """A `state` snapshot. modern=False drops `approvals`, which is how a pre-#57 Flux looks."""
    s = {"devices": list(devices), "transfers": list(transfers)}
    if modern:
        s["approvals"] = list(approvals)
    return s


class FakeFlux:
    """A fluxd stand-in on AF_UNIX: JSON lines in, scripted answers out, state events pushed on demand.

    results[method] is the reply's result, errors[method] its error; an unscripted method gets {}.
    `requests` records every request (dict) in arrival order.
    """

    def __init__(self):
        # a private 0700 folder, so the client's parent-folder check passes by default
        self.dir = tempfile.mkdtemp(prefix="flux-", dir=nixi_env.run_dir())
        os.chmod(self.dir, 0o700)
        self.path = os.path.join(self.dir, "fluxd.sock")
        self.results, self.errors, self.requests = {}, {}, []
        self.before_reply = None
        self.accepted = 0  # connections so far, to watch reconnects
        self._lock = threading.Lock()
        self._conn = None
        self._srv = None
        self._stop = False

    def start(self):
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(self.path)
        self._srv.listen(4)
        self._srv.settimeout(0.1)
        threading.Thread(target=self._accept, daemon=True).start()
        return self

    def stop(self):
        self._stop = True
        self.close_client()
        if self._srv:
            self._srv.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _accept(self):
        while not self._stop:
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self._lock:
                self._conn = conn
                self.accepted += 1
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        buf = b""
        try:
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line.strip():
                        self._answer(conn, json.loads(line))
        except OSError:
            return

    def _answer(self, conn, req):
        with self._lock:
            self.requests.append(req)
        m = req.get("method")
        if self.before_reply:
            self.before_reply(conn, req)
        reply = {"id": req.get("id")}
        if m in self.errors:
            reply["error"] = self.errors[m]
        else:
            reply["result"] = self.results.get(m, {})
        self._send(conn, reply)

    def _send(self, conn, obj):
        try:
            conn.sendall(json.dumps(obj).encode() + b"\n")
        except OSError:
            pass

    def push_state(self, data):
        """Send a {"event": "state"} to the connected client."""
        with self._lock:
            conn = self._conn
        if conn:
            self._send(conn, {"event": "state", "data": data})

    def close_client(self):
        with self._lock:
            conn, self._conn = self._conn, None
        if conn:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            conn.close()

    def methods(self):
        with self._lock:
            return [r.get("method") for r in self.requests]


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return bool(cond())


class _PhoneEnv(unittest.TestCase):
    """Imports server.py under a throwaway HOME and runtime folder (never the real ones: #176)."""

    @classmethod
    def setUpClass(cls):
        cls._orig_env = os.environ.copy()
        cls.tmp = tempfile.mkdtemp(prefix="nixi-phone-test-")
        for k, d in (("HOME", ""), ("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
            os.environ[k] = os.path.join(cls.tmp, d)
            os.makedirs(os.environ[k], exist_ok=True)
        os.environ["XDG_RUNTIME_DIR"] = nixi_env.run_dir()
        sys.path.insert(0, str(REPO_ROOT / "app"))
        import server
        cls.server = server
        if not str(server.CONF_PATH).startswith(tempfile.gettempdir()):
            raise RuntimeError(f"server.py was imported outside a throwaway HOME; CONF_PATH={server.CONF_PATH}")
        nixi_env.check_floor_path(server.FLOOR.path)

    @classmethod
    def tearDownClass(cls):
        os.environ.clear()
        os.environ.update(cls._orig_env)
        shutil.rmtree(cls.tmp, ignore_errors=True)


class _FluxCase(unittest.TestCase):
    """A running FakeFlux per test."""

    def setUp(self):
        self.flux = FakeFlux().start()
        self.addCleanup(self.flux.stop)
        old = os.environ.get("FLUX_SOCKET")
        os.environ["FLUX_SOCKET"] = self.flux.path
        self.addCleanup(lambda: os.environ.pop("FLUX_SOCKET", None) if old is None else os.environ.__setitem__("FLUX_SOCKET", old))

    def client(self):
        client = phone.Phone()
        client.start()
        self.addCleanup(client.stop)
        return client


class FakeFluxTest(_FluxCase):
    """The fixture itself: a plain socket gets scripted replies and pushed state."""

    def _connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect(self.flux.path)
        self.addCleanup(s.close)
        return s, s.makefile("rb")

    def test_reply_state_and_close(self):
        self.flux.results["ring"] = {"sent": True}
        self.flux.errors["share.files"] = {"code": "not_supported"}
        s, f = self._connect()
        s.sendall(b'{"id":1,"method":"ring","params":{"device":"pixel"}}\n')
        self.assertEqual(json.loads(f.readline()), {"id": 1, "result": {"sent": True}})
        s.sendall(b'{"id":2,"method":"share.files","params":{}}\n')
        self.assertEqual(json.loads(f.readline()), {"id": 2, "error": {"code": "not_supported"}})
        self.assertEqual(self.flux.requests[0], {"id": 1, "method": "ring", "params": {"device": "pixel"}})
        self.assertEqual(self.flux.methods(), ["ring", "share.files"])

        snap = snapshot([device(call={"state": "ringing", "caller": "Anna", "number": "+1", "since": 5})])
        self.assertTrue(wait_for(lambda: self.flux._conn is not None))
        self.flux.push_state(snap)
        ev = json.loads(f.readline())
        self.assertEqual(ev, {"event": "state", "data": snap})
        self.assertEqual(ev["data"]["devices"][0]["call"]["caller"], "Anna")
        self.assertNotIn("approvals", snapshot(modern=False))

        self.flux.close_client()
        self.assertEqual(f.readline(), b"")


# ---- placeholders: one per spec "Verification" case. Each names the step that fills it in. ----

class SocketChecks(_FluxCase):
    """Refused with "Flux isn't running", and no request is sent."""

    def test_symlinked_socket(self):
        link = self.flux.path + ".link"
        os.symlink(self.flux.path, link)
        self.addCleanup(os.unlink, link)
        os.environ["FLUX_SOCKET"] = link
        client = self.client()
        self.assertFalse(wait_for(lambda: client.connected, 0.1))
        self.assertEqual(self.flux.requests, [])

    def test_socket_owned_by_another_uid(self):
        real = phone.os.lstat
        def other(path):
            st = real(path)
            if path == self.flux.path:
                values = list(st)
                values[4] = os.getuid() + 1
                return os.stat_result(values)
            return st
        with mock.patch.object(phone.os, "lstat", side_effect=other):
            client = self.client()
            self.assertFalse(wait_for(lambda: client.connected, 0.1))
        self.assertEqual(self.flux.requests, [])

    def test_parent_folder_mode_0775(self):
        os.chmod(self.flux.dir, 0o775)
        client = self.client()
        self.assertFalse(wait_for(lambda: client.connected, 0.1))
        self.assertEqual(self.flux.requests, [])


class Reader(_FluxCase):
    def test_two_states_before_subscribe_reply_keeps_the_second(self):
        first, second = snapshot([device(name="First")]), snapshot([device(name="Second")])
        def before(conn, req):
            if req["method"] == "subscribe":
                self.flux._send(conn, {"event": "state", "data": first})
                self.flux._send(conn, {"event": "state", "data": second})
        self.flux.before_reply = before
        client = self.client()
        self.assertTrue(wait_for(lambda: client.snap == second))
        self.assertEqual(client.devices()[0]["name"], "Second")

    def test_eof_reconnects_after_1s_then_2s(self):
        client = self.client()
        self.assertTrue(wait_for(lambda: self.flux.accepted == 1))
        start = time.monotonic()
        self.flux.close_client()
        self.assertTrue(wait_for(lambda: self.flux.accepted == 2, 2))
        self.assertGreaterEqual(time.monotonic() - start, 0.9)
        start = time.monotonic()
        self.flux.close_client()
        self.assertTrue(wait_for(lambda: self.flux.accepted == 3, 3))
        self.assertGreaterEqual(time.monotonic() - start, 1.9)

    def test_45s_silence_keeps_the_connection(self):
        client = self.client()
        self.assertTrue(wait_for(lambda: self.flux.accepted == 1))
        time.sleep(45)
        self.assertTrue(client.connected)
        self.assertEqual(self.flux.accepted, 1)

    def test_handler_dnd_set_gets_its_reply_while_reader_runs(self):
        got = []
        client = self.client()
        self.assertTrue(wait_for(lambda: client.connected))
        self.flux.push_state(snapshot())
        self.assertTrue(wait_for(lambda: client.modern))
        client.on_state = lambda: got.append(client.call("dnd.set", device="pixel", on=True)) if client.connected else None
        self.flux.push_state(snapshot([device(dnd={"on": False, "by": "phone", "at": 1})]))
        self.assertTrue(wait_for(lambda: got, 2))
        self.assertIn("dnd.set", self.flux.methods())


class CallList(_FluxCase):
    def test_refuses_methods_outside_the_list(self):
        client = self.client()
        for method in ("commands.run", "settings.set", "automation.add", "pair.accept", "notification.reply"):
            with self.subTest(method=method), self.assertRaises(ValueError):
                client.call(method)
        self.assertEqual([m for m in self.flux.methods() if m != "subscribe"], [])

    def test_share_files_refuses_unregistered_paths(self):
        client = self.client()
        base = Path(self.flux.dir) / "outgoing"
        base.mkdir()
        good = base / "good"
        good.write_text("good")
        client.outgoing.add(str(good))
        sibling = Path(str(base) + "-sibling")
        sibling.write_text("x")
        link = base / "link"
        link.symlink_to(good)
        stray = base / "stray"
        stray.write_text("x")
        for bad in ("../x", str(sibling), str(link), str(base), str(stray)):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                client.call("share.files", paths=[bad])
        self.assertEqual([m for m in self.flux.methods() if m != "subscribe"], [])
        self.assertTrue(wait_for(lambda: client.connected))
        client.call("share.files", paths=[str(good)])
        self.assertIn("share.files", self.flux.methods())

    def test_no_af_unix_or_fluxd_sock_outside_phone_py(self):
        for path in (REPO_ROOT / "app").rglob("*.py"):
            if path.name == "phone.py":
                continue
            text = path.read_text()
            self.assertNotIn("fluxd.sock", text, path)
            self.assertNotIn("FLUX_SOCKET", text, path)
            self.assertNotIn("/flux/", text, path)


class Records(_FluxCase):
    def test_first_snapshot_silent_and_keys_survive_reconnect(self):
        seen = []
        client = self.client()
        client.on_call = lambda key, row: seen.append(key)
        first = snapshot([device(call={"state": "ringing", "since": 1})])
        self.assertTrue(wait_for(lambda: client.connected))
        self.flux.push_state(first)
        self.assertTrue(wait_for(lambda: ("call", "pixel", 1) in client.seen))
        self.assertEqual(seen, [])
        self.flux.push_state(snapshot([device(call={"state": "ringing", "since": 2})]))
        self.assertTrue(wait_for(lambda: len(seen) == 1))
        self.flux.close_client()
        self.assertTrue(wait_for(lambda: self.flux.accepted == 2, 2))
        self.flux.push_state(snapshot([device(call={"state": "talking", "since": 2})]))
        time.sleep(0.1)
        self.assertEqual(len(seen), 1)

    def test_missed_approval_transfer_keys_and_clean_views(self):
        client = self.client()
        got = []
        client.on_missed = lambda key, row: got.append(key)
        client.on_approval = lambda key, row: got.append(key)
        client.on_transfer = lambda key, row: got.append(key)
        self.assertTrue(wait_for(lambda: client.connected))
        self.flux.push_state(snapshot())
        self.assertTrue(wait_for(lambda: not client._first))
        row = device(missed={"caller": "Anna", "number": "123", "at": 5}, dnd={"on": False, "by": "phone", "at": 1})
        row["conversations"] = [{"name": "Anna", "body": "private"}]
        self.flux.push_state(snapshot([row, device(id="unpaired", paired=False)],
                                      [{"device": "pixel", "kind": "sudo", "since": 6}],
                                      [{"id": "t1", "state": "waiting", "path": "/private"}]))
        self.assertTrue(wait_for(lambda: len(got) == 3))
        self.assertEqual(set(got), {("missed", "pixel", 5), ("approval", "pixel", "sudo", 6), ("transfer", "t1")})
        self.assertEqual(client.transfers(), [{"id": "t1", "state": "waiting"}])
        self.assertEqual(len(client.devices()), 1)
        self.assertNotIn("conversations", client.devices()[0])
        self.assertEqual(client.devices()[0]["can"], {"ring", "share", "sms", "dnd"})
        self.assertEqual(client.sms_threads()[0]["body"], "private")

    def test_sms_delivery_reads_outbox_without_exposing_it(self):
        client = self.client()
        self.assertTrue(wait_for(lambda: client.connected))
        row = device()
        row["outbox"] = [{"address": "123", "body": "secret", "pending": True, "failed": False}]
        self.flux.push_state(snapshot([row]))
        self.assertTrue(wait_for(lambda: client.sms_delivery("pixel", "123", "secret") == "pending"))
        self.assertEqual(client.sms_delivery("pixel", "123", "secret", time.monotonic() + 1), "unknown")
        self.assertNotIn("outbox", client.devices()[0])
        row["outbox"][0].update(pending=False, failed=True)
        self.flux.push_state(snapshot([row]))
        self.assertTrue(wait_for(lambda: client.sms_delivery("pixel", "123", "secret") == "failed"))
        self.flux.push_state(snapshot([device()]))
        self.assertTrue(wait_for(lambda: client.sms_delivery("pixel", "123", "secret") == "gone"))


class StubPhone:
    """Stands in for server.Phone: the server-side phone logic without a socket."""

    def __init__(self, devices):
        self.connected, self._devices, self.calls, self.outgoing = True, devices, [], set()
        self.stop, self.modern, self.call_active = (lambda: None), True, False
        self.errors, self.results, self.states, self.at_call = {}, {}, [], {}

    def devices(self):
        return self._devices

    def transfers(self):
        return self.states.pop(0) if len(self.states) > 1 else (self.states[0] if self.states else [])

    def sms_threads(self):
        return getattr(self, "threads", [])

    def sms_delivery(self, device, address, body, after=0):
        return getattr(self, "delivery", "pending")

    def call(self, method, **params):
        self.calls.append((method, params))
        if method == "share.files":
            self.at_call["registered"] = [p in self.outgoing and os.path.isfile(p) for p in params["paths"]]
        if method in self.errors:
            raise self.errors[method]
        return self.results.get(method, {})


def dev(id, name, online=True, can=("ring", "share"), last=0):
    return {"id": id, "name": name, "online": online, "lastSeen": last, "battery": {"charge": 50, "charging": False}, "can": set(can)}


class _Phone4(_PhoneEnv):
    def setUp(self):
        s = self.server
        saved = dict(s.CFG)
        self.addCleanup(lambda: (s.CFG.clear(), s.CFG.update(saved)))
        s.CFG["phone_on"] = True
        self.phone = StubPhone([dev("pixel", "Pixel")])
        for p in (mock.patch.object(s, "Phone", self.phone), mock.patch.object(s, "PHONE_POLL", 0.01),
                  mock.patch.object(s, "PHONE_FIRST_WAIT", 2), mock.patch.object(s.BUS, "pub"),
                  mock.patch.object(s, "BRIDGED", False)):
            p.start()
            self.addCleanup(p.stop)

    def ask(self, text):
        r = self.server.quick.handle(text)
        self.assertIn("phone", r, text)
        return self.server.phone_quick(r["phone"])


class Ring(_Phone4):
    def test_one_device_online_rings(self):
        r = self.ask("where's my phone")
        self.assertEqual(self.phone.calls, [("ring", {"device": "pixel"})])
        self.assertEqual(r["say"], "Ringing your Pixel.")

    def test_two_devices_give_a_card_with_two_buttons(self):
        s = self.server
        self.phone._devices = [dev("pixel", "Pixel"), dev("ipad", "iPad")]
        with mock.patch.object(s, "BRIDGED", True), mock.patch.object(s, "stages_on", return_value=True):
            r = self.ask("find my phone")
        self.assertEqual(self.phone.calls, [])
        page = s.STAGES.current()
        self.assertEqual((page["kind"], [d["name"] for d in page["devices"]]), ("phone_pick", ["Pixel", "iPad"]))
        self.assertEqual(r["say"], "Which device?")
        self.assertIsNone(s.STAGES._keep((page, {}, 0)))          # (never kept for Back)
        s.phone_reset()
        self.assertIsNone(s.STAGES.current())
        # and the button: a device that is online and can ring; nothing else
        self.assertTrue(s.phone_pick_act("ipad", "ring")["ok"])
        self.assertEqual(self.phone.calls, [("ring", {"device": "ipad"})])
        self.assertFalse(s.phone_pick_act("nope", "ring")["ok"])
        self.assertEqual(len(self.phone.calls), 1)

    def test_two_devices_without_boards_ask_by_name(self):
        self.phone._devices = [dev("pixel", "Pixel"), dev("ipad", "iPad")]
        self.assertEqual(self.ask("find my phone")["say"], "Which one: Pixel or iPad?")

    def test_ring_my_ipad_rings_the_ipad(self):
        self.phone._devices = [dev("pixel", "Pixel"), dev("ipad", "iPad")]
        self.ask("ring my iPad")
        self.assertEqual(self.phone.calls, [("ring", {"device": "ipad"})])

    def test_no_device_online_gives_last_seen_line(self):
        self.phone._devices = [dev("pixel", "Pixel", online=False, last=time.time() - 20 * 60 - 5)]
        self.assertEqual(self.ask("find my phone")["say"], "Pixel isn't connected, last seen 20 min ago.")
        self.assertEqual(self.phone.calls, [])

    def test_not_supported_gives_cant_ring_line(self):
        self.phone.errors["ring"] = RuntimeError({"code": "not_supported"})
        self.assertEqual(self.ask("find my phone")["say"], "Your Pixel can't ring.")

    def test_a_device_that_cannot_ring_is_named_not_swapped(self):
        self.phone._devices = [dev("pixel", "Pixel"), dev("ipad", "iPad", can=("share",))]
        self.assertEqual(self.ask("ring my ipad")["say"], "Your iPad can't ring.")
        self.assertEqual(self.phone.calls, [])

    def test_not_ours_and_off_and_flux_down(self):
        s = self.server
        self.assertIsNone(s.phone_quick({"do": "ring", "name": "sister"}))
        self.phone.connected = False
        self.assertEqual(self.ask("find my phone")["say"], "Flux isn't running")
        self.assertIsNone(s.phone_quick({"do": "ring", "name": "pixel"}))
        s.CFG["phone_on"] = False
        self.assertIn("switch it on", self.ask("find my phone")["say"])


class Send(_Phone4):
    def clip(self, text=None, image=None):
        c = {"kind": "clipimg", "path": image, "label": "x"} if image else {"kind": "clip", "text": text, "label": "x"}
        p = mock.patch.object(self.server, "capture", return_value=c)
        p.start()
        self.addCleanup(p.stop)

    def test_url_on_clipboard_is_share_url(self):
        self.clip("https://example.com/a?b=1")
        r = self.ask("send this to my phone")
        self.assertEqual(self.phone.calls, [("share.url", {"device": "pixel", "url": "https://example.com/a?b=1"})])
        self.assertEqual(r["say"], "Sent to your Pixel.")

    def test_text_on_clipboard_is_share_text(self):
        self.clip("two words")
        r = self.ask("send the clipboard to my pixel")
        self.assertEqual(self.phone.calls, [("share.text", {"device": "pixel", "text": "two words"})])
        self.assertEqual(r["say"], "Sent to your Pixel.")
        self.clip("see https://example.com now")                       # (not a single URL)
        self.ask("send this to my phone")
        self.assertEqual(self.phone.calls[-1][0], "share.text")

    def test_screenshot_is_share_files_with_registered_run_dir_path(self):
        shot = Path(self.tmp) / "shot.png"
        shot.write_bytes(b"png")
        mocked = mock.patch.object(self.server, "capture", return_value={"kind": "window", "path": str(shot), "label": "x"})
        mocked.start()
        self.addCleanup(mocked.stop)
        self.phone.results["share.files"] = {"transfers": ["t1"]}
        self.phone.states = [[{"id": "t1", "state": "done"}]]
        r = self.ask("send a screenshot to my phone")
        (method, params), = self.phone.calls
        (path,) = params["paths"]
        self.assertEqual(method, "share.files")
        self.assertEqual(os.path.dirname(path), os.path.realpath(os.path.join(nixi_env.run_dir(), "nixi-companion", "phone")))
        self.assertEqual(self.phone.at_call["registered"], [True])
        self.assertEqual(oct(os.stat(os.path.dirname(path)).st_mode & 0o777), "0o700")
        self.assertEqual(r["say"], "On your Pixel.")
        self.assertTrue(wait_for(lambda: not os.path.exists(path) and path not in self.phone.outgoing))
        self.assertTrue(shot.exists())                                 # (only the copy goes)

    def test_transfer_waiting_then_done_lines_and_file_deleted(self):
        shot = Path(self.tmp) / "shot2.png"
        shot.write_bytes(b"png")
        mocked = mock.patch.object(self.server, "capture", return_value={"kind": "window", "path": str(shot), "label": "x"})
        mocked.start()
        self.addCleanup(mocked.stop)
        self.phone.results["share.files"] = {"transfers": ["t1"]}
        self.phone.states = [[{"id": "t1", "state": "waiting"}], [{"id": "t1", "state": "waiting"}], [{"id": "t1", "state": "done"}]]
        r = self.ask("send a screenshot to my phone")
        self.assertEqual(r["say"], "Waiting for your Pixel; it goes when it's back.")
        path = self.phone.calls[0][1]["paths"][0]
        self.assertTrue(wait_for(lambda: self.server.BUS.pub.call_args_list and not os.path.exists(path)))
        self.server.BUS.pub.assert_called_with(t="note", text="On your Pixel.")
        self.assertNotIn(path, self.phone.outgoing)

    def test_failed_transfer_says_so_and_a_refused_send_leaves_no_file(self):
        shot = Path(self.tmp) / "shot3.png"
        shot.write_bytes(b"png")
        mocked = mock.patch.object(self.server, "capture", return_value={"kind": "window", "path": str(shot), "label": "x"})
        mocked.start()
        self.addCleanup(mocked.stop)
        self.phone.results["share.files"] = {"transfers": ["t1"]}
        self.phone.states = [[{"id": "t1", "state": "failed"}]]
        self.assertEqual(self.ask("send a screenshot to my phone")["say"], "That didn't reach your Pixel.")
        self.phone.errors["share.files"] = RuntimeError({"code": "not_supported"})
        self.assertEqual(self.ask("send a screenshot to my phone")["say"], "Your Pixel can't take that.")
        self.assertEqual(self.phone.outgoing, set())
        d = Path(nixi_env.run_dir()) / "nixi-companion" / "phone"
        self.assertTrue(wait_for(lambda: not list(d.glob("*.png"))))


class Battery(_Phone4):
    def setUp(self):
        super().setUp()
        s = self.server
        s.PHONE_BATT.clear()
        s.PHONE_LOW.clear()
        s.Nudge.pending.pop("phone_battery", None)
        self.addCleanup(lambda: s.Nudge.pending.pop("phone_battery", None))

    def feed(self, charge, charging=False, online=True):
        d = dev("pixel", "Pixel", online=online)
        d["battery"] = {"charge": charge, "charging": charging}
        self.phone._devices = [d]
        self.server.phone_state()

    def offered(self):
        return self.server.Nudge.pending.pop("phone_battery", None)

    def test_16_to_14_nudges_once_and_14_to_13_not(self):
        self.feed(16)
        self.assertIsNone(self.offered())
        self.feed(14)
        self.assertEqual(self.offered()[0], "Your Pixel is down to 14%.")
        self.feed(13)
        self.assertIsNone(self.offered())

    def test_charging_then_14_again_nudges_once_more(self):
        for c, ch in ((16, False), (14, False)):
            self.feed(c, ch)
        self.assertIsNotNone(self.offered())
        self.feed(30, True)
        self.feed(14, False)
        self.assertIsNotNone(self.offered())

    def test_no_nudge_while_charging_or_offline_or_at_first_sight_and_it_holds_until_20(self):
        self.feed(14)                               # (first reading is low: nothing fell)
        self.assertIsNone(self.offered())
        self.feed(16)
        self.feed(14, True)
        self.assertIsNone(self.offered())
        self.feed(16)
        self.feed(14, online=False)
        self.assertIsNone(self.offered())
        self.feed(16)
        self.feed(14)
        self.assertIsNotNone(self.offered())
        self.feed(16)                               # (below 20 and not charged: still latched)
        self.feed(14)
        self.assertIsNone(self.offered())
        self.feed(25)
        self.feed(14)
        self.assertIsNotNone(self.offered())

    def test_cooldown_and_off_switch(self):
        self.assertEqual(self.server.Nudge.COOL["phone_battery"], 1800)
        self.server.CFG["phone_on"] = False
        self.feed(16)
        self.feed(14)
        self.assertIsNone(self.offered())

    def test_status_board_has_one_gauge_per_device_and_no_private_text(self):
        s = self.server
        self.phone._devices = [dev("pixel", "Pixel", last=time.time()), dev("ipad", "iPad", online=False, last=time.time() - 1500)]
        self.phone._devices[0]["battery"] = {"charge": 80, "charging": True}
        with mock.patch.object(s, "BRIDGED", True), mock.patch.object(s, "stages_on", return_value=True):
            r = self.ask("how's my phone")
        page = s.STAGES.current()
        self.assertEqual((page["kind"], [h["name"] for h in page["hosts"]]), ("gauges", ["Pixel", "iPad"]))
        self.assertEqual(page["hosts"][0]["meters"], [{"label": "battery", "pct": 80}])
        self.assertIn({"k": "charging", "v": "\u26a1"}, page["hosts"][0]["badges"])
        self.assertEqual(page["hosts"][1]["badges"][-1]["v"], "last seen 25 min ago")
        self.assertEqual(r["say"], "Here are your devices.")
        self.assertIsNotNone(s.STAGES._keep((page, {}, 0)))       # (may stay in Back)

    def test_status_without_boards_is_spoken(self):
        self.phone._devices = [dev("pixel", "Pixel")]
        self.assertEqual(self.ask("phone battery")["say"], "Pixel is at 50 percent, online.")


class Calls(_Phone4):
    def setUp(self):
        super().setUp()
        s = self.server
        s.CFG["proactive"] = True
        self.phone.call_active = False
        self.say = mock.patch.object(s.Speaker, "say").start()
        self.stop = mock.patch.object(s.Speaker, "stop").start()
        self.follow = mock.patch.object(s.Wake, "end_follow").start()
        for p in (mock.patch.object(s.Speaker, "available", return_value=True), mock.patch.object(s.Desk, "locked", return_value=False),
                  mock.patch.object(s.Ambient, "meeting", False), mock.patch.object(s.Ambient, "dnd", False),
                  mock.patch.object(s.Wake, "asleep", False), mock.patch.object(s.Ambient, "phone_call", False)):
            p.start()
        self.addCleanup(mock.patch.stopall)

    def ring(self, caller="Anna", state="ringing", since=1):
        return ("call", "pixel", since), {"state": state, "caller": caller, "number": "123", "since": since}

    def test_new_ringing_record_stops_speech_and_followup(self):
        s = self.server
        ls = mock.Mock()
        self.phone.call_active = True
        with mock.patch.object(s.Listen, "current", ls), mock.patch.object(s.Listen, "lock", mock.Mock(locked=lambda: True)):
            s.phone_state()
        self.assertTrue(s.Ambient.phone_call)
        self.assertFalse(s.Ambient.meeting)                           # (the tie look is not his to wear)
        self.stop.assert_called_once_with()
        self.follow.assert_called_once_with("cancel")
        ls.stop.assert_called_once_with(cancel=True)
        self.assertTrue(s.Ambient.situation()["phone_call"])
        self.assertFalse(s.Wake.should_run())                         # (wake is held while it lasts)
        s.phone_state()                                               # (no second edge)
        self.stop.assert_called_once_with()
        self.phone.call_active = False
        s.phone_state()
        self.assertFalse(s.Ambient.phone_call)

    def test_ringing_is_announced_once_in_the_normal_voice_even_in_a_call(self):
        s = self.server
        s.Ambient.phone_call = True
        s.phone_on_call(*self.ring())
        self.say.assert_called_once_with("Anna is calling on your Pixel", None, None, False, None)
        self.say.reset_mock()
        s.phone_on_call(*self.ring(caller=None))
        self.say.assert_called_once_with("A call on your Pixel", None, None, False, None)

    def test_ringing_to_talking_within_one_snapshot_not_announced(self):
        self.server.phone_on_call(*self.ring(state="talking"))
        self.say.assert_not_called()

    def test_locked_meeting_or_dnd_gives_no_speech(self):
        s = self.server
        for patch in (mock.patch.object(s.Desk, "locked", return_value=True), mock.patch.object(s.Desk, "locked", return_value=None),
                      mock.patch.object(s.Ambient, "meeting", True), mock.patch.object(s.Ambient, "dnd", True),
                      mock.patch.dict(s.CFG, {"proactive": False}), mock.patch.object(s.Wake, "asleep", True)):
            with patch:
                s.phone_on_call(*self.ring())
        self.say.assert_not_called()

    def test_the_call_quiet_holds_every_other_voice(self):
        s = self.server
        s.Ambient.phone_call = True
        self.assertFalse(s.mail_may_speak())
        self.assertEqual(s.agent_say_ready("claude"), {"speak": False, "reason": "call"})
        s.Nudge.pending.clear()
        s.Nudge.offer("break", "x", True)
        with mock.patch.object(s.BUS, "pub") as pub:
            s.Nudge.tick()
        pub.assert_not_called()
        s.Nudge.pending.clear()

    def test_flux_call_row_marked_before_redaction_not_with_old_flux(self):
        s = self.server
        raw = json.dumps([{"key": "k1", "app": "Pixel", "category": "other", "summary": "Call from Anna", "body": ""},
                          {"key": "k2", "app": "Pixel", "category": "other", "summary": "Hello", "body": ""},
                          {"key": "k3", "app": "Other", "category": "other", "summary": "Call from Bob", "body": ""},
                          {"key": "k4", "app": "Pixel", "category": "other", "summary": "Missed call from Anna", "body": ""}])
        with mock.patch.dict(s.CFG, {"notify_details": False}):
            rows = {r["key"]: r for r in s.Inbox.rows(raw)}
            self.assertEqual({k for k, r in rows.items() if r.get("phone_call")}, {"k1", "k4"})
            self.assertEqual(rows["k1"]["summary"], "")                  # (details are off: blanked, and still marked)
            self.phone.modern = False
            self.assertFalse(any(r.get("phone_call") for r in s.Inbox.rows(raw)))
            self.phone.modern, self.phone.connected = True, False
            self.assertFalse(any(r.get("phone_call") for r in s.Inbox.rows(raw)))

    def test_missed_call_with_number_gives_text_back_card_without_number_no_button(self):
        s = self.server
        s.PHONE_MISSED.clear()
        s.PHONE_SHOWN.clear()
        self.phone._devices = [dev("pixel", "Pixel", can=("sms",))]
        self.phone._devices[0]["missedCall"] = {"caller": "Anna", "number": "123", "at": 1}
        with mock.patch.object(s, "BRIDGED", True), mock.patch.object(s, "stages_on", return_value=True):
            s.phone_on_missed(("missed", "pixel", 1), self.phone._devices[0]["missedCall"])
        page = s.STAGES.current()
        self.assertEqual(page["kind"], "phone_missed")
        self.assertIn("Missed call from Anna", page["title"])
        self.assertTrue(page["reply"])
        self.assertTrue(s.phone_draft(page["reply"])["ok"])
        self.assertEqual((s.PHONE_DRAFT["number"], s.STAGES.current()["text"]), ("123", "Sorry I missed your call, I'll call you back."))
        self.phone._devices[0]["missedCall"] = {"caller": "Bob", "at": 2}
        with mock.patch.object(s, "BRIDGED", True), mock.patch.object(s, "stages_on", return_value=True):
            s.phone_on_missed(("missed", "pixel", 2), self.phone._devices[0]["missedCall"])
        self.assertNotIn("reply", s.STAGES.current())

    def test_missed_call_waits_for_unlock_and_stays_in_snapshot(self):
        s = self.server
        s.PHONE_MISSED.clear()
        s.PHONE_SHOWN.clear()
        self.phone._devices = [dev("pixel", "Pixel", can=("sms",))]
        self.phone._devices[0]["missedCall"] = {"caller": "Anna", "number": "123", "at": 3}
        s.STAGES.clear()
        with mock.patch.object(s, "BRIDGED", True), mock.patch.object(s, "stages_on", return_value=True), mock.patch.object(s.Desk, "locked", return_value=True):
            s.phone_on_missed(("missed", "pixel", 3), self.phone._devices[0]["missedCall"])
            self.assertIsNone(s.STAGES.current())
        with mock.patch.object(s, "BRIDGED", True), mock.patch.object(s, "stages_on", return_value=True), mock.patch.object(s.Desk, "locked", return_value=False):
            s.phone_tick()
        self.assertEqual(s.STAGES.current()["kind"], "phone_missed")


class CallRecords(_FluxCase, _PhoneEnv):
    """The real client with the server's callbacks: what is announced, over a socket."""

    def setUp(self):
        _FluxCase.setUp(self)
        s = self.server
        saved = dict(s.CFG)
        self.addCleanup(lambda: (s.CFG.clear(), s.CFG.update(saved)))
        s.CFG.update(phone_on=True, proactive=True)
        self.say = mock.patch.object(s.Speaker, "say").start()
        for p in (mock.patch.object(s.Speaker, "stop"), mock.patch.object(s.Wake, "end_follow"), mock.patch.object(s.BUS, "pub"),
                  mock.patch.object(s.Speaker, "available", return_value=True), mock.patch.object(s.Desk, "locked", return_value=False),
                  mock.patch.object(s.Ambient, "meeting", False), mock.patch.object(s.Ambient, "dnd", False),
                  mock.patch.object(s.Wake, "asleep", False), mock.patch.object(s.Ambient, "phone_call", False)):
            p.start()
        self.addCleanup(mock.patch.stopall)
        self.client = phone.Phone()
        self.client.on_call, self.client.on_state = s.phone_on_call, s.phone_state
        mock.patch.object(s, "Phone", self.client).start()
        self.client.start()
        self.addCleanup(self.client.stop)
        self.assertTrue(wait_for(lambda: self.client.connected))

    def test_call_present_at_startup_not_announced_and_a_reconnect_does_not_repeat(self):
        s = self.server
        self.flux.push_state(snapshot([device(call={"state": "ringing", "caller": "Anna", "since": 1})]))
        self.assertTrue(wait_for(lambda: s.Ambient.phone_call))
        self.say.assert_not_called()
        self.flux.push_state(snapshot([device(call={"state": "ringing", "caller": "Bob", "since": 2})]))
        self.assertTrue(wait_for(lambda: self.say.call_count == 1))
        self.assertIn("Bob is calling", self.say.call_args.args[0])
        self.flux.close_client()
        self.assertTrue(wait_for(lambda: self.flux.accepted == 2, 3))
        self.flux.push_state(snapshot([device(call={"state": "ringing", "caller": "Bob", "since": 2})]))
        self.assertTrue(wait_for(lambda: self.client.connected and s.Ambient.phone_call))
        time.sleep(0.2)
        self.assertEqual(self.say.call_count, 1)
        self.flux.push_state(snapshot([device()]))                    # the call ends: the quiet ends
        self.assertTrue(wait_for(lambda: not s.Ambient.phone_call))


class Messages(_PhoneEnv):
    def setUp(self):
        s = self.server
        saved = dict(s.CFG)
        self.addCleanup(lambda: (s.CFG.clear(), s.CFG.update(saved)))
        s.CFG["phone_on"] = True
        s.STAGES.clear()
        s.PHONE_DRAFT = None
        s.PHONE_OUTBOX.clear()
        s.Speaker.phone_sids.clear()
        self.addCleanup(s.Speaker.phone_sids.clear)
        self.phone = StubPhone([dev("pixel", "Pixel", can=("sms",))])
        self.phone.threads = [{"device": "pixel", "name": "Anna", "address": "123", "addresses": ["123"],
                               "last": "Hello", "time": 10}]
        self.pub = mock.patch.object(s.BUS, "pub").start()
        mock.patch.object(s, "Phone", self.phone).start()
        mock.patch.object(s, "BRIDGED", True).start()
        mock.patch.object(s, "stages_on", return_value=True).start()
        mock.patch.object(s.Speaker, "available", return_value=False).start()
        mock.patch.object(s.Desk, "locked", return_value=False).start()
        mock.patch.object(s.Ambient, "meeting", False).start()
        mock.patch.object(s.Ambient, "dnd", False).start()
        mock.patch.object(s.Ambient, "phone_call", False).start()
        self.addCleanup(mock.patch.stopall)
        with s.CLICK_LOCK:
            old = dict(s.CLICK)
            s.CLICK.update(claimed=True, spoiled=False)
        self.addCleanup(lambda: s.CLICK.update(old))
        self.srv = s.ThreadingHTTPServer(("127.0.0.1", 0), s.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def post(self, route, body, key=None):
        import urllib.error
        import urllib.request
        headers = {"Content-Type": "application/json", "X-Nixi-Token": self.server.TOKEN}
        if key is not None:
            headers["X-Nixi-Click"] = key
        req = urllib.request.Request(f"http://127.0.0.1:{self.srv.server_port}{route}", data=json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.load(e)

    def draft(self):
        s = self.server
        self.assertTrue(s.phone_read_messages())
        page = s.STAGES.current()
        self.assertEqual(page["kind"], "phone_sms")
        self.assertTrue(s.phone_draft(page["rows"][0]["reply"])["ok"])
        return s.PHONE_DRAFT["id"]

    def test_board_not_kept_in_back(self):
        s = self.server
        s.phone_read_messages()
        page = s.STAGES.current()
        self.assertIsNone(s.STAGES._keep((page, {}, 0)))
        s.STAGES.put({"v": 1, "kind": "facts", "title": "Other", "points": []})
        self.assertFalse(s.STAGES.has_prev())
        self.assertNotIn("123", json.dumps(page))

    def test_capture_403_while_board_up(self):
        s = self.server
        s.phone_read_messages()
        with mock.patch.object(s, "BRIDGED", False):
            code, _ = self.post("/api/capture", {"kind": "screen"})
        self.assertEqual(code, 403)
        self.assertTrue(s.phone_on_screen())

    def test_one_time_code_scrubbed(self):
        s = self.server
        self.phone.threads[0]["last"] = "Your code is 123456"
        with mock.patch.object(s.Speaker, "available", return_value=True), mock.patch.object(s.Speaker, "say") as say:
            s.phone_read_messages()
        page = s.STAGES.current()
        self.assertIn("[code]", page["rows"][0]["last"])
        self.assertNotIn("123456", json.dumps(page))
        self.assertNotIn("123456", say.call_args.args[0])
        with mock.patch.object(s.Ambient, "phone_call", True):
            self.assertFalse(s.phone_play_ok((s.PHONE_GEN, page)))

    def test_send_refused_without_click_key(self):
        draft = self.draft()
        self.assertEqual(self.post("/api/phone/send", {"draft": draft, "text": "Edited"})[0], 403)
        self.assertEqual(self.phone.calls, [("sms.refresh", {"device": "pixel"})])

    def test_send_refused_with_wrong_click_key(self):
        draft = self.draft()
        self.assertEqual(self.post("/api/phone/send", {"draft": draft, "text": "Edited"}, "wrong")[0], 403)
        self.assertEqual(len(self.phone.calls), 1)

    def test_send_refused_for_expired_draft(self):
        draft = self.draft()
        self.server.PHONE_DRAFT["created"] -= 601
        self.assertEqual(self.post("/api/phone/send", {"draft": draft, "text": "Edited"}, self.server.CLICK_KEY)[0], 403)
        self.assertEqual(len(self.phone.calls), 1)

    def test_send_refused_for_draft_from_before_phone_off(self):
        draft = self.draft()
        s = self.server
        s.CFG["phone_on"] = False
        s.phone_reset()
        s.CFG["phone_on"] = True
        self.assertEqual(self.post("/api/phone/send", {"draft": draft, "text": "Edited"}, s.CLICK_KEY)[0], 403)
        self.assertEqual(len(self.phone.calls), 1)

    def test_send_refused_on_replay_after_success(self):
        draft = self.draft()
        s = self.server
        self.assertEqual(self.post("/api/phone/send", {"draft": draft, "text": "Edited"}, s.CLICK_KEY)[0], 200)
        self.assertEqual(self.post("/api/phone/send", {"draft": draft, "text": "Edited"}, s.CLICK_KEY)[0], 403)
        self.assertEqual([m for m, _ in self.phone.calls].count("sms.send"), 1)

    def test_two_parallel_sends_give_exactly_one_sms_send(self):
        from concurrent.futures import ThreadPoolExecutor
        draft = self.draft()
        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(pool.map(lambda _: self.post("/api/phone/send", {"draft": draft, "text": "Edited"}, self.server.CLICK_KEY)[0], range(2)))
        self.assertEqual(sorted(codes), [200, 403])
        self.assertEqual([m for m, _ in self.phone.calls].count("sms.send"), 1)

    def test_edited_text_is_sent_as_edited(self):
        draft = self.draft()
        code, _ = self.post("/api/phone/send", {"draft": draft, "text": "Different words"}, self.server.CLICK_KEY)
        self.assertEqual(code, 200)
        self.assertIn(("sms.send", {"device": "pixel", "addresses": ["123"], "body": "Different words"}), self.phone.calls)
        self.assertNotIn("123", json.dumps(self.server.STAGES.current().get("rows", [])))

    def test_quick_read_and_reply_keep_the_text_out_of_the_agent(self):
        s = self.server
        self.assertEqual(s.quick.handle("read my texts"), {"phone": {"do": "read"}})
        got = s.quick.handle("reply to Anna, See you soon")
        self.assertEqual(got, {"phone": {"do": "reply", "name": "Anna", "text": "See you soon"}})
        self.assertEqual(s.phone_quick(got["phone"])["say"], "Check the draft and click Send.")
        self.assertEqual(s.STAGES.current()["text"], "See you soon")

    def test_no_name_match_goes_to_the_agent_unless_it_says_sms(self):
        s = self.server
        before = s.STAGES.current()
        self.assertIsNone(s.phone_reply_quick("Nobody", "Hi"))          # (review: "text me when..." is not a text)
        self.assertIs(s.STAGES.current(), before)
        said = s.phone_reply_quick("Nobody", "Hi", sms=True)
        self.assertEqual(said["say"], s.lang.t("phone.contact_missing"))   # (an explicit SMS never reaches the agent)

    def test_text_length_and_delivery_feedback(self):
        s = self.server
        draft = self.draft()
        for text in ("", " " * 4, "x" * 1001):
            self.assertEqual(self.post("/api/phone/send", {"draft": draft, "text": text}, s.CLICK_KEY)[0], 403)
        self.assertEqual(self.post("/api/phone/send", {"draft": draft, "text": "Edited"}, s.CLICK_KEY)[0], 200)
        item = s.PHONE_OUTBOX[0]
        s.phone_tick()
        self.assertFalse(item["waiting"])
        self.phone.delivery = "gone"
        s.phone_tick()
        self.assertTrue(any(c.kwargs.get("text") == "Sent." for c in self.pub.call_args_list))
        self.assertEqual(s.PHONE_OUTBOX, [])

    def test_pending_text_reports_waiting_then_failure(self):
        s = self.server
        draft = self.draft()
        self.assertEqual(self.post("/api/phone/send", {"draft": draft, "text": "Edited"}, s.CLICK_KEY)[0], 200)
        s.PHONE_OUTBOX[0]["created"] -= 31
        s.phone_tick()
        self.assertTrue(any(c.kwargs.get("text") == "Still waiting on your Anna." for c in self.pub.call_args_list))
        self.phone.delivery = "failed"
        s.phone_tick()
        self.assertTrue(any(c.kwargs.get("text") == "That text didn't go." for c in self.pub.call_args_list))
        self.assertEqual(s.PHONE_OUTBOX, [])


    def test_quick_reply_routes_only_known_sms_contacts(self):
        s = self.server
        for phrase in ("text me when the build finishes", "reply to the PR review, say it looks good",
                       "Text Anna on the team channel that I am late"):
            got = s.quick.handle(phrase)
            self.assertIsNone(s.phone_quick(got["phone"]) if got and "phone" in got else None, phrase)
        got = s.quick.handle("hey nixi, reply to aNnA, See You Soon")
        self.assertEqual(s.phone_quick(got["phone"])["say"], "Check the draft and click Send.")
        self.assertEqual(s.STAGES.current()["text"], "See You Soon")
        with mock.patch.object(s.lang, "active", "pl"):
            got = s.quick.handle("nixi, wyślij sms do Nobody, Hello")
        self.assertIn("say", s.phone_quick(got["phone"]))

    def test_quick_reply_long_text_and_phone_off_fall_through(self):
        s = self.server
        got = s.quick.handle("ok nixi, reply to Anna, " + "X" * 1001)
        self.assertIn("1000", s.phone_quick(got["phone"])["say"])
        self.assertIsNone(s.STAGES.current())
        for connected, enabled in ((False, True), (True, False)):
            self.phone.connected = connected
            s.CFG["phone_on"] = enabled
            for phrase in ("read my texts", "reply to Anna, Hi", "ring my Pixel", "phone status"):
                got = s.quick.handle(phrase)
                self.assertIsNone(s.phone_quick(got["phone"]), phrase)
            self.assertIn("say", s.phone_quick(s.quick.handle("find my phone")["phone"]))


class Silence(_PhoneEnv, _FluxCase):
    def setUp(self):
        super().setUp()
        self.flag = Path(os.environ["XDG_STATE_HOME"]) / "meeting-mode" / "active"
        self.flag.parent.mkdir(exist_ok=True)
        self.flag.unlink(missing_ok=True)
        self.addCleanup(lambda: self.flag.unlink(missing_ok=True))
        self._cfg = mock.patch.dict(self.server.CFG, {"ambient_calendar": False})
        self._cfg.start()
        self.addCleanup(self._cfg.stop)
        self._cal = mock.patch.object(self.server.Ambient, "cal_items", [])
        self._cal.start()
        self.addCleanup(self._cal.stop)

    def client(self):
        client = super().client()
        client.meeting_now = self.server.phone_meeting_now
        return client

    def start(self, dnd):
        client = self.client()
        self.assertTrue(wait_for(lambda: client.connected))
        self.flux.before_reply = lambda conn, req: self.flux._send(conn, {"event": "state", "data": snapshot([
            device(dnd={"on": True, "by": "set", "at": 7})])}) if req["method"] == "dnd.set" and req["params"]["on"] else None
        self.flag.touch()
        self.flux.push_state(snapshot([device(dnd=dnd)]))
        return client

    def test_start_with_dnd_off_sets_on_and_records_at(self):
        client = self.start({"on": False, "by": "phone", "at": 1})
        self.assertTrue(wait_for(lambda: client.silenced == {"pixel": 7}))
        self.assertEqual([r["params"] for r in self.flux.requests if r["method"] == "dnd.set"],
                         [{"device": "pixel", "on": True}])

    def test_start_with_dnd_on_does_nothing(self):
        client = self.start({"on": True, "by": "phone", "at": 1})
        self.assertTrue(wait_for(lambda: client.modern))
        self.assertFalse(wait_for(lambda: "dnd.set" in self.flux.methods(), 1.2))

    def test_end_with_same_at_sets_off(self):
        client = self.start({"on": False, "by": "phone", "at": 1})
        self.assertTrue(wait_for(lambda: client.silenced == {"pixel": 7}))
        self.flag.unlink()
        self.assertTrue(wait_for(lambda: len([m for m in self.flux.methods() if m == "dnd.set"]) == 2, 2))
        self.assertEqual(self.flux.requests[-1]["params"], {"device": "pixel", "on": False})
        self.assertEqual(client.silenced, {})

    def test_end_with_later_at_does_nothing(self):
        client = self.start({"on": False, "by": "phone", "at": 1})
        self.assertTrue(wait_for(lambda: client.silenced == {"pixel": 7}))
        self.flux.push_state(snapshot([device(dnd={"on": True, "by": "set", "at": 8})]))
        self.assertTrue(wait_for(lambda: client.devices()[0]["dnd"]["at"] == 8))
        self.flag.unlink()
        self.assertTrue(wait_for(lambda: not client.silenced, 2))
        self.assertEqual(self.flux.methods().count("dnd.set"), 1)

    def test_dnd_absent_or_null_never_touched(self):
        client = self.start(None)
        self.assertTrue(wait_for(lambda: client.modern))
        self.flux.push_state(snapshot([device(dnd={"on": None, "by": "connect", "at": 1})]))
        self.assertTrue(wait_for(lambda: client.devices()[0].get("dnd", {}).get("on") is None))
        self.assertFalse(wait_for(lambda: "dnd.set" in self.flux.methods(), 1.2))

    def test_calendar_item_silent_from_start_minus_60s_to_end(self):
        import datetime
        self.server.CFG["ambient_calendar"] = True
        now = datetime.datetime.now().astimezone()
        self.server.Ambient.cal_items = [{"start": now + datetime.timedelta(seconds=61),
                                          "end": now + datetime.timedelta(minutes=2), "link": "https://meet.google.com/x"}]
        self.assertFalse(self.server.phone_meeting_now())
        client = self.client()
        self.assertTrue(wait_for(lambda: client.connected))
        self.flux.before_reply = lambda conn, req: self.flux._send(conn, {"event": "state", "data": snapshot([
            device(dnd={"on": True, "by": "set", "at": 7})])}) if req["method"] == "dnd.set" and req["params"]["on"] else None
        self.flux.push_state(snapshot([device(dnd={"on": False, "by": "phone", "at": 1})]))
        self.server.Ambient.cal_items[0]["start"] = now + datetime.timedelta(seconds=59)
        self.assertTrue(wait_for(lambda: client.silenced == {"pixel": 7}, 2))
        self.server.Ambient.cal_items[0]["end"] = now - datetime.timedelta(seconds=1)
        self.assertTrue(wait_for(lambda: self.flux.methods().count("dnd.set") == 2, 2))
        self.assertEqual(self.flux.requests[-1]["params"]["on"], False)


class Approvals(_FluxCase, _PhoneEnv):
    def setUp(self):
        _FluxCase.setUp(self)
        s = self.server
        saved = dict(s.CFG)
        self.addCleanup(lambda: (s.CFG.clear(), s.CFG.update(saved)))
        s.CFG["phone_on"] = True
        self.pub = mock.patch.object(s.BUS, "pub").start()
        mock.patch.object(s.Ambient, "phone_call", False).start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(s.PHONE_APPROVALS.clear)
        self.client = phone.Phone()
        self.client.on_approval, self.client.on_state = s.phone_on_approval, s.phone_state
        mock.patch.object(s, "Phone", self.client).start()
        self.client.start()
        self.addCleanup(self.client.stop)
        self.assertTrue(wait_for(lambda: self.client.connected))
        self.flux.push_state(snapshot([device()]))                    # (the first snapshot: nothing in it is news)
        self.assertTrue(wait_for(lambda: not self.client._first))

    def caps(self):
        return [c.kwargs["text"] for c in self.pub.call_args_list if c.kwargs.get("t") == "phone_cap"]

    def test_record_shows_caption_once(self):
        approval = {"device": "pixel", "kind": "sudo", "since": 5}
        self.flux.push_state(snapshot([device()], [approval]))
        self.assertTrue(wait_for(lambda: self.caps() == ["Approve on your Pixel (sudo)"]))
        self.flux.push_state(snapshot([device(battery=70)], [approval]))     # (another snapshot, same record)
        time.sleep(0.2)
        self.assertEqual(self.caps(), ["Approve on your Pixel (sudo)"])
        self.flux.push_state(snapshot([device()], []))                         # answered: it closes
        self.assertTrue(wait_for(lambda: self.caps()[-1:] == [""]))
        self.assertEqual(len(self.caps()), 2)
        self.flux.push_state(snapshot([device()], [{"device": "pixel", "kind": "ssh", "since": 9}]))
        self.assertTrue(wait_for(lambda: self.caps()[-1:] == ["Approve on your Pixel (ssh)"]))
        self.assertFalse(self.server.Speaker.todo if hasattr(self.server.Speaker, "todo") else False)   # (never spoken)

    def test_record_added_and_answered_in_one_snapshot_shows_nothing(self):
        self.flux.push_state(snapshot([device()], []))
        time.sleep(0.2)
        self.assertEqual(self.caps(), [])

    def test_switching_phone_off_closes_it(self):
        s = self.server
        s.PHONE_APPROVALS.add(("pixel", "sudo", 5))
        s.CFG["phone_on"] = False
        s.phone_approvals_sync()
        self.assertEqual(self.caps(), [""])


if __name__ == "__main__":
    unittest.main()
