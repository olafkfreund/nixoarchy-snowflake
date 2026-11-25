import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from pbap import Pbap, _parse, allowed_number


ADDRESS = "AA:BB:CC:DD:EE:FF"
CARD = """BEGIN:VCARD
VERSION:3.0
FN:Ánna Smith
TEL;TYPE=CELL:tel:+47 912‐34 567
TEL;TYPE=HOME:12345
END:VCARD
BEGIN:VCARD
N:Jones;Bob;;;
TEL;TYPE=WORK:+4798765432
TEL:123,456
END:VCARD
"""


class Variant:
    def __init__(self, signature, value=None):
        self.value = signature if value is None else value

    def unpack(self):
        return self.value


class Bus:
    def __init__(self, mode="complete", error=None):
        self.mode, self.error = mode, error
        self.sub = None
        self.calls = []
        self.directory = None

    def signal_subscribe(self, *args):
        self.sub = args
        return 1

    def signal_unsubscribe(self, ident):
        self.sub = None

    def call_sync(self, name, path, interface, method, args, reply, flags, timeout, cancel):
        self.calls.append(method)
        if self.error and method == self.error[0]:
            error = RuntimeError("synthetic")
            error.remote = self.error[1]
            raise error
        if method == "CreateSession":
            return Variant(("/session",))
        if method == "PullAll":
            file = Path(args.unpack()[0])
            self.directory = file.parent
            file.write_text(CARD)
            if self.mode == "later":
                threading.Timer(0.01, self.emit).start()
            if self.mode == "early":
                self.emit()
            return Variant(("/transfer", {"Status": Variant(self.mode if self.mode in ("complete", "error") else "queued")}))
        return Variant(())

    def emit(self):
        while self.sub is None:
            time.sleep(0.001)
        self.sub[6](self, "sender", "/transfer", Pbap.PROPS, "PropertiesChanged",
                    Variant((Pbap.TRANSFER, {"Status": Variant("complete")}, [])), None)


def pbap(bus):
    gio = SimpleNamespace(DBusCallFlags=SimpleNamespace(NONE=0), DBusSignalFlags=SimpleNamespace(NONE=0),
                          DBusError=SimpleNamespace(get_remote_error=lambda e: getattr(e, "remote", None)))
    glib = SimpleNamespace(Variant=Variant)
    return Pbap(bus, gio, glib)


class PbapTest(unittest.TestCase):
    def setUp(self):
        self.runtime = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.runtime.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.runtime.cleanup)

    def test_allowed_numbers(self):
        for raw, expected in (("+4791234567", ("ok", "+4791234567")),
                              ("112", ("short", None)), ("12345", ("short", None)),
                              ("*#06#", ("not_allowed", None)), ("123,45", ("not_allowed", None)),
                              ("0123p4", ("not_allowed", None)),
                              ("tel:+47 912-34 567", ("ok", "+4791234567")),
                              ("tel:+47 912‐34 567", ("ok", "+4791234567"))):
            self.assertEqual(allowed_number(raw), expected)

    def test_parse_search_and_names(self):
        people = _parse(CARD)
        self.assertEqual([p["name"] for p in people], ["Ánna Smith", "Bob Jones"])
        self.assertEqual([n["label"] for n in people[0]["numbers"]], ["mobile", "home"])
        self.assertEqual([n["dialable"] for n in people[0]["numbers"]], [True, False])
        self.assertEqual(people[0]["numbers"][0]["key"], "+4791234567")
        self.assertFalse(people[1]["numbers"][1]["dialable"])
        p = pbap(Bus())
        p.entries[ADDRESS] = ("ready", time.monotonic(), people)
        self.assertEqual(p.search(ADDRESS, "anna"), [{"name": "Ánna Smith", "numbers": [("mobile", "+4791234567")]}])
        self.assertEqual(p.name_for(ADDRESS, "+4791234567"), ("Ánna Smith", "mobile"))
        self.assertEqual(p.name_for(ADDRESS, "991234567"), ("Ánna Smith", "mobile"))
        self.assertEqual(p.name_for(ADDRESS, "00000000"), None)
        collision = {"name": "Other", "numbers": [{"label": "work", "number": "0091234567",
                                                 "key": "0091234567", "dialable": True}]}
        p.entries[ADDRESS] = ("ready", time.monotonic(), people + [collision])
        self.assertIsNone(p.name_for(ADDRESS, "991234567"))
        p.entries[ADDRESS] = ("ready", time.monotonic(), people + [people[0]])   # saved twice: still one person
        self.assertEqual(p.name_for(ADDRESS, "+4791234567"), ("Ánna Smith", "mobile"))
        self.assertEqual(p.name_for(ADDRESS, "991234567"), ("Ánna Smith", "mobile"))
        twin = {"name": "Someone Else", "numbers": [dict(people[0]["numbers"][0])]}
        p.entries[ADDRESS] = ("ready", time.monotonic(), people + [twin])         # two people, one number: no name
        self.assertIsNone(p.name_for(ADDRESS, "+4791234567"))

    def test_search_order_and_limit(self):
        names = ["Jo", "Joanna", "Mary Jo", "Banjo", "Jó Doe"] + [f"Jo {i}" for i in range(10)]
        people = [{"name": name, "numbers": [{"label": "other", "number": "+4791234567", "key": "+4791234567", "dialable": True}]}
                  for name in names]
        p = pbap(Bus())
        p.entries[ADDRESS] = ("ready", time.monotonic(), people)
        result = p.search(ADDRESS, "jo")
        self.assertEqual(len(result), 8)
        self.assertEqual(result[0]["name"], "Jo")
        self.assertIn("Jó Doe", [r["name"] for r in result])
        self.assertNotIn("Banjo", [r["name"] for r in result])

    def test_transfer_terminal_states_and_cleanup(self):
        for mode, expected in (("complete", "ready"), ("later", "ready"), ("early", "ready"),
                               ("error", "failed"), ("timeout", "failed")):
            with self.subTest(mode=mode):
                bus = Bus(mode)
                p = pbap(bus)
                if mode == "timeout":
                    with patch("pbap.threading.Event") as event:
                        event.return_value.wait.return_value = False
                        p._load(ADDRESS, 0)
                else:
                    p._load(ADDRESS, 0)
                self.assertEqual(p.state(ADDRESS), expected)
                self.assertFalse(bus.directory.exists())
                self.assertIn("RemoveSession", bus.calls)
                self.assertEqual("Cancel" in bus.calls, mode == "timeout")
                self.assertIsNone(bus.sub)

    def test_errors_and_backoff(self):
        for method, remote, expected in (("CreateSession", "x.NotAuthorized", "sharing"),
                                         ("CreateSession", "x.Forbidden", "sharing"),
                                         ("CreateSession", "x.Failed", "unreachable"),
                                         ("Select", "x.Failed", "sharing"),
                                         ("PullAll", "x.Failed", "sharing")):
            with self.subTest(method=method, remote=remote):
                bus = Bus(error=(method, remote))
                p = pbap(bus)
                p._load(ADDRESS, 0)
                self.assertEqual(p.state(ADDRESS), expected)
                self.assertFalse(list(Path(self.runtime.name).glob("nixi-pbap-*")))
                p.entries[ADDRESS] = (expected, time.monotonic() - 301, [])
                self.assertEqual(p.state(ADDRESS), "cold")

    def test_expiry_drop_waiters_and_one_worker(self):
        bus = Bus()
        p = pbap(bus)
        p.entries[ADDRESS] = ("ready", time.monotonic() - 601, [])
        self.assertEqual(p.state(ADDRESS), "cold")
        started = threading.Event()
        release = threading.Event()
        original = p._load

        def slow(address, gen):
            started.set()
            release.wait(2)
            original(address, gen)

        p._load = slow
        seen = []
        p.ensure(ADDRESS, lambda state: seen.append((state, p.lock._is_owned())))
        self.assertTrue(started.wait(2))
        p.ensure(ADDRESS, lambda state: seen.append((state, p.lock._is_owned())))
        self.assertEqual(p.state(ADDRESS), "loading")
        self.assertEqual(len(p.waiters[ADDRESS]), 2)
        release.set()
        for _ in range(100):
            if len(seen) == 2:
                break
            time.sleep(0.01)
        self.assertEqual(seen, [("ready", False), ("ready", False)])
        self.assertEqual(bus.calls.count("CreateSession"), 1)
        p.drop(ADDRESS)
        self.assertEqual(p.state(ADDRESS), "cold")

    def test_generation_discards_result(self):
        bus = Bus()
        p = pbap(bus)
        started = threading.Event()
        release = threading.Event()
        original = bus.call_sync

        def slow(*args):
            if args[3] == "PullAll":
                started.set()
                release.wait(2)
            return original(*args)

        bus.call_sync = slow
        worker = threading.Thread(target=p._load, args=(ADDRESS, 0))
        worker.start()
        self.assertTrue(started.wait(2))
        p.drop(ADDRESS)
        release.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(p.state(ADDRESS), "cold")

    def test_waiters_receive_failure_outside_lock(self):
        for mode, expected in (("error", "failed"), ("sharing", "sharing"),
                               ("unreachable", "unreachable")):
            with self.subTest(mode=mode):
                bus = Bus("error") if mode == "error" else Bus(error=(
                    "Select" if mode == "sharing" else "CreateSession", "x.Failed"))
                p = pbap(bus)
                seen = []
                p.waiters[ADDRESS] = [lambda state: seen.append((state, p.lock._is_owned()))]
                p._load(ADDRESS, 0)
                self.assertEqual(seen, [(expected, False)])

    def test_startup_cleanup(self):
        old = Path(self.runtime.name) / "nixi-pbap-old"
        old.mkdir()
        (old / "pb.vcf").write_text(CARD)
        p = pbap(Bus())
        p._thread = SimpleNamespace(is_alive=lambda: True)
        p.start()
        self.assertFalse(old.exists())


if __name__ == "__main__":
    unittest.main()
