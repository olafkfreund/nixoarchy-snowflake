"""#209 step 1: local machine edges and the ambient-thread handoff."""
import tempfile
import threading
from pathlib import Path
from unittest import mock

from test_speakable import _ServerEnv


class MachineSensesTest(_ServerEnv):
    def setUp(self):
        S = self.server
        self.A, self.N = S.Ambient, S.Nudge
        saved = dict(S.CFG)
        self.addCleanup(lambda: (S.CFG.clear(), S.CFG.update(saved)))
        S.CFG.update(proactive=True, react_load=True)
        self.A.machine_due = 0
        self.A.failed = {"user": None, "system": None}
        self.A.disk_full = set()
        self.A.off_since = None
        self.A.offline = False
        self.A.peer_last = {}
        self.A.peer_due = 0
        self.A.later = []
        self.N.pending.clear()
        self.proc = Path(tempfile.mkdtemp(dir=self.tmp))
        (self.proc / "net").mkdir()
        self.route("route", "eth0 00000000 00000000 0001\n")
        self.route("ipv6_route", "")
        self.units = {"user": [], "system": []}
        self.disks = {"/": .5, "/nix/store": .5}

        def failed(cmd, out, i):
            scope = "user" if "--user" in cmd else "system"
            result = self.units[scope]
            out[i] = None if result is None else list(result)

        def statvfs(path):
            value = self.disks[path]
            if isinstance(value, OSError):
                raise value
            return mock.Mock(f_blocks=1000, f_bfree=round(1000 * (1 - value)))

        for obj, name, kwargs in ((S.plugins, "_failed", {"side_effect": failed}),
                                  (S.os, "statvfs", {"side_effect": statvfs}),
                                  (S, "quip", {"side_effect": lambda kind, **slots: S.QUIP_FALLBACK[kind][0].format(**slots)})):
            patch = mock.patch.object(obj, name, **kwargs)
            patch.start()
            self.addCleanup(patch.stop)

        self.offers = []
        self.real_offer = self.N.offer
        patch = mock.patch.object(self.N, "offer", side_effect=lambda *args: self.offers.append(args))
        patch.start()
        self.addCleanup(patch.stop)

    def route(self, name, content):
        (self.proc / "net" / name).write_text(content)

    def machine(self, t):
        self.A.machine(t, str(self.proc))

    def test_failed_units_first_read_unknown_and_recovery(self):
        self.units["system"] = ["old.service"]
        self.machine(100)
        self.assertEqual(self.offers, [])
        self.units["system"] = ["old.service", "new.service"]
        self.machine(220)
        self.assertEqual(self.offers, [("error", "new.service failed.", False, 220)])
        self.units["system"] = None
        self.machine(340)
        self.units["system"] = ["old.service", "new.service"]
        self.machine(460)
        self.assertEqual(len(self.offers), 1)
        self.units["system"] = []
        self.machine(580)
        self.units["system"] = ["new.service"]
        self.machine(700)
        self.assertEqual(len(self.offers), 2)
        self.assertEqual(self.offers[-1][1], "new.service failed.")

    def test_switches_reset_state_and_drop_waiting_machine_offers(self):
        self.machine(100)
        self.units["user"] = ["new.service"]
        self.machine(220)
        self.assertEqual(self.offers[-1][:3], ("error", "new.service failed.", False))
        for key in ("react_load", "proactive"):
            self.N.pending["error"] = ("old", False, 999)
            self.server.CFG[key] = False
            self.machine(340)
            self.assertEqual(self.A.failed, {"user": None, "system": None})
            self.assertNotIn("error", self.N.pending)
            self.server.CFG[key] = True
            self.machine(460)
            self.assertEqual(len(self.offers), 1)  # first good read after reset is a baseline

    def test_disk_hysteresis_and_unreadable_sample(self):
        self.machine(100)
        self.disks["/"] = .90
        self.machine(220)
        self.assertEqual(self.offers, [("disk", "Disk / is 90% full.", False, 220)])
        self.disks["/"] = .87
        self.machine(340)
        self.disks["/"] = OSError("unreadable")
        self.machine(460)
        self.assertEqual(len(self.offers), 1)
        self.disks["/"] = .84
        self.machine(580)
        self.disks["/"] = .90
        self.machine(700)
        self.assertEqual(len(self.offers), 2)

    def test_back_online_drops_a_held_offline_and_gate_off_drops_host(self):
        self.route("route", "")
        self.machine(100)
        self.N.pending["offline"] = ("No network connection.", False, 700)     # queued, held
        self.route("route", "eth0 00000000 00000000 0001\n")
        self.machine(140)
        self.assertNotIn("offline", self.N.pending)
        self.N.pending["host"] = ("oak is back.", False, 700)
        with mock.patch.object(self.server.plugins, "peers_allowed", return_value=False):
            self.machine(141)
        self.assertNotIn("host", self.N.pending)
        self.N.pending["host"] = ("oak is back.", False, 700)
        self.server.CFG["react_load"] = False
        self.machine(142)
        self.assertNotIn("host", self.N.pending)

    def test_offline_hold_and_return(self):
        self.route("route", "")
        self.machine(100)
        self.machine(129)
        self.assertEqual(self.offers, [])
        self.machine(130)
        self.assertEqual(self.offers, [("offline", "No network connection.", False, 130)])
        self.machine(200)
        self.assertEqual(len(self.offers), 1)
        self.route("route", "eth0 00000000 00000000 0001\n")
        self.machine(201)
        self.assertFalse(self.A.offline)
        self.route("route", "")
        self.machine(231)
        self.machine(261)
        self.assertEqual(len(self.offers), 2)

    def test_route_tables_and_unknown_keep_last_state(self):
        ipv6 = "0" * 32 + " 00 " + "0" * 32 + " 00 " + "0 " * 4 + "00000001 eth0\n"
        self.route("ipv6_route", ipv6)
        self.assertIs(self.A.route_up(str(self.proc)), True)
        self.route("ipv6_route", ipv6.replace("00000001 eth0", "00000201 lo"))
        self.route("route", "")
        self.assertIs(self.A.route_up(str(self.proc)), False)
        self.route("route", "bad row\neth0 00000000 0 invalid\n")
        self.assertIs(self.A.route_up(str(self.proc)), False)
        self.machine(100)
        self.machine(130)
        self.assertTrue(self.A.offline)
        for missing in ("route", "ipv6_route"):
            path = self.proc / "net" / missing
            old = path.read_text()
            path.unlink()
            self.assertIsNone(self.A.route_up(str(self.proc)))
            self.machine(140)
            self.assertTrue(self.A.offline)
            other = "ipv6_route" if missing == "route" else "route"
            self.route(other, ipv6 if other == "ipv6_route" else "eth0 00000000 0 0001\n")
            self.assertIs(self.A.route_up(str(self.proc)), True)
            self.route(other, "")
            path.write_text(old)

    def test_handoff_only_offers_from_loop_and_rechecks_switch(self):
        A, N = self.A, self.N
        N.offer.side_effect = self.real_offer
        with mock.patch.object(A, "step"), mock.patch.object(A, "sense"), mock.patch.object(N, "tick"):
            def one_pass():
                class StopLoop(BaseException):
                    pass
                with mock.patch.object(self.server.time, "sleep", side_effect=[None, StopLoop()]):
                    try:
                        A.loop()
                    except StopLoop:
                        pass

            worker = threading.Thread(target=lambda: A.hand("host", "host is back.", lambda: self.server.CFG["react_load"]))
            worker.start()
            worker.join()
            self.assertNotIn("host", N.pending)
            one_pass()
            self.assertEqual(N.pending["host"][:2], ("host is back.", False))
            A.hand("host", "late host is back.", lambda: self.server.CFG["react_load"])
            self.server.CFG["react_load"] = False
            one_pass()
            self.assertEqual(N.pending["host"][0], "host is back.")

    def test_peer_round_edges_and_callback_followup(self):
        S, A = self.server, self.A
        rows = [{"name": "oak", "state": "down"}]
        with mock.patch.object(S.plugins, "peers_allowed", return_value=True), \
                mock.patch.object(S.peers, "current", side_effect=lambda: list(rows)), \
                mock.patch.object(S.peers, "snapshot"):
            S._peer_followup_round = True
            self.addCleanup(setattr, S, "_peer_followup_round", False)
            S.peer_round_done()  # even a board follow-up round records its edges
            self.assertEqual(A.peer_last, {"oak": "down"})
            rows[0] = {"name": "oak", "state": "up"}
            S.peer_round_done()
            self.assertEqual(len(A.later), 1)
            self.assertEqual(A.later[0][:2], ("host", "oak is back."))
            self.assertNotIn("host", self.N.pending)
            S.peer_round_done()
            self.assertEqual(len(A.later), 1)
            rows[0] = {"name": "oak", "state": "down"}
            S.peer_round_done()
            self.assertEqual(A.later, [])  # going down cancels the held recovery
            rows[0] = {"name": "oak", "state": "up"}
            S.peer_round_done()
            self.assertEqual(len(A.later), 1)
            rows[0] = {"name": "birch", "state": "asking"}
            S.peer_round_done()
            rows[0] = {"name": "birch", "state": "up"}
            S.peer_round_done()
            self.assertEqual(A.later, [])

    def test_peer_down_again_cancels_handed_off_and_pending_recovery(self):
        S, A, N = self.server, self.A, self.N
        N.offer.side_effect = self.real_offer
        rows = [{"name": "oak", "state": "down"}]
        q = S.BUS.sub()
        self.addCleanup(S.BUS.unsub, q)

        def drain():
            with mock.patch.object(A, "step"), mock.patch.object(A, "sense"), \
                    mock.patch.object(N, "tick"), \
                    mock.patch.object(S.time, "sleep", side_effect=[None, KeyboardInterrupt()]):
                with self.assertRaises(KeyboardInterrupt):
                    A.loop()

        with mock.patch.object(S.plugins, "peers_allowed", return_value=True), \
                mock.patch.object(S.peers, "current", side_effect=lambda: list(rows)), \
                mock.patch.object(N, "watch"):
            A.peer_edges()
            rows[0] = {"name": "oak", "state": "up"}
            A.peer_edges()
            self.assertEqual(A.later[0][:2], ("host", "oak is back."))
            rows[0] = {"name": "oak", "state": "down"}
            A.peer_edges()
            self.assertEqual(A.later, [])
            drain()
            self.assertNotIn("host", N.pending)

            rows[0] = {"name": "oak", "state": "up"}
            A.peer_edges()
            drain()
            self.assertEqual(N.pending["host"][3], "oak")
            rows[0] = {"name": "oak", "state": "down"}
            A.peer_edges()
            self.assertNotIn("host", N.pending)
            N.tick()
            self.assertFalse(any(event.get("t") == "nudge" and "is back" in event.get("text", "")
                                 for event in list(q.queue)))

    def test_peer_switches_clear_baseline_even_without_round(self):
        S, A = self.server, self.A
        rows = [{"name": "oak", "state": "down"}]
        allowed = True
        with mock.patch.object(S.plugins, "peers_allowed", side_effect=lambda: allowed), \
                mock.patch.object(S.peers, "current", side_effect=lambda: list(rows)), \
                mock.patch.object(S.peers, "snapshot"):
            A.peer_edges()
            allowed = False
            self.machine(100)  # no callback happened while peers were off
            self.assertEqual(A.peer_last, {})
            allowed = True
            rows[0] = {"name": "oak", "state": "up"}
            A.peer_edges()
            self.assertEqual(A.later, [])
            rows[0] = {"name": "oak", "state": "down"}
            A.peer_edges()
            S.CFG["react_load"] = False
            self.machine(220)
            self.assertEqual(A.peer_last, {})
            S.CFG["react_load"] = True
            rows[0] = {"name": "oak", "state": "up"}
            A.peer_edges()
            self.assertEqual(A.later, [])

    def test_peer_handoff_checks_switch_at_drain(self):
        S, A, N = self.server, self.A, self.N
        N.offer.side_effect = self.real_offer
        with mock.patch.object(S.plugins, "peers_allowed", return_value=True), \
                mock.patch.object(S.peers, "current", side_effect=[
                    [{"name": "oak", "state": "down"}], [{"name": "oak", "state": "up"}],
                    [{"name": "oak", "state": "up"}, {"name": "birch", "state": "down"}],
                    [{"name": "oak", "state": "up"}, {"name": "birch", "state": "up"}]]):
            A.peer_edges()
            A.peer_edges()
            self.assertNotIn("host", N.pending)

            def drain():
                with mock.patch.object(A, "step"), mock.patch.object(A, "sense"), \
                        mock.patch.object(N, "tick"), \
                        mock.patch.object(S.time, "sleep", side_effect=[None, KeyboardInterrupt()]):
                    with self.assertRaises(KeyboardInterrupt):
                        A.loop()

            drain()
            self.assertEqual(N.pending["host"][0], "oak is back.")
            A.peer_edges()
            A.peer_edges()
            S.CFG["react_load"] = False
            drain()
            self.assertEqual(N.pending["host"][0], "oak is back.")
