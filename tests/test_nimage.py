import json
import io
import os
import struct
import tempfile
import threading
import time
import unittest
import zlib
from pathlib import Path
from unittest import mock

from test_speakable import _ServerEnv


def chunk(kind, data=b""):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(width=1, height=1, ihdr=None, extra=b""):
    header = ihdr if ihdr is not None else struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    pixels = b"\0" + b"\xff\0\0\xff" * width if width < 2048 else b"\0"
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + extra + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND")


class NImageTest(_ServerEnv):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=self.tmp))
        self.server.NImage.clear()
        self.server.CFG["notify_details"] = True

    def file(self, name, data):
        path = self.root / name
        path.write_bytes(data)
        return path

    def request(self, path, body=None):
        handler = self.server.Handler.__new__(self.server.Handler)
        handler.path = path
        handler.headers = {"Host": "127.0.0.1"}
        handler.rfile = io.BytesIO(body or b"")
        handler.wfile = io.BytesIO()
        headers = {}
        status = []
        handler.send_response = lambda code: status.append(code)
        handler.send_header = lambda key, value: headers.__setitem__(key, value)
        handler.end_headers = lambda: None
        if body is not None:
            handler.headers["X-Nixi-Token"] = self.server.TOKEN
            handler.headers["Content-Length"] = str(len(body))
            handler.do_POST()
        else:
            handler.do_GET()
        return status[0], headers, handler.wfile.getvalue()

    def test_png_is_served_from_first_read(self):
        original = png()
        path = self.file("image.png", original)
        key = self.server.NImage.add(path)
        self.assertRegex(key, r"^[0-9a-f]{16}$")
        path.write_bytes(png(2, 2))
        status, headers, data = self.request("/api/nimage/" + key)
        self.assertEqual((status, data, headers["Content-Type"], headers["Cache-Control"]),
                         (200, original, "image/png", "no-store"))

    def test_refused_files(self):
        good = self.file("good.png", png())
        link = self.root / "link"
        link.symlink_to(good)
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        refused = [link, self.root, self.file("huge.png", b"x" * (2 * 1024 * 1024)),
                   self.file("image.svg", b"<svg/>"), self.file("image.jpg", b"\xff\xd8\xff"),
                   self.file("animated.png", png(extra=chunk(b"acTL", struct.pack(">II", 1, 0)))),
                   self.file("broken.png", png(ihdr=b"short")), self.file("large.png", png(3000, 3000))]
        for path in refused:
            with self.subTest(path=path.name):
                self.assertIsNone(self.server.NImage.add(path))
        result = []
        thread = threading.Thread(target=lambda: result.append(self.server.NImage.add(fifo)), daemon=True)
        thread.start()
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive(), "FIFO read blocked")
        self.assertEqual(result, [None])

    def test_file_growing_during_read_is_refused(self):
        path = self.file("growing.png", png())
        with mock.patch.object(self.server.os, "read", return_value=b"x" * (self.server.NImage.MAX + 1)):
            self.assertIsNone(self.server.NImage.add(path))

    def test_unknown_bad_expired_and_cleared_ids(self):
        key = self.server.NImage.add(self.file("image.png", png()))
        for bad in ("0" * 16, "ABCDEF0123456789", key + "0", "../" + key):
            self.assertEqual(self.request("/api/nimage/" + bad)[0], 404, bad)
        with mock.patch.object(self.server.time, "monotonic", return_value=time.monotonic() + 61):
            self.assertEqual(self.request("/api/nimage/" + key)[0], 404)
        key = self.server.NImage.add(self.file("another.png", png()))
        self.server.NImage.clear()
        self.assertEqual(self.request("/api/nimage/" + key)[0], 404)

    def test_settings_turning_details_off_empties_store(self):
        key = self.server.NImage.add(self.file("image.png", png()))
        self.server.CFG["notify_details"] = True
        with mock.patch.object(self.server.Wake, "ensure"), mock.patch.object(self.server, "state_info", return_value={}):
            status, _, _ = self.request("/api/settings", json.dumps({"notify_details": False}).encode())
        self.assertEqual(status, 200)
        self.assertEqual(self.request("/api/nimage/" + key)[0], 404)

    def test_nothing_is_kept_once_details_are_off(self):
        self.server.CFG["notify_details"] = False                # (turned off while the file was being read)
        self.assertIsNone(self.server.NImage.add(self.file("image.png", png())))

    def test_oldest_is_evicted_after_eight(self):
        path = self.file("image.png", png())
        keys = [self.server.NImage.add(path) for _ in range(9)]
        self.assertEqual(self.request("/api/nimage/" + keys[0])[0], 404)
        self.assertTrue(all(self.request("/api/nimage/" + key)[0] == 200 for key in keys[1:]))


if __name__ == "__main__":
    unittest.main()
