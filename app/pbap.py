"""In-memory phonebook from the phone's Bluetooth PBAP service."""

import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
import time
import unicodedata


def allowed_number(raw):
    value = re.sub(r"^tel:", "", raw.strip(), flags=re.I)
    if re.search(r"[*#,;pw]", value, flags=re.I):
        return "not_allowed", None
    value = "".join(c for c in value if not (c.isspace() or c in "-‐‑‒–—―.()"))
    if re.fullmatch(r"\+?[0-9]{6,15}", value):
        return "ok", value
    if re.fullmatch(r"\+?[0-9]{1,5}", value):
        return "short", None
    return "not_allowed", None


def _key(number):
    return ("+" if re.sub(r"^tel:", "", number.lstrip(), flags=re.I).lstrip().startswith("+") else "") + "".join(
        c for c in number if c.isdigit())


def _fold(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value).casefold()
                   if not unicodedata.combining(c))


def _unescape(value):
    return re.sub(r"\\([nN,;\\])", lambda m: "\n" if m[1].lower() == "n" else m[1], value)


def _parse(data):
    lines = []
    for line in data.splitlines():
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    people, fields = [], []
    for line in lines:
        if line.upper() == "BEGIN:VCARD":
            fields = []
        elif line.upper() == "END:VCARD":
            fn = next((_unescape(v) for k, v in fields if k.upper().split(";")[0] == "FN"), None)
            if not fn:
                n = next((v for k, v in fields if k.upper().split(";")[0] == "N"), "")
                parts = n.split(";")
                fn = " ".join(_unescape(p) for p in (parts[1:2] + parts[:1]) if p)
            numbers = []
            for key, raw in fields:
                parts = key.upper().split(";")
                if parts[0] != "TEL":
                    continue
                types = set()
                for part in parts[1:]:
                    types.update((part.removeprefix("TYPE=")).split(","))
                label = next((name for typ, name in (("CELL", "mobile"), ("HOME", "home"),
                                                   ("WORK", "work")) if typ in types), "other")
                number = _unescape(raw)
                ok, dial = allowed_number(number)
                numbers.append({"label": label, "number": number, "key": _key(number),
                                "dialable": ok == "ok", "dial": dial})
            if fn and numbers:
                people.append({"name": fn, "numbers": numbers})
        elif ":" in line:
            fields.append(line.split(":", 1))
    return people


class Pbap:
    NAME = "org.bluez.obex"
    CLIENT = "org.bluez.obex.Client1"
    ACCESS = "org.bluez.obex.PhonebookAccess1"
    TRANSFER = "org.bluez.obex.Transfer1"
    PROPS = "org.freedesktop.DBus.Properties"

    def __init__(self, conn=None, gio=None, glib=None):
        self.conn, self.Gio, self.GLib = conn, gio, glib
        self.lock = threading.RLock()
        self.entries = {}
        self.waiters = {}
        self.gens = {}
        self._thread = self._loop = self._context = None
        self._ready = threading.Event()

    def _deps(self):
        if self.Gio is None or self.GLib is None:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio, GLib
            self.Gio, self.GLib = Gio, GLib
        if self.conn is None:
            self.conn = self.Gio.bus_get_sync(self.Gio.BusType.SESSION, None)

    def _run(self):
        try:
            self._deps()
            context = self._context = self.GLib.MainContext.new()
            context.push_thread_default()
            try:
                self._loop = self.GLib.MainLoop.new(context, False)
                self._ready.set()
                self._loop.run()
            finally:
                context.pop_thread_default()
        except Exception as error:
            print(f"[nixi] PBAP: {type(error).__name__}", file=sys.stderr)
            self._ready.set()

    def start(self):
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        for path in Path(runtime).glob("nixi-pbap-*") if runtime else []:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
        if not self._thread or not self._thread.is_alive():
            self._ready.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def _state_locked(self, address):
        entry = self.entries.get(address)
        if not entry:
            return "cold"
        state, stamp, _ = entry
        return state if time.monotonic() - stamp < (600 if state == "ready" else 300) else "cold"

    def state(self, address):
        with self.lock:
            return self._state_locked(address)

    def ensure(self, address, cb):
        with self.lock:
            state = self._state_locked(address)
            if state in ("ready", "sharing", "unreachable", "failed"):
                immediate = True
            else:
                immediate = False
                self.waiters.setdefault(address, []).append(cb)
                if state == "cold":
                    gen = self.gens.get(address, 0)
                    self.entries[address] = ("loading", time.monotonic(), [])
                    threading.Thread(target=self._load, args=(address, gen), daemon=True).start()
        if immediate:
            cb(state)

    def name_for(self, address, number):
        with self.lock:
            if self._state_locked(address) != "ready":
                return None
            people = self.entries[address][2]
            key = _key(number)
            exact = [(p["name"], n["label"]) for p in people for n in p["numbers"]
                     if n["key"] == key]
            exact = list(dict.fromkeys(exact))              # (a contact saved twice is still one person)
            if exact:
                return exact[0] if len(exact) == 1 else None
            if len(key.lstrip("+")) < 8:
                return None
            suffix = [(p["name"], n["label"]) for p in people for n in p["numbers"]
                      if n["key"].endswith(key[-8:])]
            suffix = list(dict.fromkeys(suffix))
            return suffix[0] if len(suffix) == 1 else None

    def search(self, address, query):
        with self.lock:
            if self._state_locked(address) != "ready":
                return []
            people = list(self.entries[address][2])
        q = _fold(query).strip()
        if not q:
            return []
        found = []
        for person in people:
            name = _fold(person["name"])
            rank = 0 if name == q else 1 if any(w.startswith(q) for w in name.split()) else 2 if q in name else 3
            numbers = [(n["label"], n.get("dial") or n["number"]) for n in person["numbers"] if n["dialable"]]   # (the normalised number: what Dial gets)
            if rank < 3 and numbers:
                found.append((rank, {"name": person["name"], "numbers": numbers}))
        return [row for _, row in sorted(found, key=lambda x: x[0])[:8]]

    def drop(self, address=None):
        with self.lock:
            addresses = [address] if address is not None else set(self.gens) | set(self.entries) | set(self.waiters)
            for addr in addresses:
                self.gens[addr] = self.gens.get(addr, 0) + 1
                self.entries.pop(addr, None)
                self.waiters.pop(addr, None)

    @staticmethod
    def _value(value):
        return value.unpack() if hasattr(value, "unpack") else value

    def _call(self, path, interface, method, args):
        return self._value(self.conn.call_sync(self.NAME, path, interface, method, args, None,
                                               self.Gio.DBusCallFlags.NONE, 20000, None))

    def _on_context(self, callback):
        if self._thread is None:
            return callback()  # Synthetic buses can be used without start().
        if not self._ready.wait(5) or self._context is None:
            raise RuntimeError("PBAP context unavailable")
        done = threading.Event()
        cancelled = threading.Event()
        result = {}

        def run(*_):
            if cancelled.is_set():
                return False
            try:
                result["value"] = callback()
            except Exception as error:
                result["error"] = error
            finally:
                done.set()
            return False

        source = self.GLib.idle_source_new()
        source.set_callback(run)
        source.attach(self._context)
        if not done.wait(5):
            cancelled.set()
            source.destroy()
            raise RuntimeError("PBAP context unavailable")
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def _load(self, address, gen):
        session = subscription = directory = None
        status = "failed"
        people = []
        phase = "create"
        try:
            self._deps()
            try:
                session = self._call("/org/bluez/obex", self.CLIENT, "CreateSession",
                                     self.GLib.Variant("(sa{sv})", (address, {"Target": self.GLib.Variant("s", "pbap")})))[0]
            except Exception as error:
                remote = self.Gio.DBusError.get_remote_error(error) or ""
                status = "sharing" if "NotAuthorized" in remote or "Forbidden" in remote else "unreachable"
                return
            try:
                phase = "select"
                self._call(session, self.ACCESS, "Select", self.GLib.Variant("(ss)", ("int", "pb")))
                phase = "setup"                                  # (local trouble from here on is "failed", not "sharing")
                directory = Path(tempfile.mkdtemp(prefix="nixi-pbap-", dir=os.environ["XDG_RUNTIME_DIR"]))
                path = directory / "pb.vcf"
                done = threading.Event()
                guard = threading.Lock()                         # (the GLib thread and this one share `result`)
                result = {"status": None, "path": None, "early": {}}

                def changed(conn, sender, obj, interface, member, params, data):
                    iface, props, _ = self._value(params)
                    if iface == self.TRANSFER and "Status" in props:
                        value = self._value(props["Status"])
                        with guard:
                            if result["path"] is None:
                                result["early"][obj] = value
                            elif obj == result["path"]:
                                result["status"] = value
                                if value in ("complete", "error"):
                                    done.set()

                subscription = self._on_context(lambda: self.conn.signal_subscribe(
                    self.NAME, self.PROPS, "PropertiesChanged", None, None,
                    self.Gio.DBusSignalFlags.NONE, changed, None))
                phase = "pull"
                transfer, props = self._call(session, self.ACCESS, "PullAll",
                                             self.GLib.Variant("(sa{sv})", (str(path), {
                                                 "Format": self.GLib.Variant("s", "vcard30"),
                                                 "Fields": self.GLib.Variant("as", ["FN", "N", "TEL"])})))
                phase = "transfer"
                with guard:
                    result["path"] = transfer
                    initial = self._value(props.get("Status"))
                    if initial in ("complete", "error"):
                        result["status"] = initial
                    elif result["early"].get(transfer) in ("complete", "error"):
                        result["status"] = result["early"][transfer]
                if result["status"] not in ("complete", "error") and not done.wait(20):
                    try:
                        self._call(transfer, self.TRANSFER, "Cancel", None)
                    except Exception:
                        pass
                if result["status"] == "complete":
                    try:
                        people = _parse(path.read_text(errors="replace"))
                        status = "ready"
                    except Exception as error:
                        print(f"[nixi] PBAP: {type(error).__name__}", file=sys.stderr)
                        status = "failed"
            except Exception as error:
                print(f"[nixi] PBAP: {type(error).__name__}", file=sys.stderr)
                status = "sharing" if phase in ("select", "pull") else "failed"   # (setup: our own trouble)
        except Exception as error:
            print(f"[nixi] PBAP: {type(error).__name__}", file=sys.stderr)
        finally:
            if subscription is not None:
                try:
                    self.conn.signal_unsubscribe(subscription)
                except Exception as error:
                    print(f"[nixi] PBAP: {type(error).__name__}", file=sys.stderr)
            if directory is not None:
                try:
                    shutil.rmtree(directory)
                except Exception as error:
                    print(f"[nixi] PBAP: {type(error).__name__}", file=sys.stderr)
            if session is not None:
                try:
                    self._call("/org/bluez/obex", self.CLIENT, "RemoveSession",
                               self.GLib.Variant("(o)", (session,)))
                except Exception as error:
                    print(f"[nixi] PBAP: {type(error).__name__}", file=sys.stderr)
            with self.lock:
                current = self.gens.get(address, 0) == gen
                if current:
                    self.entries[address] = (status, time.monotonic(), people if status == "ready" else [])
                    callbacks = self.waiters.pop(address, [])
                else:
                    callbacks = []
            for cb in callbacks:
                cb(self.state(address))
