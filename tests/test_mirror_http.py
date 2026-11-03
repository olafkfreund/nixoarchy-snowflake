"""#145 over HTTP: the token gates /api/mirror/off, a new event stream starts with the mirror state, and "take control
back" by voice revokes and answers from the result. A real server in a throwaway home, with a fake `ai-mirror` on PATH
(never the real one)."""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

FAKE = """#!/bin/sh
d="$(dirname "$0")"
echo "$*" >> "$d/argv.log"
case "$*" in
  "status") cat "$XDG_RUNTIME_DIR/ai-mirror/state.json" ;;
  "control off") printf '{"owner":"off","generation":2}' > "$XDG_RUNTIME_DIR/ai-mirror/state.json"
                 printf '{"owner":"off","generation":2}' ;;
  *) echo '{"error":{"message":"not allowed in this test"}}'; exit 1 ;;
esac
"""


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class MirrorHttp(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="nixi-mirror-"))
        run, fakebin = self.home / "run", self.home / "bin"
        (run / "ai-mirror").mkdir(parents=True)
        fakebin.mkdir()
        (run / "ai-mirror/state.json").write_text('{"owner":"agent","generation":1}')
        (fakebin / "ai-mirror").write_text(FAKE)
        (fakebin / "ai-mirror").chmod(0o755)
        for d in (".config/nixi-companion", "data", "state"):
            (self.home / d).mkdir(parents=True, exist_ok=True)
        self.port = _free_port()
        (self.home / ".config/nixi-companion/config.json").write_text(json.dumps({"port": self.port}))
        path = [str(fakebin)] + [d for d in os.environ.get("PATH", "").split(os.pathsep)
                                 if not os.path.exists(os.path.join(d, "ai-mirror"))]
        env = dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / ".config"),
                   XDG_DATA_HOME=str(self.home / "data"), XDG_STATE_HOME=str(self.home / "state"),
                   XDG_RUNTIME_DIR=str(run), PATH=os.pathsep.join(path))
        self.argv_log = fakebin / "argv.log"
        self.srv = subprocess.Popen([sys.executable, str(REPO / "app/server.py")], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        rt = self.home / "data/nixi-companion/runtime.json"
        for _ in range(80):
            if rt.exists():
                break
            time.sleep(0.25)
        self.token = json.loads(rt.read_text())["token"]
        self.deadline(lambda: self.state()["mirror"]["owner"] == "agent", "the watcher never saw the grant")

    def tearDown(self):
        self.srv.terminate()
        try:
            self.srv.wait(5)
        except subprocess.TimeoutExpired:
            self.srv.kill()
        shutil.rmtree(self.home, ignore_errors=True)

    def post(self, path, body=None, token=True):
        h = {"Content-Type": "application/json"}
        if token:
            h["X-Nixi-Token"] = self.token
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body or {}).encode(), headers=h)
        return urllib.request.urlopen(req, timeout=10)

    def state(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/state", headers={"X-Nixi-Token": self.token})
        return json.loads(urllib.request.urlopen(req, timeout=5).read())

    def deadline(self, ok, msg, secs=15):
        end = time.monotonic() + secs
        while time.monotonic() < end:
            try:
                if ok():
                    return
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(0.25)
        self.fail(msg)

    def test_token_events_and_voice(self):
        with self.assertRaises(urllib.error.HTTPError) as e:   # no token: forbidden
            self.post("/api/mirror/off", token=False)
        self.assertEqual(e.exception.code, 403)

        stream = self.post("/api/events")                      # a new stream starts with the mirror state
        seen, end = b"", time.monotonic() + 10
        while b'"mirror"' not in seen and time.monotonic() < end:
            seen += stream.read1(4096) if hasattr(stream, "read1") else stream.read(256)
        stream.close()
        self.assertIn(b'"owner": "agent"', seen.replace(b'"owner":"agent"', b'"owner": "agent"'))

        r = json.loads(self.post("/api/quick", {"text": "take control back"}).read())
        self.assertEqual(r.get("say"), "Control is back with you.")
        self.assertEqual(r.get("mood"), "happy")
        r = json.loads(self.post("/api/quick", {"text": "take control back"}).read())
        self.assertEqual(r.get("say"), "No agent is controlling the mouse and keyboard through ai-mirror.")

        argv = self.argv_log.read_text().split("\n")
        self.assertTrue(set(a for a in argv if a) <= {"status", "control off"}, argv)   # never agent/confirm/deny


if __name__ == "__main__":
    unittest.main()
