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


class StubPhone:
    """Stands in for server.Phone: the server-side phone logic without a socket."""

    def __init__(self, devices):
        self.connected, self._devices, self.calls, self.outgoing = True, devices, [], set()
        self.stop, self.modern = (lambda: None), True
        self.errors, self.results, self.states, self.at_call = {}, {}, [], {}

    def devices(self):
        return self._devices

    def transfers(self):
        return self.states.pop(0) if len(self.states) > 1 else (self.states[0] if self.states else [])

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


class Battery(unittest.TestCase):
    @unittest.skip("step 5")
    def test_16_to_14_nudges_once_and_14_to_13_not(self): ...

    @unittest.skip("step 5")
    def test_charging_then_14_again_nudges_once_more(self): ...


class Calls(unittest.TestCase):
    @unittest.skip("step 6")
    def test_new_ringing_record_stops_speech_and_followup(self): ...

    @unittest.skip("step 6")
    def test_ringing_to_talking_within_one_snapshot_not_announced(self): ...

    @unittest.skip("step 6")
    def test_call_present_at_startup_not_announced(self): ...

    @unittest.skip("step 6")
    def test_locked_meeting_or_dnd_gives_no_speech(self): ...

    @unittest.skip("step 6")
    def test_flux_call_row_marked_before_redaction_not_with_old_flux(self): ...

    @unittest.skip("step 7")
    def test_missed_call_with_number_gives_text_back_card_without_number_no_button(self): ...

    @unittest.skip("step 6")
    def test_reconnect_during_same_ringing_call_not_announced_again(self): ...


class Messages(unittest.TestCase):
    @unittest.skip("step 7")
    def test_board_not_kept_in_back(self): ...

    @unittest.skip("step 7")
    def test_capture_403_while_board_up(self): ...

    @unittest.skip("step 7")
    def test_one_time_code_scrubbed(self): ...

    @unittest.skip("step 7")
    def test_send_refused_without_click_key(self): ...

    @unittest.skip("step 7")
    def test_send_refused_with_wrong_click_key(self): ...

    @unittest.skip("step 7")
    def test_send_refused_for_expired_draft(self): ...

    @unittest.skip("step 7")
    def test_send_refused_for_draft_from_before_phone_off(self): ...

    @unittest.skip("step 7")
    def test_send_refused_on_replay_after_success(self): ...

    @unittest.skip("step 7")
    def test_two_parallel_sends_give_exactly_one_sms_send(self): ...

    @unittest.skip("step 7")
    def test_edited_text_is_sent_as_edited(self): ...


class Silence(unittest.TestCase):
    @unittest.skip("step 9")
    def test_start_with_dnd_off_sets_on_and_records_at(self): ...

    @unittest.skip("step 9")
    def test_start_with_dnd_on_does_nothing(self): ...

    @unittest.skip("step 9")
    def test_end_with_same_at_sets_off(self): ...

    @unittest.skip("step 9")
    def test_end_with_later_at_does_nothing(self): ...

    @unittest.skip("step 9")
    def test_dnd_absent_or_null_never_touched(self): ...

    @unittest.skip("step 9")
    def test_calendar_item_silent_from_start_minus_60s_to_end(self): ...


class Approvals(unittest.TestCase):
    @unittest.skip("step 10")
    def test_record_shows_caption_once(self): ...

    @unittest.skip("step 10")
    def test_record_added_and_answered_in_one_snapshot_shows_nothing(self): ...


if __name__ == "__main__":
    unittest.main()
