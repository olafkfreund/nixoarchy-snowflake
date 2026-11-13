"""The narrow Flux socket client used by Nixi's phone features."""

import concurrent.futures
import json
import os
import socket
import stat
import struct
import sys
import threading
import time


class Phone:
    METHODS = frozenset({"ring", "share.url", "share.text", "share.files", "clipboard.send",
                         "sms.refresh", "sms.send", "dnd.set"})

    def __init__(self):
        self.snap = {}
        self.seen = set()
        self.outgoing = set()
        self.silenced = {}
        self._silence_seen = set()
        self._silence_pending = {}
        self._sms_pending = {}
        self.on_call = self.on_missed = self.on_approval = self.on_transfer = self.on_state = None
        self._lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._socket = None
        self._pending = {}
        self._next_id = 1
        self._version = 0
        self._first = True
        self._connected = False
        self._has_snapshot = False
        self._snap_at = 0.0
        self._error_logged = False
        self._reader_thread = self._worker_thread = None

    @staticmethod
    def _path():
        return (os.environ.get("FLUX_SOCKET") or
                os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}",
                             "flux", "fluxd.sock"))

    @staticmethod
    def _check_path(path):
        sock = os.lstat(path)
        parent = os.stat(os.path.dirname(path))
        if (not stat.S_ISSOCK(sock.st_mode) or sock.st_uid != os.getuid() or
                parent.st_uid != os.getuid() or parent.st_mode & 0o022):
            raise ConnectionError("Flux isn't running")

    def start(self):
        with self._lifecycle_lock:
            if (self._reader_thread and self._reader_thread.is_alive() and
                    self._worker_thread and self._worker_thread.is_alive()):
                return
            self._stop.set()
            self._wake.set()
            for thread in (self._reader_thread, self._worker_thread):
                if thread and thread is not threading.current_thread():
                    thread.join()
            with self._lock:
                self._sms_pending.clear()
            self._stop.clear()
            self._reader_thread = threading.Thread(target=self._reader, daemon=True)
            self._worker_thread = threading.Thread(target=self._worker, daemon=True)
            self._reader_thread.start()
            self._worker_thread.start()

    def stop(self):
        with self._lifecycle_lock:
            self._stop.set()
            self._wake.set()
            with self._lock:
                sock = self._socket
            if sock:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()
            for thread in (self._reader_thread, self._worker_thread):
                if thread and thread is not threading.current_thread():
                    thread.join()
            with self._lock:
                self._sms_pending.clear()

    @property
    def connected(self):
        with self._lock:
            return self._connected

    @property
    def modern(self):
        with self._lock:
            return "approvals" in self.snap

    @property
    def call_active(self):
        with self._lock:
            return "approvals" in self.snap and any(d.get("call") for d in self.snap.get("devices", [])
                                                     if d.get("paired"))

    def devices(self):
        with self._lock:
            rows = self.snap.get("devices", [])
            result = []
            for d in rows:
                if not d.get("paired"):
                    continue
                can = {name for plugin, name in (("findmyphone", "ring"), ("share", "share"),
                                                  ("sms", "sms"), ("dnd", "dnd"))
                       if plugin in d.get("plugins", [])}
                row = {key: d.get(key) for key in ("id", "name", "online", "lastSeen", "battery")}
                row["can"] = can
                if "approvals" in self.snap:
                    for key in ("call", "missedCall", "dnd"):
                        if key in d:
                            row[key] = d[key]
                result.append(row)
            return result

    def approvals(self):
        with self._lock:
            return list(self.snap.get("approvals", []))

    def sms_threads(self):
        with self._lock:
            return [{"device": d.get("id"), **c} for d in self.snap.get("devices", [])
                    if d.get("paired") for c in d.get("conversations", [])]

    def sms_delivery(self, device, address, body, after=0):
        """The delivery state of one sent text; no outbox contents leave this module."""
        with self._lock:
            if not self._connected or self._snap_at <= after:
                return "unknown"
            row = next((d for d in self.snap.get("devices", []) if d.get("id") == device), None)
            if not row or not row.get("paired"):
                return "unknown"
            if "outbox" not in row:
                return "unknown"
            # shortcut: identical texts to one number share a match, until Flux exposes a stable SMS id.
            item = next((m for m in row.get("outbox", [])
                         if m.get("address") == address and m.get("body") == body), None)
            if item and item.get("failed"):
                self._sms_pending.pop((device, address, body), None)
                return "failed"
            if item or self._sms_pending.get((device, address, body), 0) <= after:
                return "pending"
            return "gone"

    def transfers(self):
        with self._lock:
            return [{"id": t.get("id"), "state": t.get("state")}
                    for t in self.snap.get("transfers", [])]

    def call(self, method, **params):
        if method not in self.METHODS:
            raise ValueError("Flux method is not allowed")
        if method == "share.files":
            paths = params.get("paths")
            if not isinstance(paths, list) or not paths:
                raise ValueError("Unregistered outgoing file")
            for path in paths:
                if not isinstance(path, str) or not os.path.isabs(path) or os.path.islink(path):
                    raise ValueError("Unregistered outgoing file")
                real = os.path.realpath(path)
                if (path != real or real not in self.outgoing or
                        not stat.S_ISREG(os.stat(real).st_mode)):
                    raise ValueError("Unregistered outgoing file")
        if threading.current_thread() is self._reader_thread:
            raise RuntimeError("Phone.call cannot run on the reader")
        future = concurrent.futures.Future()
        with self._send_lock:
            with self._lock:
                if not self._connected or not self._socket:
                    raise ConnectionError("Flux isn't running")
                sock = self._socket
                ident = self._next_id
                self._next_id += 1
                self._pending[ident] = future
            try:
                sock.sendall((json.dumps({"id": ident, "method": method, "params": params}) + "\n").encode())
            except OSError as exc:
                with self._lock:
                    self._pending.pop(ident, None)
                raise ConnectionError("Flux isn't running") from exc
        try:
            reply = future.result(timeout=10)
        except concurrent.futures.TimeoutError as exc:
            with self._lock:
                self._pending.pop(ident, None)
            raise TimeoutError("Flux did not reply") from exc
        if "error" in reply:
            raise RuntimeError(reply["error"])
        return reply.get("result")

    def _reader(self):
        delay = 1
        while not self._stop.is_set():
            sock = None
            try:
                path = self._path()
                self._check_path(path)
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(30)
                sock.connect(path)
                uid = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
                if uid != os.getuid():
                    raise ConnectionError("Flux isn't running")
                with self._send_lock:
                    with self._lock:
                        ident = self._next_id
                        self._next_id += 1
                    sock.sendall((json.dumps({"id": ident, "method": "subscribe"}) + "\n").encode())
                with self._lock:
                    self._socket = sock
                    self._snap_at = 0.0
                    self._error_logged = False
                delay = 1
                buf = b""
                while not self._stop.is_set():
                    try:
                        chunk = sock.recv(65536)
                    except socket.timeout:
                        continue  # Flux has no heartbeat.
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if not line:
                            continue
                        msg = json.loads(line)
                        if not isinstance(msg, dict) or ("id" in msg and not isinstance(msg["id"], (str, int))):
                            continue
                        with self._lock:
                            if not self._connected:
                                self._connected = True
                                self._wake.set()
                            if msg.get("event") == "state" and isinstance(msg.get("data"), dict):
                                self.snap = msg["data"]
                                self._has_snapshot = True
                                self._snap_at = time.monotonic()
                                for d in self.snap.get("devices", []):
                                    if not isinstance(d, dict):
                                        continue
                                    for m in d.get("outbox", []):
                                        if isinstance(m, dict) and m.get("pending") and not m.get("failed"):
                                            key = (d.get("id"), m.get("address"), m.get("body"))
                                            if all(isinstance(v, (str, int)) for v in key):
                                                self._sms_pending[key] = self._snap_at
                                self._version += 1
                                self._wake.set()
                            elif "id" in msg:
                                future = self._pending.pop(msg["id"], None)
                                if future:
                                    future.set_result(msg)
            except (OSError, ValueError, ConnectionError):
                pass
            finally:
                with self._lock:
                    if not self._stop.is_set() and not self._error_logged:
                        print("[nixi] Flux isn't running", file=sys.stderr)
                        self._error_logged = True
                    if self._socket is sock:
                        self._socket = None
                    self._connected = False
                    self.snap = {}
                    self._has_snapshot = False
                    self._snap_at = 0.0
                    self._version += 1
                    self._wake.set()
                    for future in self._pending.values():
                        future.set_exception(ConnectionError("Flux isn't running"))
                    self._pending.clear()
                if sock:
                    sock.close()
            if self._stop.wait(delay):
                break
            delay = min(delay * 2, 30)

    @staticmethod
    def _records(snap):
        for d in snap.get("devices", []):
            if not d.get("paired"):
                continue
            ident = d.get("id")
            if "approvals" in snap and d.get("call") and "since" in d["call"]:
                yield ("call", ident, d["call"]["since"]), d["call"]
            if "approvals" in snap and d.get("missedCall") and "at" in d["missedCall"]:
                yield ("missed", ident, d["missedCall"]["at"]), d["missedCall"]
        for a in snap.get("approvals", []):
            if all(k in a for k in ("device", "kind", "since")):
                yield ("approval", a["device"], a["kind"], a["since"]), a
        for t in snap.get("transfers", []):
            if "id" in t:
                yield ("transfer", t["id"]), t

    def meeting_now(self):
        return False  # The server supplies its Meeting Mode and calendar signal.

    def tick(self):
        meeting = self.meeting_now()
        devices = self.devices()
        for d in devices:
            state = d.get("dnd")
            if (d["id"] in self._silence_pending and state and
                    state.get("on") is True and state.get("by") == "set" and state.get("at") is not None):
                self.silenced[d["id"]] = state["at"]
                self._silence_pending.pop(d["id"])
        if not meeting:
            self._silence_seen.clear()
            if not self.connected:
                return
            for d in devices:
                ident = d["id"]
                if ident not in self.silenced or not d["online"]:
                    continue
                state = d.get("dnd")
                if not state:
                    continue
                if state.get("at") != self.silenced[ident]:
                    self.silenced.pop(ident)
                elif state.get("on") is True and state.get("by") == "set":
                    self.call("dnd.set", device=ident, on=False)
                    self.silenced.pop(ident)
            return
        if not self.connected or not self.modern:
            return
        for d in devices:
            state = d.get("dnd")
            if (not d["online"] or "dnd" not in d["can"] or not state or state.get("on") is None or
                    d["id"] in self._silence_seen or d["id"] in self._silence_pending or d["id"] in self.silenced):
                continue
            self._silence_seen.add(d["id"])
            if state.get("on") is not False:
                continue
            self.call("dnd.set", device=d["id"], on=True)
            self._silence_pending[d["id"]] = time.monotonic() + 10

    def _worker(self):
        last = -1
        while not self._stop.is_set():
            self._wake.wait(1)
            self._wake.clear()
            if self._stop.is_set():
                break
            with self._lock:
                version = self._version
                snap = self.snap
                if version != last and self._has_snapshot:
                    records = list(self._records(snap))
                    fresh = [] if self._first else [(key, value) for key, value in records if key not in self.seen]
                    self.seen.update(key for key, _ in records)
                    self._first = False
                else:
                    fresh = []
            if version != last:
                last = version
                if self.on_state:
                    try:
                        self.on_state()
                    except Exception as exc:
                        print(f"[nixi] phone state handler failed: {type(exc).__name__}", file=sys.stderr)
            for key, value in fresh:
                callback = getattr(self, "on_" + key[0])
                if callback:
                    try:
                        callback(key, value)
                    except Exception as exc:
                        print(f"[nixi] phone record handler failed: {type(exc).__name__}", file=sys.stderr)
            try:
                self.tick()
            except Exception as exc:
                print(f"[nixi] phone tick failed: {type(exc).__name__}", file=sys.stderr)
