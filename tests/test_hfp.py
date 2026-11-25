import sys
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from hfp import Hfp


class Variant:
    def __init__(self, value):
        self.value = value

    def unpack(self):
        return self.value


AG = Hfp.ROOT + "/ag0"
CALL = AG + "/call0"
ADDRESS = "AA:BB:CC:DD:EE:FF"


class Bus:
    def __init__(self):
        self.subs = []
        self.methods = []
        self.requests = []
        self.objects = {
            Hfp.ROOT: {AG: {Hfp.AG: {"Address": ADDRESS}, Hfp.TRANSPORT: {"State": "idle"}}},
            AG: {CALL: {Hfp.CALL: {"State": "incoming", "LineIdentification": "withheld", "Name": "Alex"}}},
        }
        self.error = None

    def signal_subscribe(self, *args):
        self.subs.append(args)
        return len(self.subs)

    def signal_unsubscribe(self, ident):
        pass

    def call_sync(self, name, path, interface, method, args, reply_type, flags, timeout, cancellable):
        self.methods.append((path, interface, method))
        self.requests.append((name, path, interface, method, args, timeout))
        if self.error and method in ("Answer", "Hangup", "Dial", "GetManagedObjects"):
            raise self.error
        if method == "GetManagedObjects":
            return Variant((self.objects[path],))
        return Variant(())

    def emit(self, member, path, values):
        interface = ("org.freedesktop.DBus" if member == "NameOwnerChanged" else
                     Hfp.PROPS if member == "PropertiesChanged" else Hfp.OM)
        for sub in self.subs:
            if sub[1:3] == (interface, member):
                sub[6](self, "sender", path, interface, member, Variant(values), None)


class HfpTest(unittest.TestCase):
    def setUp(self):
        self.bus = Bus()
        self.events = []
        gio = SimpleNamespace(DBusCallFlags=SimpleNamespace(NONE=0),
                              DBusSignalFlags=SimpleNamespace(NONE=0),
                              DBusError=SimpleNamespace(get_remote_error=lambda e: getattr(e, "remote", None)))
        self.hfp = Hfp(lambda: self.events.append(True), self.bus, gio,
                       SimpleNamespace(Variant=lambda signature, value: Variant(value)))
        self.assertTrue(self.hfp.connect())

    def test_discovery_both_levels_and_reseed(self):
        self.assertEqual([p for p, _, m in self.bus.methods if m == "GetManagedObjects"], [Hfp.ROOT, AG])
        self.assertEqual(len(self.bus.subs), 4)
        self.assertTrue(all(sub[3] is None for sub in self.bus.subs[:3]))
        self.assertIsNone(self.hfp.calls[CALL]["number"])
        self.assertTrue(self.hfp.any_call())
        self.bus.objects[AG] = {}
        self.bus.emit("NameOwnerChanged", "/org/freedesktop/DBus", (Hfp.NAME, ":old", ":new"))
        self.assertEqual(self.hfp.calls, {})
        self.assertEqual([p for p, _, m in self.bus.methods if m == "GetManagedObjects"],
                         [Hfp.ROOT, AG, Hfp.ROOT, AG])
        self.assertGreaterEqual(len(self.events), 3)

    def test_late_service_owner(self):
        bus = Bus()
        bus.objects.pop(Hfp.ROOT)
        self.hfp.conn = bus
        self.assertTrue(self.hfp.connect())
        bus.objects[Hfp.ROOT] = {AG: {Hfp.AG: {"Address": ADDRESS}}}
        bus.emit("NameOwnerChanged", "/org/freedesktop/DBus", (Hfp.NAME, "", ":new"))
        self.assertIn(CALL, self.hfp.calls)

    def test_removed_call_is_seen_disconnected_before_it_goes(self):
        seen = []
        self.hfp.on_change = lambda: seen.append(self.hfp.calls.get(CALL, {}).get("state"))
        self.bus.emit("InterfacesRemoved", AG, (CALL, [Hfp.CALL]))
        self.assertEqual(seen, ["disconnected", None])
        self.assertNotIn(CALL, self.hfp.calls)

    def test_signals_transport_and_second_call(self):
        self.assertFalse(self.hfp.audio_here(self.hfp.calls[CALL]))
        self.bus.emit("PropertiesChanged", AG, (Hfp.TRANSPORT, {"State": "active"}, []))
        self.bus.emit("PropertiesChanged", CALL, (Hfp.CALL, {"State": "active", "LineIdentification": "123"}, []))
        self.assertTrue(self.hfp.audio_here(self.hfp.calls[CALL]))
        self.assertEqual(self.hfp.calls[CALL]["number"], "123")
        second = AG + "/call1"
        self.bus.emit("InterfacesAdded", AG, (second, {Hfp.CALL: {"State": "waiting"}}))
        self.assertEqual(len(self.hfp.calls_on(AG)), 2)
        self.bus.emit("InterfacesRemoved", AG, (CALL, [Hfp.CALL]))
        self.assertEqual(len(self.hfp.calls_on(AG)), 1)
        self.bus.emit("InterfacesRemoved", Hfp.ROOT, (AG, [Hfp.AG]))
        self.assertFalse(self.hfp.any_call())

    def test_actions_and_error_mapping(self):
        self.assertEqual(self.hfp.answer(CALL), {"ok": True, "error": None})
        self.assertIn((CALL, Hfp.CALL, "Answer"), self.bus.methods)
        self.bus.emit("PropertiesChanged", CALL, (Hfp.CALL, {"State": "active"}, []))
        before = len(self.bus.methods)
        self.assertEqual(self.hfp.answer(CALL)["error"], "InvalidState")
        self.assertEqual(len(self.bus.methods), before)
        self.assertTrue(self.hfp.hangup(CALL)["ok"])
        error = RuntimeError("bad state")
        error.remote = Hfp.NAME + ".Error.InvalidState"
        self.bus.error = error
        self.assertEqual(self.hfp.hangup(CALL)["error"], "InvalidState")
        error.remote = "org.freedesktop.DBus.Error.Failed"
        self.assertEqual(self.hfp.hangup(CALL)["error"], "Failed")
        self.assertFalse(any(m == "Set" for _, _, m in self.bus.methods))

    def test_dial_and_errors(self):
        self.assertEqual(self.hfp.dial(AG, "123456"), {"ok": False, "error": "busy"})
        self.bus.emit("InterfacesRemoved", AG, (CALL, [Hfp.CALL]))
        self.assertEqual(self.hfp.dial("/gone", "123456"), {"ok": False, "error": "gone"})
        self.assertEqual(self.hfp.dial(AG, "123456"), {"ok": True})
        name, path, interface, method, args, timeout = self.bus.requests[-1]
        self.assertEqual((name, path, interface, method, args.unpack(), timeout),
                         (Hfp.NAME, AG, Hfp.AG, "Dial", ("123456",), 10000))
        self.bus.error = TimeoutError()
        self.assertEqual(self.hfp.dial(AG, "123456"), {"ok": False, "error": "unknown"})
        error = RuntimeError()
        error.remote = "org.freedesktop.DBus.Error.NoReply"
        self.bus.error = error
        self.assertEqual(self.hfp.dial(AG, "123456"), {"ok": False, "error": "unknown"})
        error.remote = "org.freedesktop.DBus.Error.Timeout"
        self.assertEqual(self.hfp.dial(AG, "123456"), {"ok": False, "error": "unknown"})
        error.remote = "org.freedesktop.DBus.Error.Failed"
        self.assertEqual(self.hfp.dial(AG, "123456"), {"ok": False, "error": "failed"})

    def test_gateway_list_alias_fallback_and_duplicates(self):
        system = Bus()
        system.objects["/"] = {
            "/org/bluez/hci0/dev_1": {"org.bluez.Device1": {"Address": ADDRESS, "Alias": "Phone"}},
            "/org/bluez/hci0/dev_2": {"org.bluez.Device1": {"Address": "11:22:33:44:55:66", "Alias": "Phone"}},
        }
        self.hfp.sys_conn = system
        self.hfp.gateways["/ag1"] = {"address": "11:22:33:44:55:66"}
        self.assertEqual(self.hfp.gateway_list(), [
            (AG, ADDRESS, "Phone (…E:FF)"),
            ("/ag1", "11:22:33:44:55:66", "Phone (…5:66)"),
        ])
        self.assertEqual(system.requests[-1][:4], ("org.bluez", "/", Hfp.OM, "GetManagedObjects"))
        system.error = RuntimeError()
        self.assertEqual(self.hfp.gateway_list(), [(AG, ADDRESS, ADDRESS),
                                                   ("/ag1", "11:22:33:44:55:66", "11:22:33:44:55:66")])
        system.error = None
        system.objects["/"] = {}
        self.assertEqual(self.hfp.gateway_list()[0], (AG, ADDRESS, ADDRESS))

    def test_gateway_list_gets_system_bus_lazily(self):
        system = Bus()
        system.objects["/"] = {
            "/org/bluez/hci0/dev_1": {"org.bluez.Device1": {"Address": Variant(ADDRESS),
                                                             "Alias": Variant("My phone")}},
        }
        self.hfp.Gio.BusType = SimpleNamespace(SYSTEM=1)
        self.hfp.Gio.bus_get_sync = unittest.mock.Mock(return_value=system)
        self.assertEqual(self.hfp.gateway_list(), [(AG, ADDRESS, "My phone")])
        self.assertEqual(self.hfp.gateway_list(), [(AG, ADDRESS, "My phone")])
        self.hfp.Gio.bus_get_sync.assert_called_once_with(1, None)

    def test_streams_and_wpctl(self):
        fixture = Path(__file__).with_name("fixtures") / "pw-dump-hfp.json"
        dump = fixture.read_text()
        commands = []

        def run(argv, **kwargs):
            commands.append(argv)
            self.assertIs(kwargs["preexec_fn"], __import__("floor").pdeathsig_preexec)
            if argv[0] == "pw-dump":
                return SimpleNamespace(stdout=dump)
            if argv[1] == "get-volume":
                return SimpleNamespace(stdout="Volume: 0.45 [MUTED]" if argv[2] == "42" else "Volume: 0.75")
            return SimpleNamespace(stdout="")

        with patch("hfp.subprocess.run", side_effect=run):
            self.assertEqual(self.hfp.streams(ADDRESS), {"down": 41, "up": 42})
            self.bus.emit("PropertiesChanged", AG, (Hfp.TRANSPORT, {"State": "active"}, []))
            self.bus.emit("PropertiesChanged", CALL, (Hfp.CALL, {"State": "active"}, []))
            self.assertEqual(self.hfp.volume(1)["volume"], 0.75)
            self.assertEqual(self.hfp.volume(-1)["muted"], True)
            self.assertEqual(self.hfp.mute()["muted"], True)
        self.assertIn(["wpctl", "set-volume", "-l", "1.5", "41", "5%+"], commands)
        self.assertIn(["wpctl", "set-volume", "-l", "1.5", "41", "5%-"], commands)
        self.assertIn(["wpctl", "set-mute", "42", "toggle"], commands)
        self.assertFalse(any("SpeakerVolume" in str(c) for c in commands))


class StopTest(unittest.TestCase):
    def test_stop_clears_records(self):
        hfp = Hfp(gio=object(), glib=object())
        hfp.calls = {"/ag/c": {"path": "/ag/c", "ag": "/ag", "state": "active", "number": None, "name": None}}
        hfp.gateways = {"/ag": {"path": "/ag", "address": "A", "transport": "active"}}
        hfp.stop()
        self.assertEqual((hfp.calls, hfp.gateways), ({}, {}))

    def test_stop_during_connect_never_runs_the_loop(self):
        loop = SimpleNamespace(run=unittest.mock.Mock(), quit=unittest.mock.Mock())
        ctx = SimpleNamespace(push_thread_default=lambda: None, pop_thread_default=lambda: None)
        glib = SimpleNamespace(MainContext=SimpleNamespace(new=lambda: ctx),
                               MainLoop=SimpleNamespace(new=lambda c, r: loop))
        hfp = Hfp(gio=object(), glib=glib)
        hfp.connect = lambda: (hfp.stop(), True)[1]     # (Phone off arrives while connecting)
        hfp._run()
        loop.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
