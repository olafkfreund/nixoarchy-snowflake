"""NotifyWatch against a real, private session bus (#107). Never touches the host's bus."""
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

from test_speakable import _ServerEnv

try:
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
except (ImportError, ValueError):
    gi = None

XML = """<node><interface name='org.freedesktop.Notifications'><method name='Notify'>
<arg type='s' direction='in'/><arg type='u' direction='in'/><arg type='s' direction='in'/><arg type='s' direction='in'/>
<arg type='s' direction='in'/><arg type='as' direction='in'/><arg type='a{sv}' direction='in'/><arg type='i' direction='in'/>
<arg type='u' direction='out'/></method></interface></node>"""
PATH = "/org/freedesktop/Notifications"
BUS = ("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus")


def connect(addr):
    flags = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
    return Gio.DBusConnection.new_for_address_sync(addr, flags, None, None)


def bus_call(conn, method, sig, *args):
    return conn.call_sync(*BUS, method, GLib.Variant(sig, args), None, Gio.DBusCallFlags.NONE, -1, None)


class Fake:
    """A notification server on the private bus: Notify returns 1, 2, 3 ... (or the id it is asked to replace)."""

    def __init__(self, addr, name):
        self.conn, self.name, self.next = connect(addr), name, 0
        self.conn.register_object(PATH, Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], self.call, None, None)
        self.own()

    def call(self, conn, sender, path, iface, method, params, inv):
        replaces = params.get_child_value(1).get_uint32()
        if not replaces:
            self.next += 1
        inv.return_value(GLib.Variant("(u)", (replaces or self.next,)))

    def own(self):
        bus_call(self.conn, "RequestName", "(su)", self.name, 0)

    def release(self):
        bus_call(self.conn, "ReleaseName", "(s)", self.name)


class NotifyWatchBusTest(_ServerEnv):
    def setUp(self):
        if gi is None:
            self.skipTest("PyGObject is missing")
        daemon = shutil.which("dbus-daemon")
        if not daemon:
            self.skipTest("dbus-daemon is missing")
        self.W, self.C = self.server.NotifyWatch, self.server.CodePause
        tmp = tempfile.mkdtemp(prefix="nixi-bus-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        conf = os.path.join(tmp, "bus.conf")      # (our own config: the host may have no /etc/dbus-1/session.conf)
        with open(conf, "w") as f:
            f.write(f"""<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>session</type>
  <listen>unix:dir={tmp}</listen>
  <auth>EXTERNAL</auth>
  <policy context="default">
    <allow send_destination="*" eavesdrop="true"/>
    <allow eavesdrop="true"/>
    <allow own="*"/>
  </policy>
</busconfig>
""")
        self.proc = subprocess.Popen([daemon, f"--config-file={conf}", "--nofork", "--print-address=1"],
                                     stdout=subprocess.PIPE, text=True)
        self.addCleanup(self.proc.wait)
        self.addCleanup(self.proc.kill)
        self.addr = self.proc.stdout.readline().strip()
        self.assertTrue(self.addr, "dbus-daemon printed no address")
        env = mock.patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": self.addr})
        env.start()
        self.addCleanup(env.stop)
        self.loop = GLib.MainLoop()
        threading.Thread(target=self.loop.run, daemon=True).start()
        self.addCleanup(self.loop.quit)
        saved = dict(self.server.CFG)
        self.addCleanup(lambda: (self.server.CFG.clear(), self.server.CFG.update(saved)))
        self.server.CFG["phone_on"] = True
        self.seen = []
        mock.patch.object(self.C, "seen", side_effect=lambda k, **kw: self.seen.append(k)).start()
        self.addCleanup(mock.patch.stopall)
        self.reached, self.took = [], []
        real = self.W.filter.__func__

        def spy(cls, conn, msg, incoming, g):
            if incoming and msg.get_member() == "Notify":
                self.reached.append(msg.get_destination())
            t = time.monotonic()
            try:
                return real(cls, conn, msg, incoming, g)
            finally:
                self.took.append(time.monotonic() - t)
        mock.patch.object(self.W, "filter", classmethod(spy)).start()
        with self.W.lock:
            self.W.mon = self.W.plain = None
            self.W.fails, self.W.retry_at, self.W.logged = 0, 0.0, True
        self.addCleanup(setattr, self.W, "logged", False)
        self.addCleanup(self.W.close)
        self.fake = Fake(self.addr, "org.freedesktop.Notifications")
        self.client = connect(self.addr)
        self.addCleanup(self.client.close_sync, None)

    def notify(self, dest, replaces=0, summary="Your sign-in code", body="482910", actions=()):
        args = GLib.Variant("(susssasa{sv}i)", ("t", replaces, "", summary, body, list(actions), {}, -1))
        return self.client.call_sync(dest, PATH, "org.freedesktop.Notifications", "Notify", args, None,
                                     Gio.DBusCallFlags.NONE, -1, None).get_child_value(0).get_uint32()

    def wait(self, n):
        end = time.monotonic() + 3
        while len(self.seen) < n and time.monotonic() < end:
            time.sleep(0.02)
        time.sleep(0.1)   # a second count would arrive about now
        return self.seen

    def test_code_counts_once_and_an_update_does_not(self):
        self.assertTrue(self.W.connect())
        nid = self.notify("org.freedesktop.Notifications")
        self.assertEqual(len(self.wait(1)), 1)
        self.assertTrue(self.seen[0].endswith(f":{self.fake.conn.get_unique_name()}:{nid}"))
        self.notify("org.freedesktop.Notifications", replaces=nid)
        self.assertEqual(self.wait(2)[1], self.seen[0])   # the same key: CodePause.seen drops it

    def test_other_destination_is_never_read(self):
        other = Fake(self.addr, "org.example.Other")
        self.assertTrue(self.W.connect())
        self.notify("org.example.Other")
        self.notify("org.freedesktop.Notifications")
        self.wait(1)
        self.assertEqual(set(self.reached), {"org.freedesktop.Notifications"})
        self.assertEqual(len(self.seen), 1)
        del other

    def test_owner_change_counts_under_the_new_owner(self):
        self.assertTrue(self.W.connect())
        old = self.W.owner
        self.fake.release()
        second = Fake(self.addr, "org.freedesktop.Notifications")
        end = time.monotonic() + 3
        while not self.W.stale and time.monotonic() < end:
            time.sleep(0.02)
        self.W.tick()
        self.assertNotEqual(self.W.owner, old)
        self.assertEqual(self.W.owner, second.conn.get_unique_name())
        self.notify("org.freedesktop.Notifications")
        self.wait(1)
        self.assertIn(second.conn.get_unique_name(), self.seen[0])

    def test_dropped_connection_reconnects(self):
        self.assertTrue(self.W.connect())
        old = self.W.mon
        old.close_sync(None)
        self.W.tick()
        self.assertIsNotNone(self.W.mon)
        self.assertIsNot(self.W.mon, old)
        self.notify("org.freedesktop.Notifications")
        self.assertEqual(len(self.wait(1)), 1)

    def test_huge_message_is_cheap(self):
        self.assertTrue(self.W.connect())
        self.notify("org.freedesktop.Notifications", summary="Your sign-in code 482910", body="x" * 1_000_000,
                    actions=["a"] * 10_000)
        self.wait(1)
        self.assertEqual(len(self.seen), 1)
        self.assertLess(max(self.took), 0.2)


if __name__ == "__main__":
    unittest.main()
