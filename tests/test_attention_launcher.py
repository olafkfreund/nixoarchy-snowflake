import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = REPO_ROOT / "bin" / "nixi-companion"
FIX = REPO_ROOT / "tests" / "fixtures" / "hooks"
ALLOWED = {"notification_type", "message", "type", "last-assistant-message", "hook_event_name", "cwd", "title",
           "prompt_response", "response", "error", "fullyIdle"}


class LauncherTest(unittest.TestCase):
    """`nixi-companion attention --hook` against a tiny listener standing in for the server."""

    def setUp(self):
        self.got = got = []

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                got.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200); self.end_headers(); self.wfile.write(b"{}")

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name, "nixi-companion"); d.mkdir()
        (d / "runtime.json").write_text(json.dumps({"port": self.srv.server_port, "token": "t"}))
        self.env = dict(os.environ, XDG_DATA_HOME=self.tmp.name, NIXI_COMPANION_PYTHON=sys.executable)

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close(); self.tmp.cleanup()

    def run_it(self, *args, stdin=b""):
        r = subprocess.run(["bash", str(LAUNCHER), "attention", *args], input=stdin, env=self.env, timeout=10)
        self.assertEqual(r.returncode, 0)
        return self.got[-1] if self.got else None

    def test_claude_on_stdin_keeps_only_allowed_keys(self):
        b = self.run_it("--from", "claude", "--hook", stdin=(FIX / "claude-permission.json").read_bytes())
        self.assertEqual(b["from"], "claude")
        self.assertEqual(b["text"], "")
        self.assertTrue(b["hook"] and set(b["hook"]) <= ALLOWED)
        self.assertEqual(b["hook"]["notification_type"], "permission_prompt")

    def test_agy_cwd_from_workspace_and_fully_idle_kept(self):
        h = json.loads((FIX / "agy.json").read_text())
        b = self.run_it("--from", "agy", "--hook", stdin=json.dumps(h).encode())
        self.assertEqual(b["hook"]["cwd"], h["workspacePaths"][0])
        self.assertIs(b["hook"]["fullyIdle"], h["fullyIdle"])
        self.assertNotIn("workspacePaths", b["hook"])

    def test_codex_as_argument(self):
        b = self.run_it("--from", "codex", "--hook", (FIX / "codex.json").read_text())
        self.assertEqual(b["hook"]["type"], "agent-turn-complete")

    def test_long_string_is_cut_at_a_word(self):
        b = self.run_it("--from", "claude", "--hook", stdin=json.dumps({"message": "word " * 80}).encode())
        m = b["hook"]["message"]
        self.assertLessEqual(len(m), 300)
        self.assertTrue(m.endswith("word"))

    def test_bad_json_argument_is_not_sent_as_text(self):
        b = self.run_it("--from", "claude", "--hook", "{not json", stdin=b"")
        self.assertNotIn("hook", b)
        self.assertNotIn("{", b["text"])

    def test_open_stdin_never_hangs(self):
        t0 = time.time()
        p = subprocess.Popen(["bash", str(LAUNCHER), "attention", "--from", "claude", "--hook"], stdin=subprocess.PIPE, env=self.env)
        try:
            self.assertEqual(p.wait(timeout=3), 0)
        finally:
            p.stdin.close()
        self.assertLess(time.time() - t0, 3)


if __name__ == "__main__":
    unittest.main()
