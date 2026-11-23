"""PipeWire's session-bus HFP calls and their PipeWire audio streams."""

import json
import re
import subprocess
import sys
import threading

from floor import pdeathsig_preexec


class Hfp:
    NAME = "org.pipewire.Telephony"
    ROOT = "/org/pipewire/Telephony"
    AG = NAME + ".AudioGateway1"
    TRANSPORT = NAME + ".AudioGatewayTransport1"
    CALL = NAME + ".Call1"
    OM = "org.freedesktop.DBus.ObjectManager"
    PROPS = "org.freedesktop.DBus.Properties"

    def __init__(self, on_change=None, conn=None, gio=None, glib=None):
        self.on_change = on_change
        self.conn, self.Gio, self.GLib = conn, gio, glib
        self.gateways = {}
        self.calls = {}
        self.lock = threading.RLock()
        self.logged = False
        self._subscriptions = []
        self._thread = self._loop = None

    def _load(self):
        if self.Gio is None or self.GLib is None:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio, GLib
            self.Gio, self.GLib = Gio, GLib

    def _log(self, error):
        if not self.logged:
            self.logged = True
            print(f"[nixi] HFP: {type(error).__name__}", file=sys.stderr)

    def _call(self, path, interface, method, args=None):
        return self.conn.call_sync(self.NAME, path, interface, method, args, None,
                                   self.Gio.DBusCallFlags.NONE, -1, None)

    def connect(self):
        try:
            self._load()
            if self.conn is None:
                self.conn = self.Gio.bus_get_sync(self.Gio.BusType.SESSION, None)
            for interface, member, sender, callback in (
                (self.OM, "InterfacesAdded", self.NAME, self._signal),
                (self.OM, "InterfacesRemoved", self.NAME, self._signal),
                (self.PROPS, "PropertiesChanged", self.NAME, self._signal),
                ("org.freedesktop.DBus", "NameOwnerChanged", "org.freedesktop.DBus", self._owner_changed),
            ):
                ident = self.conn.signal_subscribe(sender, interface, member, None,
                                                   self.NAME if member == "NameOwnerChanged" else None,
                                                   self.Gio.DBusSignalFlags.NONE, callback, None)
                self._subscriptions.append(ident)
            try:
                self._seed()
            except Exception as error:
                self._log(error)  # PipeWire may acquire its bus name after we start.
            return True
        except Exception as error:
            self._log(error)
            return False

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            self._load()
            context = self.GLib.MainContext.new()
            context.push_thread_default()
            try:
                if self.connect():
                    self._loop = self.GLib.MainLoop.new(context, False)
                    self._loop.run()
            finally:
                context.pop_thread_default()
        except Exception as error:
            self._log(error)

    def stop(self):
        if self._loop:
            self._loop.quit()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join()
        if self.conn:
            for ident in self._subscriptions:
                self.conn.signal_unsubscribe(ident)
        self._subscriptions.clear()

    def _managed(self, path):
        return self._call(path, self.OM, "GetManagedObjects").unpack()[0]

    def _seed(self):
        roots = self._managed(self.ROOT)
        gateways, calls = {}, {}
        for path, interfaces in roots.items():
            if self.AG not in interfaces:
                continue
            props = interfaces[self.AG]
            transport = interfaces.get(self.TRANSPORT, {})
            gateways[path] = {"path": path, "address": self._value(props.get("Address")),
                              "transport": self._value(transport.get("State"))}
            for call_path, call_interfaces in self._managed(path).items():
                if self.CALL in call_interfaces:
                    calls[call_path] = self._record(call_path, call_interfaces[self.CALL])
        with self.lock:
            self.gateways, self.calls = gateways, calls
        self._notify()

    @staticmethod
    def _value(value):
        return value.unpack() if hasattr(value, "unpack") else value

    def _record(self, path, props):
        number = self._value(props.get("LineIdentification"))
        return {"path": path, "ag": path.rsplit("/", 1)[0],
                "state": self._value(props.get("State")),
                "number": None if number == "withheld" else number,
                "name": self._value(props.get("Name"))}

    def _notify(self):
        if self.on_change:
            self.on_change()

    def _owner_changed(self, conn, sender, path, interface, member, parameters, data):
        name, old, new = parameters.unpack()
        if name != self.NAME or old == new:
            return
        with self.lock:
            self.gateways.clear()
            self.calls.clear()
        self._notify()
        if new:
            try:
                self._seed()
            except Exception as error:
                self._log(error)

    def _signal(self, conn, sender, path, interface, member, parameters, data):
        try:
            values = parameters.unpack()
            with self.lock:
                if member == "InterfacesAdded":
                    obj, interfaces = values
                    if self.AG in interfaces:
                        props = interfaces[self.AG]
                        self.gateways[obj] = {"path": obj, "address": self._value(props.get("Address")),
                                              "transport": self._value(interfaces.get(self.TRANSPORT, {}).get("State"))}
                    if self.CALL in interfaces:
                        self.calls[obj] = self._record(obj, interfaces[self.CALL])
                elif member == "InterfacesRemoved":
                    obj, interfaces = values
                    if self.AG in interfaces:
                        self.gateways.pop(obj, None)
                        for call in list(self.calls):
                            if self.calls[call]["ag"] == obj:
                                del self.calls[call]
                    if self.CALL in interfaces:
                        self.calls.pop(obj, None)
                elif member == "PropertiesChanged":
                    changed_interface, props, invalidated = values
                    if changed_interface == self.CALL and path in self.calls:
                        row = self.calls[path]
                        for key, field in (("State", "state"), ("LineIdentification", "number"), ("Name", "name")):
                            if key in props or key in invalidated:
                                value = self._value(props.get(key))
                                row[field] = None if value == "withheld" else value
                    elif changed_interface == self.TRANSPORT and path in self.gateways:
                        if "State" in props or "State" in invalidated:
                            self.gateways[path]["transport"] = self._value(props.get("State"))
                    elif changed_interface == self.AG and path in self.gateways:
                        if "Address" in props or "Address" in invalidated:
                            self.gateways[path]["address"] = self._value(props.get("Address"))
            if member == "InterfacesAdded" and self.AG in interfaces:
                for call_path, call_interfaces in self._managed(obj).items():
                    if self.CALL in call_interfaces:
                        with self.lock:
                            self.calls[call_path] = self._record(call_path, call_interfaces[self.CALL])
            self._notify()
        except Exception as error:
            self._log(error)

    def any_call(self):
        with self.lock:
            return any(c["state"] != "disconnected" for c in self.calls.values())

    def calls_on(self, ag):
        with self.lock:
            return [c.copy() for c in self.calls.values() if c["ag"] == ag and c["state"] != "disconnected"]

    def audio_here(self, call):
        with self.lock:
            return (call["state"] == "active" and
                    self.gateways.get(call["ag"], {}).get("transport") == "active")

    def _action(self, path, method):
        with self.lock:
            row = self.calls.get(path)
            if not row or row["state"] == "disconnected" or (method == "Answer" and row["state"] != "incoming"):
                return {"ok": False, "error": "InvalidState"}
        try:
            self._call(path, self.CALL, method)
            return {"ok": True, "error": None}
        except Exception as error:
            try:
                remote = self.Gio.DBusError.get_remote_error(error)
            except (AttributeError, TypeError):
                remote = None
            return {"ok": False, "error": "InvalidState" if remote and remote.endswith(".InvalidState") else "Failed"}

    def answer(self, path):
        return self._action(path, "Answer")

    def hangup(self, path):
        return self._action(path, "Hangup")

    def streams(self, address):
        dump = subprocess.run(["pw-dump"], check=True, capture_output=True, text=True,
                              preexec_fn=pdeathsig_preexec)
        found = {"down": None, "up": None}
        for item in json.loads(dump.stdout):
            if item.get("type") != "PipeWire:Interface:Node" or type(item.get("id")) is not int:
                continue
            props = item.get("info", {}).get("props", {})
            if (props.get("api.bluez5.address") != address or
                    props.get("api.bluez5.profile") != "headset-audio-gateway"):
                continue
            if props.get("media.class") == "Stream/Output/Audio":
                found["down"] = item["id"]
            elif props.get("media.class") == "Stream/Input/Audio":
                found["up"] = item["id"]
        return found

    def _audio(self, kind, step=None):
        with self.lock:
            call = next((c for c in self.calls.values() if self.audio_here(c)), None)
            address = self.gateways.get(call["ag"], {}).get("address") if call else None
        if not address:
            return {"ok": False, "error": "Failed"}
        try:
            ids = self.streams(address)
            if ids["down"] is None or ids["up"] is None:
                return {"ok": False, "error": "Failed"}
            if kind == "volume":
                if step not in (-1, 1):
                    return {"ok": False, "error": "Failed"}
                argv = ["wpctl", "set-volume", "-l", "1.5", str(ids["down"]), f"5%{'+' if step > 0 else '-'}"]
            else:
                argv = ["wpctl", "set-mute", str(ids["up"]), "toggle"]
            subprocess.run(argv, check=True, capture_output=True, text=True, preexec_fn=pdeathsig_preexec)
            down = subprocess.run(["wpctl", "get-volume", str(ids["down"])], check=True, capture_output=True,
                                  text=True, preexec_fn=pdeathsig_preexec).stdout
            up = subprocess.run(["wpctl", "get-volume", str(ids["up"])], check=True, capture_output=True,
                                text=True, preexec_fn=pdeathsig_preexec).stdout
            match = re.search(r"Volume:\s*([0-9]+(?:\.[0-9]+)?)", down)
            if not match:
                return {"ok": False, "error": "Failed"}
            return {"ok": True, "error": None, "volume": float(match[1]), "muted": "[MUTED]" in up}
        except (OSError, ValueError, subprocess.CalledProcessError):
            return {"ok": False, "error": "Failed"}

    def volume(self, step):
        return self._audio("volume", step)

    def mute(self):
        return self._audio("mute")
