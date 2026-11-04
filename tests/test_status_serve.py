"""The status endpoint only answers authorized, bounded reads."""
import contextlib
import http.client
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import status_serve  # noqa: E402


STATUS = {"host": "p620", "cpu_pct": 12.5, "mem": None, "disks": None,
          "net": {"rx_bps": None, "tx_bps": None}, "uptime_s": 42,
          "failed_system": [], "generation": "system-1", "rev": "abc", "built": None}


class StatusServe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.token_file = Path(self.tmp.name, "token")
        self.token_file.write_bytes(b"test-token\n")
        self.server = status_serve.StatusServer(("127.0.0.1", 0), ["127.0.0.1"], self.token_file.read_bytes().rstrip())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, method="GET", path="/v1/status", token="test-token", source=None, server=None):
        server = server or self.server
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2, source_address=(source, 0) if source else None)
        try:
            headers = {} if token is None else {"Authorization": "Bearer " + token}
            conn.request(method, path, headers=headers)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def test_access_and_shape(self):
        with mock.patch.object(status_serve, "system_status", return_value=STATUS) as status, \
             contextlib.redirect_stderr(io.StringIO()) as stderr:
            wrong = self.request(token="wrong")
            missing = self.request(token=None)
            self.assertEqual(wrong[0], 403)
            self.assertEqual(missing, wrong)
            self.assertEqual(self.request("POST")[0], 404)
            self.assertEqual(self.request(path="/")[0], 404)
            code, body = self.request()
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body), {**STATUS, "failed": None})
        status.assert_called_once_with(user=False)
        self.assertEqual(stderr.getvalue(), "")

    def test_source_address_is_checked_before_token(self):
        other = status_serve.StatusServer(("127.0.0.1", 0), ["127.0.0.2"], b"test-token")
        thread = threading.Thread(target=other.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.object(status_serve, "system_status") as status:
                self.assertEqual(self.request(server=other), (403, status_serve.FORBIDDEN))
                self.assertEqual(self.request(token=None, server=other), (403, status_serve.FORBIDDEN))
                self.assertEqual(self.request(path="/", server=other), (403, status_serve.FORBIDDEN))      # a stranger can't probe paths
                self.assertEqual(self.request("POST", server=other), (403, status_serve.FORBIDDEN))
            status.assert_not_called()
        finally:
            other.shutdown()
            other.server_close()
            thread.join(2)

    def test_oversized_status_is_fixed_500(self):
        with mock.patch.object(status_serve, "system_status", return_value={**STATUS, "host": "x" * 17000}):
            self.assertEqual(self.request(), (500, status_serve.TOO_LARGE))

    def test_fifth_request_does_not_start_a_handler(self):
        entered = threading.Event()
        release = threading.Event()
        lock = threading.Lock()
        count = 0
        results = []

        def blocked(user):
            nonlocal count
            with lock:
                count += 1
                if count == 4:
                    entered.set()
            release.wait(3)
            return STATUS

        def request():
            try:
                results.append(self.request())
            except OSError as error:
                results.append(error)

        with mock.patch.object(status_serve, "system_status", side_effect=blocked):
            threads = [threading.Thread(target=request) for _ in range(4)]
            for thread in threads:
                thread.start()
            try:
                self.assertTrue(entered.wait(2), "four requests did not reach system_status")
                with self.assertRaises((OSError, http.client.RemoteDisconnected)):
                    self.request()
                with lock:
                    self.assertEqual(count, 4)
            finally:
                release.set()
                for thread in threads:
                    thread.join(2)
        self.assertEqual(len(results), 4)
        self.assertTrue(all(isinstance(result, tuple) and result[0] == 200 for result in results))


class StatusStartup(unittest.TestCase):
    def test_main_reads_token_once_and_sets_stack_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_file = Path(tmp, "token")
            token_file.write_bytes(b"test-token\n")
            with mock.patch.object(status_serve, "StatusServer") as server, \
                 mock.patch.object(status_serve.threading, "stack_size") as stack, \
                 contextlib.redirect_stderr(io.StringIO()) as stderr:
                status_serve.main(["--address", "127.0.0.1", "--port", "9188",
                                   "--allow", "127.0.0.2", "--token-file", str(token_file)])
            server.assert_called_once_with(("127.0.0.1", 9188), ["127.0.0.2"], b"test-token")
            stack.assert_called_once_with(256 * 1024)
            self.assertIn("nixi-status listening", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
