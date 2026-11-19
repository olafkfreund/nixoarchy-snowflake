import io
import sys
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from test_speakable import _ServerEnv

NAME = "org.freedesktop.Notifications"
SIG = "susssasa{sv}i"
CALL, RETURN, SIGNAL = 1, 2, 4


class V:
    """A variant fake: strings, children and uint32 only; unpack() and get_strv() must never be used."""

    def __init__(self, s="", kids=(), n=None, num=0, log=None):
        self.s, self.kids, self.n, self.num, self.log = s, list(kids), n, num, log

    def get_string(self):
        return self.s

    def get_uint32(self):
        return self.num

    def n_children(self):
        return len(self.kids) if self.n is None else self.n

    def get_child_value(self, i):
        if self.log is not None:
            self.log.append(i)
        return self.kids[i] if self.n is None else V(f"x{i}")

    def unpack(self):
        raise AssertionError("unpack")

    def get_strv(self):
        raise AssertionError("get_strv")


class Body:
    """The Notify arguments; a read of child 6 (the hints) is recorded."""

    def __init__(self, summary, body, actions):
        self.kids = {3: V(summary), 4: V(body), 5: actions}
        self.reads = []

    def get_child_value(self, i):
        self.reads.append(i)
        return self.kids[i]


def notify(summary="Hi", body="", labels=(), dest=NAME, sig=SIG, sender=":1.5", serial=1, actions=None):
    if actions is None:
        actions = V(kids=[V(x) for pair in labels for x in ("default", pair)])
    msg = mock.Mock()
    msg.get_message_type.return_value = CALL
    msg.get_member.return_value = "Notify"
    msg.get_destination.return_value = dest
    msg.get_sender.return_value = sender
    msg.get_serial.return_value = serial
    msg.get_signature.return_value = sig
    msg.get_body.return_value = Body(summary, body, actions)
    return msg


def reply(to=":1.5", serial=1, nid=7):
    msg = mock.Mock()
    msg.get_message_type.return_value = RETURN
    msg.get_destination.return_value = to
    msg.get_reply_serial.return_value = serial
    msg.get_body.return_value = V(kids=[V(num=nid)])
    return msg


CODE = dict(summary="Your sign-in code", body="<b>482</b>910")


class WatchTestBase(_ServerEnv):
    def setUp(self):
        self.S = self.server
        self.W = self.S.NotifyWatch
        self.C = self.S.CodePause
        patch = mock.patch.dict(sys.modules, {"gi": None, "gi.repository": None})
        patch.start()
        self.addCleanup(patch.stop)
        saved_cfg = dict(self.S.CFG)
        self.addCleanup(lambda: (self.S.CFG.clear(), self.S.CFG.update(saved_cfg)))
        self.S.CFG["phone_on"] = True
        saved = {k: getattr(self.W, k) for k in ("Gio", "GLib", "mon", "plain", "owner", "bus_id", "pending", "stale",
                                                 "fails", "retry_at", "logged", "gen")}
        self.addCleanup(lambda: [setattr(self.W, k, v) for k, v in saved.items()])
        self.W.Gio = SimpleNamespace(DBusMessageType=SimpleNamespace(METHOD_CALL=CALL, METHOD_RETURN=RETURN, SIGNAL=SIGNAL))
        self.W.mon = self.W.plain = None
        self.W.owner, self.W.bus_id, self.W.pending = ":1.9", "B", {}
        self.W.stale, self.W.fails, self.W.retry_at, self.W.logged, self.W.gen = False, 0, 0.0, False, 3
        with self.C.lock:
            self.C.keys.clear()
            self.C.pending = 0
            self.C.last_watch = -1e9
        self.conn = mock.Mock()
        self.conn.get_unique_name.return_value = ":1.99"

    def feed(self, msg, g=3, incoming=True):
        return self.W.filter(self.conn, msg, incoming, g)


class FilterTest(WatchTestBase):
    def at(self, t):
        return mock.patch.object(self.S.time, "monotonic", return_value=t)

    def test_call_then_reply_counts_once_and_update_does_not_recount(self):
        with mock.patch.object(self.C, "seen") as seen:
            self.assertIsNone(self.feed(notify(**CODE)))
            self.assertIsNone(self.feed(reply()))
            seen.assert_called_once_with("B:" + ":1.9" + ":7")
            self.assertIsNone(self.feed(reply()))                    # no pending call any more
            self.assertEqual(seen.call_count, 1)
        self.assertEqual(self.W.pending, {})

    def test_update_with_the_same_id_does_not_raise_pending_again(self):
        self.feed(notify(**CODE))
        self.feed(reply())
        self.feed(notify(serial=2, **CODE))
        self.feed(reply(serial=2))
        self.assertEqual(self.C.pending, 1)

    def test_clean_call_then_code_update_counts_once(self):
        self.feed(notify(summary="Lunch?", body="at 12", serial=1))
        self.feed(reply(serial=1))
        self.feed(notify(serial=2, **CODE))
        self.feed(reply(serial=2))
        self.assertEqual(self.C.pending, 1)

    def test_reply_without_call_does_nothing(self):
        self.feed(reply())
        self.assertEqual(self.C.pending, 0)

    def test_other_bus_id_counts_again(self):
        for bus in ("B", "B2"):
            self.W.bus_id = bus
            self.feed(notify(**CODE))
            self.feed(reply())
        self.assertEqual(self.C.pending, 2)

    def test_a_reply_after_11s_does_not_count(self):
        with self.at(100):
            self.feed(notify(**CODE))
        with self.at(111):
            self.feed(reply())
        self.assertEqual(self.C.pending, 0)

    def test_detection(self):
        long = "Your code is 482910"
        cases = (
            (CODE, True),
            (dict(summary="New mail", body='<a href="https://x/' + "A1b2C3d4" * 20 + '">open</a>'), False),
            (dict(summary="Hi", body="", labels=["482910 verification code"]), True),
            (dict(summary="x", body="password=example"), True),
            (dict(summary="Hello", body="word " * 60 + long), True),
        )
        for kw, hit in cases:
            with self.subTest(kw=kw):
                self.W.pending = {}
                self.feed(notify(**kw))
                self.assertEqual(len(self.W.pending), int(hit))

    def test_bounds(self):
        start = time.perf_counter()
        self.feed(notify(summary="Hi", body="x" * 1_000_000))
        self.assertLess(time.perf_counter() - start, 0.2)
        seen = []
        actions = V(n=10000, log=seen)
        msg = notify(summary="Hi", body="", actions=actions)
        self.feed(msg)
        self.assertLess(max(seen), 64)
        self.assertNotIn(6, msg.get_body.return_value.reads)
        self.assertFalse(self.W.logged)

    def test_text_past_the_slice_limits_is_ignored(self):
        code = " Your code is 482910"
        pad = lambda n: ("word " * n)[:n]                          # spaces, so the padding is no secret-looking token
        cases = (
            dict(summary=pad(16384) + code),
            dict(body=pad(16384) + code),
            dict(labels=[pad(1024) + code]),
        )
        for kw in cases:
            with self.subTest(kw=list(kw)):
                self.W.pending = {}
                self.feed(notify(**kw))
                self.assertEqual(self.W.pending, {})
                kw = {k: [code.strip() + v[0]] if k == "labels" else code.strip() + " " + v for k, v in kw.items()}
                self.feed(notify(**kw))                                # same text with the code first is found
                self.assertEqual(len(self.W.pending), 1)

    def test_a_code_is_found_in_a_late_action_label_and_hints_never_read(self):
        msg = notify(summary="Hi", body="", labels=["a"] * 20 + ["Your code is 482910"])
        self.feed(msg)
        self.assertEqual(len(self.W.pending), 1)
        self.assertEqual(sorted(set(msg.get_body.return_value.reads)), [3, 4, 5])

    def test_pending_is_capped_and_expires(self):
        with self.at(100):
            for i in range(70):
                self.feed(notify(serial=i, **CODE))
        self.assertEqual(len(self.W.pending), 64)
        with self.at(111):
            self.feed(notify(serial=99, **CODE))
        self.assertEqual(list(self.W.pending), [(":1.5", 99)])

    def test_a_hit_from_a_connection_closed_mid_read_is_not_kept(self):
        W = self.W

        class Closing(V):
            def get_string(self):
                W.close()                               # a close() or reconnect while the filter is reading
                return "Your sign-in code"
        msg = notify(**CODE)
        msg.get_body.return_value.kids[3] = Closing()
        self.assertIsNone(self.feed(msg))
        self.assertEqual(self.W.pending, {})

    def test_pass_through_and_drops(self):
        out = notify(**CODE)
        self.assertIs(self.feed(out, incoming=False), out)
        out.get_body.assert_not_called()
        own = reply(to=":1.99")
        self.assertIs(self.feed(own), own)
        self.assertIsNone(self.feed(notify(**CODE)))
        for kw in (dict(sig="s"), dict(dest="org.example.Other")):
            msg = notify(**kw, **CODE)
            self.assertIsNone(self.feed(msg))
            msg.get_body.assert_not_called()
        msg = notify(**CODE)
        self.assertIsNone(self.feed(msg, g=2))
        msg.get_body.assert_not_called()

    def test_call_to_the_owner_is_read(self):
        self.feed(notify(dest=":1.9", **CODE))
        self.assertEqual(len(self.W.pending), 1)

    def test_phone_off_reads_nothing(self):
        self.S.CFG["phone_on"] = False
        msg = notify(**CODE)
        self.assertIsNone(self.feed(msg))
        msg.get_body.assert_not_called()
        self.assertEqual(self.W.pending, {})

    def test_owner_change_marks_stale(self):
        msg = mock.Mock()
        msg.get_message_type.return_value = SIGNAL
        msg.get_member.return_value = "NameOwnerChanged"
        self.assertIsNone(self.feed(msg))
        self.assertTrue(self.W.stale)

    def test_a_failing_read_logs_one_line_without_content(self):
        msg = notify(summary="SECRETSUMMARY", body="")
        msg.get_body.return_value.kids[4] = mock.Mock(get_string=mock.Mock(side_effect=ValueError("SECRETSUMMARY")))
        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err):
            self.assertIsNone(self.feed(msg))
            self.assertIsNone(self.feed(msg))
        self.assertEqual(err.getvalue(), "[nixi] notification watch: ValueError\n")

    def test_seen_gets_only_the_key(self):
        with mock.patch.object(self.C, "seen") as seen:
            self.feed(notify(summary="SECRETSUMMARY your code 482910", body="SECRETBODY"))
            self.feed(reply())
        for call in seen.call_args_list:
            self.assertNotIn("SECRET", repr(call))


class Err(Exception):
    domain, code = "g-io", 24


class FakeConn:
    def __init__(self, bus):
        self.bus, self.closed, self.filters = bus, False, []

    def add_filter(self, f):
        self.filters.append(f)

    def is_closed(self):
        return self.closed

    def get_unique_name(self):
        return ":1.99"

    def close_sync(self, _):
        self.closed = True

    def call_sync(self, dest, path, iface, method, args, *_):
        bus = self.bus
        if bus.fail_at == method:
            err = Err(method)
            err.remote = bus.remote
            raise err
        if method == "BecomeMonitor":
            if bus.on_become:
                bus.on_become(self)
            return None
        if method == "GetNameOwner":
            return V(kids=[V(bus.owners.pop(0) if bus.owners else bus.owner)])
        return V(kids=[V("B")])


class FakeBus:
    def __init__(self):
        self.conns, self.fail_at, self.on_become, self.owners, self.owner = [], None, None, [], ":1.9"
        self.remote = None

    def new(self, *_):
        self.conns.append(FakeConn(self))
        return self.conns[-1]


class LifecycleTest(WatchTestBase):
    def setUp(self):
        super().setUp()
        self.bus = FakeBus()
        self.W.GLib = SimpleNamespace(Variant=lambda fmt, val: (fmt, val), Error=Err)
        self.W.Gio.dbus_address_get_for_bus_sync = lambda *_: "unix:test"
        self.W.Gio.BusType = SimpleNamespace(SESSION=1)
        self.W.Gio.DBusConnectionFlags = SimpleNamespace(AUTHENTICATION_CLIENT=1, MESSAGE_BUS_CONNECTION=2)
        self.W.Gio.DBusCallFlags = SimpleNamespace(NONE=0)
        self.W.Gio.DBusConnection = SimpleNamespace(new_for_address_sync=self.bus.new)
        self.W.Gio.DBusError = SimpleNamespace(get_remote_error=lambda e: getattr(e, "remote", None))
        self.W.thread = None
        patch = mock.patch.object(self.S.time, "monotonic", return_value=1000.0)
        patch.start()
        self.addCleanup(patch.stop)

    def test_phone_off_never_connects_and_phone_on_does(self):
        self.S.CFG["phone_on"] = False
        self.W.tick()
        self.assertEqual(self.bus.conns, [])
        self.S.CFG["phone_on"] = True
        self.W.tick()
        self.assertEqual(len(self.bus.conns), 2)
        self.assertIsNotNone(self.W.mon)

    def test_failures_close_everything_log_once_and_back_off(self):
        for method in ("GetId", "GetNameOwner", "BecomeMonitor"):
            with self.subTest(method=method):
                self.bus.conns.clear()
                self.W.fails, self.W.retry_at, self.W.logged = 0, 0.0, False
                self.bus.fail_at = method
                err = io.StringIO()
                with mock.patch.object(sys, "stderr", err):
                    self.W.tick()
                    self.assertEqual(self.W.retry_at, 1004.0)
                    self.W.retry_at = 0.0
                    self.W.tick()
                    self.assertEqual(self.W.retry_at, 1008.0)
                self.assertTrue(self.bus.conns and all(c.closed for c in self.bus.conns))
                self.assertEqual(err.getvalue(), "[nixi] notification watch: g-io:24\n")
                self.assertIsNone(self.W.mon)

    def test_phone_switched_off_during_connect_closes_the_result(self):
        self.bus.on_become = lambda c: self.S.CFG.__setitem__("phone_on", False)
        self.W.tick()
        self.assertIsNone(self.W.mon)
        self.assertTrue(all(c.closed for c in self.bus.conns))

    def test_owner_change_during_connect_fails(self):
        self.bus.owners = [":1.9", ":1.10"]
        self.assertFalse(self.W.connect())
        self.assertTrue(all(c.closed for c in self.bus.conns))
        self.assertIsNone(self.W.mon)

    def test_a_message_during_setup_counts_under_the_new_owner(self):
        def deliver(mon):
            f = mon.filters[0]
            f(mon, notify(**CODE), True)
            f(mon, reply(), True)
        self.bus.on_become = deliver
        with mock.patch.object(self.C, "seen") as seen:
            self.assertTrue(self.W.connect())
        seen.assert_called_once_with("B::1.9:7")

    def test_reconnects_when_closed_stale_or_owner_changed(self):
        self.W.tick()
        for trigger in (lambda: setattr(self.W.mon, "closed", True), lambda: setattr(self.W, "stale", True),
                        lambda: setattr(self.bus, "owner", ":1.20")):
            with self.subTest():
                first, gen = self.W.mon, self.W.gen
                trigger()
                self.W.tick()
                self.assertIsNot(self.W.mon, first)
                self.assertTrue(first.closed)
                self.assertGreater(self.W.gen, gen)
                self.assertFalse(self.W.stale)
        self.assertEqual(self.W.owner, ":1.20")

    def test_no_notification_server_retries_next_tick_without_growing_the_back_off(self):
        self.bus.fail_at, self.bus.remote = "GetNameOwner", "org.freedesktop.DBus.Error.NameHasNoOwner"
        with mock.patch.object(sys, "stderr", io.StringIO()):
            self.W.tick()
            self.W.tick()
        self.assertEqual((self.W.fails, self.W.retry_at), (0, 1002.0))
        self.bus.fail_at = None
        self.W.retry_at = 0.0
        self.W.tick()
        self.assertIsNotNone(self.W.mon)

    def test_phone_off_resets_the_back_off(self):
        self.W.fails, self.W.retry_at = 5, 5000.0
        self.S.CFG["phone_on"] = False
        self.W.tick()
        self.assertEqual((self.W.fails, self.W.retry_at), (0, 0.0))
        self.S.CFG["phone_on"] = True
        self.W.tick()
        self.assertIsNotNone(self.W.mon)

    def test_no_reconnect_before_the_back_off(self):
        self.W.tick()
        self.W.retry_at = 2000.0
        self.W.mon.closed = True
        self.W.tick()
        self.assertIsNone(self.W.mon)
        self.assertEqual(len(self.bus.conns), 2)


if __name__ == "__main__":
    unittest.main()
