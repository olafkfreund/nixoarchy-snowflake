import json
import threading
import unittest
import urllib.request
from http.server import HTTPServer
from unittest import mock

from test_speakable import _ServerEnv


class IdleModeTest(_ServerEnv):
    """#140 S1: idle_mode is off | shrink | doze, shrink by default; /api/settings ignores anything else."""

    def post(self, body):
        s = self.server
        httpd = HTTPServer(("127.0.0.1", 0), s.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        req = urllib.request.Request(f"http://127.0.0.1:{httpd.server_port}/api/settings", json.dumps(body).encode(),
                                     {"X-Nixi-Token": s.TOKEN})
        try:
            with mock.patch.object(s, "save_config", side_effect=lambda **kw: s.CFG.update(kw)) as sc, \
                    mock.patch.object(s.Wake, "ensure"):
                with urllib.request.urlopen(req) as r:
                    return json.load(r), sc
        finally:
            httpd.shutdown()
            httpd.server_close()

    def setUp(self):
        self.server.CFG["idle_mode"] = "shrink"
        p = mock.patch.object(self.server.quick, "cfg", self.server.CFG)  # the app wires this at startup
        p.start()
        self.addCleanup(p.stop)

    def test_default_is_shrink(self):
        self.assertEqual(self.server.state_info()["idle_mode"], "shrink")

    def test_bad_stored_value_reads_as_shrink(self):
        self.server.CFG["idle_mode"] = "nap"
        self.assertEqual(self.server.state_info()["idle_mode"], "shrink")

    def test_accepts_the_three_modes(self):
        for m in ("off", "doze", "shrink"):
            info, sc = self.post({"idle_mode": m})
            self.assertEqual(info["idle_mode"], m)
            sc.assert_called_once_with(idle_mode=m)

    def test_rejects_anything_else(self):
        for bad in ("nap", "", None, 1, ["off"]):
            info, sc = self.post({"idle_mode": bad})
            sc.assert_not_called()
            self.assertEqual(info["idle_mode"], "shrink")


if __name__ == "__main__":
    unittest.main()
