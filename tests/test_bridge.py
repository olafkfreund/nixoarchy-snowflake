import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NIXI_SRC = Path(os.environ["NIXI_SRC"]) if os.environ.get("NIXI_SRC") else None
HAVE_BRIDGE = bool(
    NIXI_SRC
    and (NIXI_SRC / "bridge" / "bridge.js").is_file()
    and (NIXI_SRC / "bridge" / "testing" / "fake-agent.js").is_file()
    and (NIXI_SRC / "bridge" / "node_modules").is_dir()
    and shutil.which("node")
)


def _close_pipes(proc):
    if not proc:
        return
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        if stream:
            try:
                stream.close()
            except OSError:
                pass


@unittest.skipUnless(HAVE_BRIDGE, "requires NIXI_SRC with bridge/node_modules and node")
class BridgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_env = os.environ.copy()
        cls.tmp = Path(tempfile.mkdtemp(prefix="void-bridge-test-"))
        home = cls.tmp / "home"
        config_home = home / ".config"
        data_home = home / ".local" / "share"
        state_home = home / ".local" / "state"
        bin_dir = cls.tmp / "bin"
        for d in (home, config_home / "omarchy", data_home, state_home, bin_dir):
            d.mkdir(parents=True, exist_ok=True)

        for name in ("claude", "codex", "opencode"):
            stub = bin_dir / name
            stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            stub.chmod(0o700)

        (config_home / "omarchy" / "nixi.json").write_text(
            json.dumps({"agent": "claude", "trust": "mechanic"}),
            encoding="utf-8",
        )

        cls.agent_log = cls.tmp / "agent.log"
        os.environ["HOME"] = str(home)
        os.environ["XDG_CONFIG_HOME"] = str(config_home)
        os.environ["XDG_DATA_HOME"] = str(data_home)
        os.environ["XDG_STATE_HOME"] = str(state_home)
        os.environ["PATH"] = f"{bin_dir}:{os.environ.get('PATH', '')}"
        os.environ["NIXI_ACP_COMMAND"] = json.dumps(
            ["node", str(NIXI_SRC / "bridge" / "testing" / "fake-agent.js")]
        )
        os.environ["FAKE_AGENT_LOG"] = str(cls.agent_log)
        os.environ["NIXI_CONTEXT_COMMAND"] = json.dumps(
            [str(cls.tmp / "no-such-nixi-context")]
        )

        app_dir = str(REPO_ROOT / "app")
        if app_dir not in sys.path:
            sys.path.insert(0, app_dir)
        import server

        cls.server = server
        cls.server.ST.cwd = str(home)
        cls.server.NIXI_BRIDGE = json.dumps(
            ["node", str(NIXI_SRC / "bridge" / "bridge.js")]
        )
        cls.server.BRIDGED = cls.server.bridge_argv() is not None

    @classmethod
    def tearDownClass(cls):
        p = cls.server.BRIDGE.proc
        try:
            cls.server.BRIDGE.close()
        finally:
            _close_pipes(p)
            os.environ.clear()
            os.environ.update(cls._orig_env)
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.server.ST.stopped = False
        self.server.APPROVALS.cancel_all()

    def _read_agent_log(self):
        if not self.agent_log.exists():
            return []
        return [
            json.loads(line)
            for line in self.agent_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_1_text_streams_as_delta(self):
        events = []
        res = self.server.run_bridge("hello", lambda **kw: events.append(kw))
        self.assertEqual(res, "done")
        deltas = [e.get("text") for e in events if e.get("t") == "delta"]
        self.assertEqual("".join(deltas), "ok")
        self.assertTrue(any(e.get("t") == "result" and not e.get("is_error") for e in events))

    def test_2_permission_yes_sends_allow_once(self):
        before = len(self._read_agent_log())

        def approve_yes():
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                with self.server.APPROVALS.lock:
                    aids = list(self.server.APPROVALS.pending.keys())
                if aids:
                    self.server.APPROVALS.answer(aids[0], "yes")
                    return
                time.sleep(0.02)

        t = threading.Thread(target=approve_yes, daemon=True)
        t.start()
        events = []
        res = self.server.run_bridge("PLEASE_WRITE", lambda **kw: events.append(kw))
        t.join(timeout=2.0)
        self.assertEqual(res, "done")

        new_entries = self._read_agent_log()[before:]
        outcomes = [e["outcome"] for e in new_entries if e.get("method") == "permissionOutcome"]
        self.assertEqual(outcomes, [{"outcome": "selected", "optionId": "allow"}])
        self.assertEqual(self.server.APPROVALS.always, set())

    def test_3_stop_proc_cancels_turn(self):
        before = len(self._read_agent_log())

        def stop_when_pending():
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                with self.server.APPROVALS.lock:
                    has_pending = bool(self.server.APPROVALS.pending)
                if has_pending:
                    self.server.stop_proc()
                    return
                time.sleep(0.02)

        t = threading.Thread(target=stop_when_pending, daemon=True)
        t.start()
        events = []
        res = self.server.run_bridge("PLEASE_WRITE", lambda **kw: events.append(kw))
        t.join(timeout=2.0)
        self.assertEqual(res, "done")
        self.assertTrue(any(e.get("t") == "stopped" for e in events), f"expected stopped in {events}")

        new_entries = self._read_agent_log()[before:]
        self.assertTrue(
            any(e.get("method") == "cancel" for e in new_entries)
            or any(
                e.get("method") == "permissionOutcome"
                and e.get("outcome") in (
                    {"outcome": "cancelled"},
                    {"outcome": "selected", "optionId": "reject"},
                )
                for e in new_entries
            ),
            f"expected cancel/reject in agent log, got {new_entries}",
        )

    def test_4_dead_bridge_restarts_on_next_prompt(self):
        p1 = self.server.BRIDGE.start()
        pid1 = p1.pid
        sessions_before = sum(1 for e in self._read_agent_log() if e.get("method") == "newSession")

        p1.kill()
        p1.wait(timeout=5.0)
        _close_pipes(p1)
        self.assertFalse(self.server.BRIDGE.alive())

        events = []
        res = self.server.run_bridge("hello", lambda **kw: events.append(kw))
        self.assertEqual(res, "done")
        p2 = self.server.BRIDGE.proc
        self.assertIsNotNone(p2)
        self.assertTrue(self.server.BRIDGE.alive())
        self.assertNotEqual(p2.pid, pid1)

        self.assertEqual("".join(e.get("text", "") for e in events if e.get("t") == "delta"), "ok")
        sessions_after = sum(1 for e in self._read_agent_log() if e.get("method") == "newSession")
        self.assertGreater(sessions_after, sessions_before)


if __name__ == "__main__":
    unittest.main()
