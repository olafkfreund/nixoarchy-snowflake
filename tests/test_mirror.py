import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent

# the fake ai-mirror: logs its argv, then prints/exits as the files in $FAKE say ("<cmd>.out", ".err", ".rc"; no .rc = 0)
FAKE = """#!/bin/sh
echo "$*" >> "$FAKE/log"
c=$(echo "$*" | tr ' ' '_')
[ -f "$FAKE/$c.err" ] && cat "$FAKE/$c.err" >&2
[ -f "$FAKE/$c.out" ] && cat "$FAKE/$c.out"
[ -f "$FAKE/$c.rc" ] && exit "$(cat "$FAKE/$c.rc")"
exit 0
"""


class MirrorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_env = os.environ.copy()
        cls.tmp = tempfile.mkdtemp(prefix="nixi-mirror-test-")
        for k, d in (("HOME", ""), ("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
            os.environ[k] = os.path.join(cls.tmp, d)
            os.makedirs(os.environ[k], exist_ok=True)
        sys.path.insert(0, str(REPO_ROOT / "app"))
        import quick
        import server
        cls.s, cls.q = server, quick

    @classmethod
    def tearDownClass(cls):
        os.environ.clear()
        os.environ.update(cls._orig_env)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(dir=self.tmp))
        self.bin, self.fake, self.run = self.d / "bin", self.d / "fake", self.d / "run"
        for p in (self.bin, self.fake, self.run / "ai-mirror"):
            p.mkdir(parents=True)
        exe = self.bin / "ai-mirror"
        exe.write_text(FAKE)
        exe.chmod(0o755)
        tools = self.d / "tools"       # a PATH of its own, so the real ai-mirror can never be found
        tools.mkdir()
        for t in ("sh", "tr", "cat"):
            (tools / t).symlink_to(shutil.which(t, path=self._orig_env["PATH"]))
        os.environ["PATH"] = f"{self.bin}{os.pathsep}{tools}"
        os.environ["FAKE"] = str(self.fake)
        os.environ["XDG_RUNTIME_DIR"] = str(self.run)
        M = self.s.Mirror
        M.state, M.installed, M.checked, M.stamp, M.last_status, M.expires = {"owner": None, "watching": False}, False, 0.0, None, 0.0, None
        M.retry_at, M.revokes = None, 0
        bus = mock.patch.object(self.s, "BUS")
        self.bus = bus.start()
        self.addCleanup(bus.stop)
        self.t = [1000.0]          # one clock for both time.time and time.monotonic
        for name in ("time", "monotonic"):
            p = mock.patch.object(self.s.time, name, lambda: self.t[0])
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    # ---- helpers
    def state_file(self, owner="off", **extra):
        f = self.run / "ai-mirror" / "state.json"
        f.write_text(json.dumps({"owner": owner, **extra}))
        os.utime(f, ns=(self.t[0] and int(self.t[0] * 1e9), int(self.t[0] * 1e9) + self.n()))
        return f

    def n(self, _c=[0]):
        _c[0] += 1000
        return _c[0]

    def fakeout(self, cmd, out=None, rc=None, err=None):
        for ext, v in (("out", out), ("rc", rc), ("err", err)):
            if v is not None:
                (self.fake / f"{cmd}.{ext}").write_text(str(v))

    def calls(self):
        f = self.fake / "log"
        return f.read_text().splitlines() if f.exists() else []

    def watching(self, age):
        (self.run / "ai-mirror" / "watching").write_text(str(self.t[0] - age))

    def tick(self):
        self.s.Mirror.tick()
        return self.s.Mirror.snapshot()

    def test_grant_read_during_a_failed_revoke_is_not_lost(self):
        """Codex on PR #28: a status answer discarded because a revoke landed (and failed) must be asked for again."""
        self.state_file("off")
        self.fakeout("status", '{"owner":"off"}')
        self.assertEqual(self.tick()["owner"], "off")
        self.state_file("agent")                       # a grant arrives...
        self.fakeout("status", '{"owner":"agent"}')
        orig_run = self.s.subprocess.run
        def run(argv, *a, **k):                        # ...and a revoke lands (and fails) while that status runs
            if argv == self.s.MIRROR_STATUS and not getattr(run, "done", False):
                run.done = True
                self.s.Mirror.revokes += 1
            return orig_run(argv, *a, **k)
        with mock.patch.object(self.s.subprocess, "run", run):
            self.tick()                                # this answer is discarded...
        self.t[0] += 1
        self.assertEqual(self.tick()["owner"], "agent")   # ...but the next tick asks again and shows the grant

    def test_both_sources_failing_on_a_grant_retry_while_cached_off(self):
        """Codex on PR #28: off → agent, but status and the file both fail once: it must ask again soon, though it shows off."""
        self.state_file("off")
        self.fakeout("status", '{"owner":"off"}')
        self.assertEqual(self.tick()["owner"], "off")
        self.state_file("agent")
        self.fakeout("status", "", rc=1)              # status fails...
        real = Path.read_text
        def deny(p, *a, **k):                         # ...and the file can't be read either (mocked: chmod means nothing to root)
            if p.name == "state.json":
                raise PermissionError(p)
            return real(p, *a, **k)
        with mock.patch.object(Path, "read_text", deny):
            self.assertEqual(self.tick()["owner"], "off")
        self.fakeout("status", '{"owner":"agent"}', rc=0)
        self.t[0] += 6                                # past the 5 s retry
        self.assertEqual(self.tick()["owner"], "agent")

    # ---- tick: nothing to read
    def test_none_without_cli(self):
        os.environ["PATH"] = str(self.d / "empty")
        self.state_file("agent")
        self.assertEqual(self.tick(), {"owner": None, "watching": False})

    def test_none_without_runtime_dir(self):
        del os.environ["XDG_RUNTIME_DIR"]
        self.assertEqual(self.tick(), {"owner": None, "watching": False})

    def test_missing_state_reads_off_and_watching_works(self):
        self.watching(2)
        self.assertEqual(self.tick(), {"owner": "off", "watching": True})
        self.assertEqual(self.calls(), [])

    def test_watching_boundary_at_10s(self):
        self.state_file("off")
        self.fakeout("status", '{"owner":"off"}')
        for age, want in ((9.9, True), (10, False), (-0.5, True), (-1.5, False)):   # (ai-mirror rounds to the second: up to 1 s ahead is fresh)
            self.watching(age)
            self.assertIs(self.tick()["watching"], want, age)

    def test_unreadable_watching_is_false(self):
        self.state_file("off")
        (self.run / "ai-mirror" / "watching").write_text("soon")
        self.assertIs(self.tick()["watching"], False)

    def test_unknown_owner_is_none(self):
        self.state_file("root")
        self.fakeout("status", '{"owner":"root"}')
        self.assertIsNone(self.tick()["owner"])

    # ---- tick: when status runs
    def test_status_on_change_not_every_tick(self):
        self.state_file("agent")
        self.fakeout("status", '{"owner":"agent"}')
        self.assertEqual(self.tick()["owner"], "agent")
        self.assertEqual(self.calls(), ["status"])
        self.t[0] += 5
        self.tick()
        self.tick()
        self.assertEqual(self.calls(), ["status"])           # held, but not 30 s yet, file unchanged
        self.state_file("agent")                              # stat changed
        self.tick()
        self.assertEqual(self.calls(), ["status"] * 2)

    def test_status_every_30s_while_held_never_while_off(self):
        self.state_file("agent")
        self.fakeout("status", '{"owner":"agent"}')
        self.tick()
        self.t[0] += 29
        self.tick()
        self.assertEqual(len(self.calls()), 1)
        self.t[0] += 1
        self.tick()
        self.assertEqual(len(self.calls()), 2)
        self.state_file("off")
        self.fakeout("status", '{"owner":"off"}')
        self.tick()
        n = len(self.calls())
        self.t[0] += 100
        self.tick()
        self.assertEqual(len(self.calls()), n)

    def test_expired_pending_becomes_off(self):
        self.state_file("pending")
        self.fakeout("status", json.dumps({"owner": "pending", "request": {"expires": self.t[0] + 20}}))
        self.assertEqual(self.tick()["owner"], "pending")
        self.t[0] += 21
        self.tick()                                           # expiry triggers a status, which still says pending
        self.assertEqual(self.calls(), ["status"] * 2)
        self.assertEqual(self.s.Mirror.snapshot()["owner"], "off")

    def test_status_wins_over_file_but_failure_falls_back_to_file(self):
        self.state_file("agent")
        self.fakeout("status", '{"owner":"off"}')
        self.assertEqual(self.tick()["owner"], "off")
        self.fakeout("status", rc=1)
        self.state_file("agent")
        self.assertEqual(self.tick()["owner"], "agent")       # status failed: the file stands

    def test_both_failing_keeps_last_state(self):
        f = self.state_file("agent")
        self.fakeout("status", '{"owner":"agent"}')
        self.tick()
        self.fakeout("status", "garbage", rc=0)
        f.write_text("not json")
        os.utime(f, ns=(1, 2))                                # changed, unreadable
        self.assertEqual(self.tick()["owner"], "agent")
        self.assertEqual(self.bus.pub.call_count, 1)

    def test_cli_recheck_after_60s(self):
        self.state_file("agent")
        self.fakeout("status", '{"owner":"agent"}')
        self.assertEqual(self.tick()["owner"], "agent")
        (self.bin / "ai-mirror").unlink()
        self.t[0] += 59
        self.assertEqual(self.tick()["owner"], "agent")       # not looked for yet
        self.t[0] += 1
        self.assertEqual(self.tick(), {"owner": None, "watching": False})

    def test_publish_only_on_change(self):
        M = self.s.Mirror
        M.publish("agent", False)
        M.publish("agent", False)
        self.assertEqual(self.bus.pub.call_count, 1)
        self.bus.pub.assert_called_with(t="mirror", owner="agent", watching=False)
        M.publish("agent", True)
        self.assertEqual(self.bus.pub.call_count, 2)
        M.publish("bogus", True)
        self.assertIsNone(M.snapshot()["owner"])

    # ---- revoke
    def test_revoke_argv_and_success(self):
        self.fakeout("control_off", '{"owner":"off"}')
        self.assertEqual(self.s.MIRROR_OFF, ["ai-mirror", "control", "off"])
        self.assertEqual(self.s.Mirror.revoke(), {"ok": True})
        self.assertEqual(self.calls(), ["control off"])
        self.assertEqual(self.s.Mirror.snapshot(), {"owner": "off", "watching": False})

    def test_revoke_exit_0_but_not_off_fails(self):
        self.fakeout("control_off", '{"owner":"agent"}')
        self.assertFalse(self.s.Mirror.revoke()["ok"])

    def test_revoke_exit_1_with_off_fails(self):
        self.fakeout("control_off", '{"owner":"off"}', rc=1)
        self.assertFalse(self.s.Mirror.revoke()["ok"])

    def test_revoke_failure_message_from_stdout_json(self):
        self.fakeout("control_off", '{"error":{"message":"no daemon"}}', rc=1)
        self.assertEqual(self.s.Mirror.revoke(), {"ok": False, "error": "no daemon"})

    def test_revoke_failure_message_from_stderr_and_truncated(self):
        self.fakeout("control_off", rc=1, err="first\n" + "x" * 300 + "\n")
        r = self.s.Mirror.revoke()
        self.assertEqual((r["ok"], r["error"]), (False, "x" * 200))

    def test_revoke_without_cli(self):
        os.environ["PATH"] = str(self.d / "empty")
        r = self.s.Mirror.revoke()
        self.assertFalse(r["ok"])
        self.assertTrue(r["error"])

    # ---- source
    def test_no_agent_confirm_deny_in_ai_mirror_argv(self):
        src = (REPO_ROOT / "app" / "server.py").read_text()
        for m in re.finditer(r"\[\s*[\"']ai-mirror[\"'][^\]]*\]", src):
            self.assertFalse(re.search(r"[\"'](agent|confirm|deny)[\"']", m.group(0)), m.group(0))

    # ---- /api/quick: do_POST has no harness, so the phrases and the handler's branches are checked here
    def test_quick_phrases(self):
        for p in ("take control back", "stop the agent", "revoke control", "give me my desktop back"):
            self.assertEqual(self.q.handle(p), {"mirror": "off"}, p)

    def test_quick_handler_branches_in_source(self):
        src = (REPO_ROOT / "app" / "server.py").read_text()
        for s in ('"say": "Control is back with you.", "mood": "happy", "sfx": "ok"',
                  '"say": "I couldn\'t take it back — press Super, Shift and Escape.", "mood": "sad", "sfx": "error"',
                  '"say": "No agent is controlling the mouse and keyboard through ai-mirror.", "mood": "curious"',
                  'Mirror.live_owner() == "off"', "Mirror.revoke()[\"ok\"]"):
            self.assertIn(s, src)

    def test_state_info_carries_mirror(self):
        self.s.Mirror.publish("pending", True)
        with mock.patch.object(self.s.quick, "projects", return_value={}):
            self.assertEqual(self.s.state_info()["mirror"], {"owner": "pending", "watching": True})


if __name__ == "__main__":
    unittest.main()
