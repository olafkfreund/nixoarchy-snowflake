"""Local HTTP checks for the bounded peer collector."""
import http.server
import ipaddress
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from test_speakable import _ServerEnv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import peers  # noqa: E402


STATUS = {"host": "peer", "cpu_pct": 12.5, "mem": {"total": 100, "available": 50},
          "disks": [{"path": "/", "total": 100, "used": 20}],
          "net": {"rx_bps": 1, "tx_bps": None}, "uptime_s": 42,
          "failed_system": [], "generation": "system-1", "rev": "abc", "built": None,
          "failed": None}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append((self.path, self.headers.get("Authorization")))
        if self.server.delay:
            time.sleep(self.server.delay)
        body = self.server.body
        try:
            self.send_response(self.server.code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if getattr(self.server, "drip", False):         # one byte every 0.5 s: never silent long enough to time out
                for i in range(len(body)):
                    self.wfile.write(body[i:i + 1]); self.wfile.flush(); time.sleep(0.5)
            else:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


class PeerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name, "peers.json")
        self.token = Path(self.tmp.name, "token")
        self.token.write_text("  test-token\n")
        self.servers = []
        patch = mock.patch.object(peers, "_RANGES", (ipaddress.ip_network("127.0.0.0/8"),))
        patch.start()
        self.addCleanup(patch.stop)
        peers.stop()
        peers.on_round(None)
        self.addCleanup(peers.stop)
        self.addCleanup(lambda: peers.on_round(None))

    def server(self, body=None, code=200, delay=0):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        server.requests = []
        server.body = json.dumps(STATUS if body is None else body).encode() if not isinstance(body, bytes) else body
        server.code = code
        server.delay = delay
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.servers.append(server)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def configure(self, servers, extra=()):
        entries = [{"name": f"peer{i}", "address": "127.0.0.1", "port": server.server_port}
                   for i, server in enumerate(servers)]
        self.path.write_text(json.dumps({"peers": entries + list(extra), "token_file": str(self.token)}))
        peers.load(self.path)

    def test_parallel_round_deadline_limit_and_auth(self):
        servers = [self.server(), self.server(delay=3), self.server(body=b"x" * (65 * 1024)),
                   self.server(code=302)]
        self.configure(servers)
        done = threading.Event()
        peers.on_round(done.set)
        started = time.monotonic()
        first = peers.snapshot()
        self.assertLess(time.monotonic() - started, 0.01)
        self.assertEqual([row["state"] for row in first], ["asking"] * 4)
        peers.snapshot()
        self.assertTrue(done.wait(2.1), "round exceeded its two second deadline")
        self.assertLess(time.monotonic() - started, 2.1)
        self.assertTrue(all(server.requests == [("/v1/status", "Bearer test-token")]
                            for server in servers))
        rows = peers.snapshot()
        self.assertEqual([row["state"] for row in rows], ["up", "down", "down", "down"])
        self.assertEqual(rows[0]["status"], STATUS)
        self.assertIsNotNone(rows[0]["last_ok"])
        self.assertEqual(rows[2]["note"], "gave an answer Nixi can't read")

    def test_current_is_independent_and_does_not_start_a_round(self):
        with mock.patch.object(peers, "_results", [{"name": "peer0", "state": "asking"}]), \
                mock.patch.object(peers, "_peers", [{"name": "peer0"}]), \
                mock.patch.object(peers, "_round") as round_run:
            rows = peers.current()
            rows[0]["state"] = "up"
            self.assertEqual(peers.current()[0]["state"], "asking")
            round_run.assert_not_called()
            self.assertFalse(peers._running)

    def test_a_dripping_peer_is_cut_off_at_the_deadline(self):
        server = self.server()
        server.drip = True
        self.configure([server])
        done = threading.Event()
        peers.on_round(done.set)
        def workers():                                   # the collector's own threads (the fake server's drip thread goes on)
            return [t for t in threading.enumerate() if getattr(t, "_target", None) is peers._ask]
        started = time.monotonic()
        peers.snapshot()
        self.assertTrue(done.wait(2.2), "round exceeded its two second deadline")
        self.assertEqual(peers._results[0]["state"], "down")    # (not snapshot(): that would start the next round)
        deadline = time.monotonic() + 1                  # the worker ends soon after the round, not after the whole drip
        while workers() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(workers(), [], "a worker outlived its round")
        self.assertLess(time.monotonic() - started, 3.3)

    def test_stop_discards_round_and_last_ok(self):
        server = self.server(delay=0.2)
        self.configure([server])
        called = threading.Event()
        peers.on_round(called.set)
        peers.snapshot()
        time.sleep(0.05)
        peers.stop()
        time.sleep(0.3)
        self.assertFalse(called.is_set())
        row = peers.snapshot()[0]
        self.assertIsNone(row["last_ok"])
        self.assertEqual(row["state"], "asking")

    def test_bad_types_and_unknown_keys(self):
        for bad in ("x", True):
            with self.subTest(bad=bad):
                server = self.server(body={**STATUS, "cpu_pct": bad})
                self.configure([server])
                done = threading.Event()
                peers.on_round(done.set)
                peers.snapshot()
                self.assertTrue(done.wait(2))
                self.assertEqual(peers.snapshot()[0]["note"], "gave an answer Nixi can't read")
        server = self.server(body={**STATUS, "extra": "discard"})
        self.configure([server])
        done = threading.Event()
        peers.on_round(done.set)
        peers.snapshot()
        self.assertTrue(done.wait(2))
        self.assertNotIn("extra", peers.snapshot()[0]["status"])

    def test_missing_config_rejected_addresses_and_missing_token(self):
        self.assertEqual(peers.load(self.path), [])
        self.assertEqual(peers.snapshot(), [])
        server = self.server()
        denied = [{"name": "lan", "address": "192.168.1.65", "port": server.server_port},
                  {"name": "dns", "address": "localhost", "port": server.server_port},
                  {"name": "tailscale", "address": "100.100.100.100", "port": server.server_port}]
        self.configure([server], denied)
        self.token.unlink()
        done = threading.Event()
        peers.on_round(done.set)
        self.assertEqual(len(peers.snapshot()), 1)
        self.assertTrue(done.wait(2))
        self.assertEqual(peers.snapshot()[0]["note"], "no token")
        self.assertEqual(server.requests, [])


class HostRoundIntegration(_ServerEnv):
    def test_machine_and_board_round_counts(self):
        S, A = self.server, self.server.Ambient
        stub = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        stub.daemon_threads = True
        stub.requests, stub.body, stub.code, stub.delay = [], json.dumps(STATUS).encode(), 503, 0
        threading.Thread(target=stub.serve_forever, daemon=True).start()
        self.addCleanup(stub.server_close)
        self.addCleanup(stub.shutdown)
        path, token = Path(self.tmp, "host-round-peers.json"), Path(self.tmp, "host-round-token")
        token.write_text("test-token")
        path.write_text(json.dumps({"peers": [{"name": "oak", "address": "127.0.0.1", "port": stub.server_port}],
                                    "token_file": str(token)}))
        old_cfg = dict(S.CFG)
        self.addCleanup(lambda: (S.CFG.clear(), S.CFG.update(old_cfg)))
        S.CFG.update(proactive=True, react_load=True, peers_on=True)
        A.peer_last, A.peer_due, A.machine_due, A.later = {}, 0, float("inf"), []
        S._peer_followup_round = False
        self.addCleanup(setattr, S, "_peer_followup_round", False)
        completed = []
        original_edges = A.peer_edges

        def record_edges():
            original_edges()
            completed.append(None)

        with mock.patch.object(peers, "_RANGES", (ipaddress.ip_network("127.0.0.0/8"),)), \
                mock.patch.object(S, "PEERS", [{"name": "oak"}]), \
                mock.patch.object(A, "route_up", return_value=True), \
                mock.patch.object(peers, "_round", wraps=peers._round) as rounds, \
                mock.patch.object(A, "peer_edges", side_effect=record_edges):
            peers.load(path)
            peers.on_round(S.peer_round_done)
            self.addCleanup(lambda: peers.on_round(None))
            self.addCleanup(peers.stop)

            def wait_for(count):
                deadline = time.monotonic() + 2
                while len(completed) < count and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(len(completed), count)

            with mock.patch.object(S.STAGES, "current", return_value=None), \
                    mock.patch.object(S, "quip", side_effect=lambda kind, **slots: S.QUIP_FALLBACK[kind][0].format(**slots)):
                A.machine(100)
                wait_for(1)
                self.assertEqual(rounds.call_count, 1)
                self.assertEqual(A.peer_last, {"oak": "down"})
                stub.code = 200
                A.machine(400)
                wait_for(2)
                self.assertEqual(rounds.call_count, 2)
                self.assertEqual([item[:2] for item in A.later], [("host", "oak is back.")])

            peers.stop()
            A.peer_last, A.peer_due, A.later = {}, 0, []
            stub.code = 503
            page = {"kind": "gauges", "live": True, "refresh": "board"}
            plugin = mock.Mock(manifest={"stage": {"reads": ["peer-status"]}})
            with mock.patch.object(S.STAGES, "current", return_value=page), \
                    mock.patch.object(S.STAGES, "visible", return_value=True), \
                    mock.patch.object(S.STAGES, "get", return_value=("refresh", {"pid": "x"})), \
                    mock.patch.object(S.Plug, "stage", {"x": plugin}), \
                    mock.patch.object(S, "refresh_stage", side_effect=lambda _: (peers.snapshot(), {"ok": True})[1]):
                A.machine(700)
                wait_for(4)
                self.assertEqual(rounds.call_count, 4)
                self.assertEqual(A.peer_last, {"oak": "down"})
                self.assertEqual(A.later, [])


if __name__ == "__main__":
    unittest.main()
