import sys
import unittest
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
        if self.error and method in ("Answer", "Hangup"):
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
        self.hfp = Hfp(lambda: self.events.append(True), self.bus, gio, SimpleNamespace())
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


if __name__ == "__main__":
    unittest.main()
