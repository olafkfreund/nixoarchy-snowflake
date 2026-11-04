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
            self.wfile.write(body)
        except BrokenPipeError:
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


if __name__ == "__main__":
    unittest.main()
