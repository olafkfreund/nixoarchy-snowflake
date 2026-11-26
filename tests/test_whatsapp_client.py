"""The WhatsApp client against a disposable Unix HTTP bridge."""

import io
import json
import os
import socketserver
import stat
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from unittest import mock

import nixi_env

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import whatsapp


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def handle_request(self):
        size = int(self.headers.get("Content-Length", "0"))
        self.server.requests.append((self.command, self.path, dict(self.headers),
                                     json.loads(self.rfile.read(size)) if size else None))
        if self.server.drop:
            return
        body = json.dumps(self.server.reply).encode()
        self.send_response(self.server.status)
        self.send_header("X-Boot", "boot-1")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = handle_request
    do_POST = handle_request


class Server(socketserver.UnixStreamServer):
    allow_reuse_address = False


class WhatsAppClientTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="nixi-wa-test-", dir=nixi_env.run_dir())
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir(mode=0o700)
        # a short runtime dir: CI's work paths push a Unix socket path past its 108-byte limit
        self.short = tempfile.TemporaryDirectory(prefix="wa", dir="/tmp")
        self.env = mock.patch.dict(os.environ, nixi_env.server_env(os.environ, self.home) | {"HOME": str(self.home), "XDG_RUNTIME_DIR": self.short.name})
        self.env.start()
        self.run = Path(os.environ["XDG_RUNTIME_DIR"]) / "nixi-whatsapp"
        self.run.mkdir(mode=0o700)
        (self.run / "token").write_text("test-token")
        (self.run / "stage").mkdir(mode=0o700)
        (self.run / "dl").mkdir(mode=0o700)
        self.server = Server(str(self.run / "sock"), Handler)
        self.server.requests = []
        self.server.reply = {"state": "ready"}
        self.server.status = 200
        self.server.drop = False
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = whatsapp.WhatsApp()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.env.stop()
        self.tmp.cleanup()
        self.short.cleanup()

    def test_api_token_boot_and_json(self):
        data, boot = self.client.status()
        self.assertEqual((data, boot), ({"state": "ready"}, "boot-1"))
        self.client.pair()
        self.client.pair_cancel()
        self.client.chats("Alice & Bob", 7)
        self.client.contacts("Alice")
        self.client.thread("1@s.whatsapp.net", 9, 12)
        self.client.new(15)
        self.client.latest()
        self.client.download("1@s.whatsapp.net", "message")
        self.client.send("1@s.whatsapp.net", "hello", "boot-1")
        self.client.send_file("1@s.whatsapp.net", "staged", "caption", "photo.jpg", "boot-1")
        self.client.forget("boot-1")
        self.assertTrue(all(r[2]["Authorization"] == "Bearer test-token" for r in self.server.requests))
        self.assertEqual([r[1] for r in self.server.requests], [
            "/status", "/pair", "/pair/cancel", "/chats?q=Alice+%26+Bob&limit=7",
            "/contacts?q=Alice", "/thread?jid=1%40s.whatsapp.net&limit=9&before=12",
            "/new?after=15", "/new?latest=1", "/download", "/send", "/send-file", "/forget"])
        self.assertEqual([r[2]["If-Boot"] for r in self.server.requests[-3:]], ["boot-1"] * 3)
        self.assertEqual(self.server.requests[-2][3]["file_name"], "photo.jpg")

    def test_errors_and_lost_reply(self):
        self.server.status = 401
        self.server.reply = {"error": "unauthorized"}
        with self.assertRaises(whatsapp.Unauthorized) as caught:
            self.client.status()
        self.assertEqual(caught.exception.boot, "boot-1")
        self.server.status = 200
        for result, error in (("not_sent", whatsapp.NotSent), ("unknown", whatsapp.Unknown)):
            self.server.reply = {"result": result}
            with self.assertRaises(error) as caught:
                self.client.send("1@s.whatsapp.net", "hello", "boot-1")
            self.assertEqual(caught.exception.boot, "boot-1")
        self.server.drop = True
        with self.assertRaises(whatsapp.Unknown):
            self.client.send("1@s.whatsapp.net", "hello", "boot-1")

    def test_path_checks(self):
        os.chmod(self.run, 0o750)
        with self.assertRaises(whatsapp.Unavailable):
            self.client.status()
        os.chmod(self.run, 0o700)
        real_lstat = os.lstat

        def wrong_owner(path):
            value = real_lstat(path)
            if os.fspath(path) == str(self.run / "sock"):
                return mock.Mock(st_mode=value.st_mode, st_uid=os.getuid() + 1)
            return value

        with mock.patch.object(whatsapp.os, "lstat", side_effect=wrong_owner):
            with self.assertRaises(whatsapp.Unavailable):
                self.client.status()
        (self.run / "token").unlink()
        (self.run / "token").symlink_to(self.home / "secret")
        with self.assertRaises(whatsapp.Unavailable):
            self.client.status()

    def test_unavailable(self):
        self.server.shutdown()
        self.server.server_close()
        (self.run / "sock").unlink()
        with self.assertRaises(whatsapp.Unavailable):
            self.client.send("1@s.whatsapp.net", "hi", "boot-1")

    def test_stage_limit_cleanup_and_exclusive_name(self):
        client = whatsapp.WhatsApp(self.run, max_file=3)
        with self.assertRaises(ValueError):
            client.stage(io.BytesIO(b"abcd"), 4)
        with self.assertRaises(ValueError):
            client.stage(io.BytesIO(b"a"), 2)
        self.assertEqual(list((self.run / "stage").iterdir()), [])
        with mock.patch.object(whatsapp.secrets, "token_urlsafe", return_value="A" * 32):
            name = client.stage(io.BytesIO(b"abc"), 3)
            self.assertEqual((self.run / "stage" / name).read_bytes(), b"abc")
            self.assertEqual(stat.S_IMODE((self.run / "stage" / name).stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                client.stage(io.BytesIO(b"x"), 1)
            self.assertEqual((self.run / "stage" / name).read_bytes(), b"abc")

    def test_fetch_copy_clash_and_unlink(self):
        file = "123-0123456789abcdef.txt"
        source = self.run / "dl" / file
        source.write_bytes(b"new")
        dest = self.home / "elsewhere"
        dest.mkdir()
        (dest / "report.txt").write_bytes(b"old")
        path = self.client.fetch(file, dest_dir=dest, name="../report.txt")
        self.assertEqual(path, dest / "report-1.txt")
        self.assertEqual(path.read_bytes(), b"new")
        self.assertEqual((dest / "report.txt").read_bytes(), b"old")
        self.assertFalse(source.exists())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        source.write_bytes(b"default")
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            path = self.client.fetch(file)
        self.assertEqual(path, self.home / "Downloads" / "WhatsApp" / file)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_fetch_rejects_bad_names_and_symlinks(self):
        for file in ("../bad", "123-0123456789abcdef.TXT", "123-0123456789abcdef.txt/other"):
            with self.assertRaises(ValueError):
                self.client.fetch(file, dest_dir=self.home)
        file = "123-0123456789abcdef.txt"
        source = self.run / "dl" / file
        source.symlink_to(self.home / "private")
        with self.assertRaises(OSError):
            self.client.fetch(file, dest_dir=self.home)
        self.assertFalse(source.is_symlink())

    def test_fetch_uses_bridge_extension_and_sanitizes_sender(self):
        file = "123-0123456789abcdef.png"
        source = self.run / "dl" / file
        source.write_bytes(b"image")
        path = self.client.fetch(file, dest_dir=self.home, name="../.\u202ephoto.exe")
        self.assertEqual(path.name, "photo.png")
        source.write_bytes(b"image")
        path = self.client.fetch(file, dest_dir=self.home, name="\u2066...")
        self.assertEqual(path.name, file)

    def test_send_file_timeout_and_no_none_boot_header(self):
        seen = []
        connect = whatsapp._UnixHTTP.connect
        def watch(conn):
            seen.append(conn.timeout)
            return connect(conn)
        with mock.patch.object(whatsapp._UnixHTTP, "connect", watch):
            self.client.status()
            self.client.send_file("1@s.whatsapp.net", "staged", "", "file.txt", None)
        self.assertEqual(seen, [30, 900])
        self.assertNotIn("If-Boot", self.server.requests[-1][2])

    def test_fetch_removes_partial_copy_and_source_on_error(self):
        file = "123-0123456789abcdef.txt"
        source = self.run / "dl" / file
        source.write_bytes(b"contents")

        def fail_copy(src, out):
            out.write(b"partial")
            raise OSError("disk full")

        with mock.patch.object(whatsapp.shutil, "copyfileobj", side_effect=fail_copy):
            with self.assertRaises(OSError):
                self.client.fetch(file, dest_dir=self.home)
        self.assertFalse(source.exists())
        self.assertFalse((self.home / file).exists())


if __name__ == "__main__":
    unittest.main()
