"""Launcher hook protocol tests with synthetic payloads pending probe P9."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

import nixi_env


ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "bin" / "nixi-companion"
FIX = ROOT / "tests" / "fixtures" / "hooks"
ALLOW = b'{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}\n'
DENY = b'{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"deny","message":"The user said no in Nixi."}}}\n'


class AgentHooksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_env = os.environ.copy()
        cls.home = tempfile.mkdtemp(prefix="nixi-hook-import-")
        for key, suffix in (("HOME", ""), ("XDG_CONFIG_HOME", ".config"),
                            ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
            os.environ[key] = os.path.join(cls.home, suffix)
            os.makedirs(os.environ[key], exist_ok=True)
        sys.path.insert(0, str(ROOT / "app"))
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": nixi_env.run_dir()}):
            import server
        cls.server_module = server

    @classmethod
    def tearDownClass(cls):
        os.environ.clear()
        os.environ.update(cls.old_env)
        shutil.rmtree(cls.home, ignore_errors=True)

    def setUp(self):
        self.received = []
        self.reply = b'{"decision":"allow"}'
        self.status = 200
        self.close_early = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                owner.received.append((self.path, self.headers.get("X-Nixi-Token"), json.loads(body)))
                if owner.close_early:
                    self.close_connection = True
                    return
                self.send_response(owner.status)
                self.end_headers()
                self.wfile.write(owner.reply)

            def log_message(self, *_args):
                pass

        self.http = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.tmp = tempfile.TemporaryDirectory()
        runtime = Path(self.tmp.name, "nixi-companion")
        runtime.mkdir()
        (runtime / "runtime.json").write_text(json.dumps({"port": self.http.server_port, "token": "private-token"}))
        self.env = dict(os.environ, XDG_DATA_HOME=self.tmp.name, NIXI_COMPANION_PYTHON=sys.executable)

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.tmp.cleanup()

    def run_hook(self, mode, agent, payload):
        proc = subprocess.run(["bash", str(LAUNCHER), mode, "--from", agent], input=payload,
                              env=self.env, capture_output=True, timeout=10)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr, b"")
        return proc.stdout

    def test_allow_and_deny_exact_bytes_for_both_agents(self):
        for agent in ("claude", "codex"):
            payload = (FIX / f"{agent}-approval.json").read_bytes()
            self.assertEqual(self.run_hook("approve", agent, payload), ALLOW)
            path, token, body = self.received[-1]
            self.assertEqual((path, token), ("/api/agent-approve", "private-token"))
            self.assertEqual(body["from"], agent)
            self.assertEqual(body["tool_input"], json.loads(payload)["tool_input"])
            self.assertIn("target", body)
            self.reply = b'{"decision":"deny"}'
            self.assertEqual(self.run_hook("approve", agent, payload), DENY)
            self.reply = b'{"decision":"allow"}'

    def test_no_output_on_server_errors_or_closed_connection(self):
        payload = (FIX / "codex-approval.json").read_bytes()
        self.status = 500
        self.assertEqual(self.run_hook("approve", "codex", payload), b"")
        self.status = 200
        self.reply = b"invalid json"
        self.assertEqual(self.run_hook("approve", "codex", payload), b"")
        self.close_early = True
        self.assertEqual(self.run_hook("approve", "codex", payload), b"")

    def test_no_output_on_connection_refused_or_unknown_agent(self):
        payload = (FIX / "codex-approval.json").read_bytes()
        self.assertEqual(self.run_hook("approve", "agy", payload), b"")
        self.assertEqual(len(self.received), 0)
        self.http.shutdown()
        self.http.server_close()
        self.assertEqual(self.run_hook("approve", "codex", payload), b"")

    def test_result_minimal_body_and_same_key_as_server(self):
        for agent in ("claude", "codex"):
            approval = json.loads((FIX / f"{agent}-approval.json").read_text())
            result = json.loads((FIX / f"{agent}-result.json").read_text())
            self.assertEqual(self.run_hook("approve", agent, json.dumps(approval).encode()), ALLOW)
            approve_body = self.received[-1][2]
            self.assertEqual(self.run_hook("result", agent, json.dumps(result).encode()), b"")
            path, token, body = self.received[-1]
            self.assertEqual((path, token), ("/api/agent-result", "private-token"))
            self.assertEqual(set(body), {"from", "key", "ok"})
            self.assertTrue(body["ok"])
            server_key = self.server_module.AgentApprovals.result_key(approve_body)
            self.assertEqual(body["key"], list(server_key) if isinstance(server_key, tuple) else server_key)
            server_key = self.server_module.AgentApprovals.result_key({"from": agent, **result})
            self.assertEqual(body["key"], list(server_key) if isinstance(server_key, tuple) else server_key)
            self.assertNotIn("private output", json.dumps(body))

    def test_failure_event_is_not_ok_and_has_no_unprobed_exit(self):
        result = json.loads((FIX / "claude-result.json").read_text())
        result["hook_event_name"] = "PostToolUseFailure"
        result["exit_code"] = 9
        self.assertEqual(self.run_hook("result", "claude", json.dumps(result).encode()), b"")
        self.assertEqual(set(self.received[-1][2]), {"from", "key", "ok"})
        self.assertFalse(self.received[-1][2]["ok"])


if __name__ == "__main__":
    unittest.main()
