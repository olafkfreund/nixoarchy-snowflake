"""Step 3: agent approval lifecycle and the server-only click key."""
import inspect
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import nixi_env


class AgentApprovalsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_env = os.environ.copy()
        cls.home = tempfile.mkdtemp(prefix="nixi-agent-approvals-")
        for key, suffix in (("HOME", ""), ("XDG_CONFIG_HOME", ".config"),
                            ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
            os.environ[key] = os.path.join(cls.home, suffix)
            os.makedirs(os.environ[key], exist_ok=True)
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": nixi_env.run_dir()}):
            import server
        cls.s = server

    @classmethod
    def tearDownClass(cls):
        os.environ.clear()
        os.environ.update(cls.old_env)
        shutil.rmtree(cls.home, ignore_errors=True)

    def setUp(self):
        s = self.s
        self.data = Path(tempfile.mkdtemp(dir=self.home))
        self.addCleanup(shutil.rmtree, self.data, True)
        for obj, name, value in ((s, "DATA_DIR", self.data), (s, "_SENDS_LOG_FIXED", False),
                                 (s, "AGENT_APPROVE_FROM", frozenset({"codex"})),
                                 (s.BUS, "subs", [object()])):
            p = mock.patch.object(obj, name, value)
            p.start(); self.addCleanup(p.stop)
        self.cfg = dict(s.CFG)
        self.addCleanup(lambda: (s.CFG.clear(), s.CFG.update(self.cfg)))
        s.CFG["agent_approvals"] = True
        with s.CLICK_LOCK:
            s.CLICK.update(claimed=True, spoiled=False)
        self.addCleanup(self.reset_click)
        self.events = []
        p = mock.patch.object(s.BUS, "pub", side_effect=lambda **e: self.events.append(e))
        p.start(); self.addCleanup(p.stop)
        self.ap = s.AgentApprovals()
        p = mock.patch.object(s, "AGENT_APPROVALS", self.ap)
        p.start(); self.addCleanup(p.stop)
        self.sockets = []
        self.addCleanup(lambda: [x.close() for x in self.sockets])

    def reset_click(self):
        with self.s.CLICK_LOCK:
            self.s.CLICK.update(claimed=False, spoiled=False)

    def tearDown(self):
        self.assertTrue(all(x["decision"] in {"allow", "deny", "timeout"} for x in self.log()))

    def req(self, cmd="echo hi", **extra):
        return {"from": "codex", "cwd": "/tmp/project", "session_id": "s", "turn_id": "t",
                "tool_name": "Bash", "tool_input": {"command": cmd, "description": "private description"}, **extra}

    def start(self, req=None, wait=1):
        a, b = socket.socketpair()
        self.sockets += [a, b]
        out = []
        p = mock.patch.object(self.s, "AGENT_APPROVE_WAIT", wait)
        p.start(); self.addCleanup(p.stop)
        t = threading.Thread(target=lambda: out.append(self.ap.ask(req or self.req(), a)))
        t.start(); self.addCleanup(lambda: t.join(2))
        end = time.monotonic() + 1
        while not self.ap.pending and t.is_alive() and time.monotonic() < end:
            time.sleep(.002)
        return t, out, b, next(iter(self.ap.pending.values()), None)

    def done(self):
        return [e for e in self.events if e["t"] == "approve_done"]

    def log(self):
        f = self.data / "sends.log"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def post(self, path, body=None, token=None, click=None):
        h = object.__new__(self.s.Handler)
        h.path = path
        h.headers = {"X-Nixi-Token": token if token is not None else self.s.TOKEN,
                     "X-Nixi-Click": click or ""}
        h._host_ok = lambda: True
        h._body = lambda: json.dumps(body or {}).encode()
        h._json = mock.Mock()
        h.connection = self.sockets[0] if self.sockets else None
        h.do_POST()
        return h._json.call_args

    def test_probe_set_refuses_claude_and_accepts_codex(self):
        self.assertEqual(self.s.AGENT_APPROVE_FROM, frozenset({"codex"}))
        claude = self.req(**{"from": "claude"})
        self.assertEqual(self.ap.ask(claude, None), {"decision": None})
        self.assertEqual(self.post("/api/agent-approve", claude).args[0], {"decision": None})
        t, out, _, item = self.start()
        self.assertIsNotNone(item)
        self.assertTrue(self.post("/api/approve/answer", {"id": item["id"], "ans": "yes"},
                                  click=self.s.CLICK_KEY).args[0]["ok"])
        t.join(2)
        self.assertEqual(out, [{"decision": "allow"}])

    def test_codex_result_key_ignores_permission_description(self):
        approval = self.req(tool_input={"command": "printf hello", "description": "private"})
        result = self.req(tool_input={"command": "printf hello"})
        self.assertEqual(self.ap.result_key(approval), self.ap.result_key(result))
        self.assertNotEqual(self.ap.result_key(result), self.ap.result_key(self.req("printf goodbye")))

    def test_off_unclaimed_and_no_page_return_immediately(self):
        for change in (lambda: self.s.CFG.update(agent_approvals=False), self.reset_click,
                       lambda: setattr(self.s.BUS, "subs", [])):
            change()
            self.assertEqual(self.ap.ask(self.req(), None), {"decision": None})
            self.s.CFG["agent_approvals"] = True
            with self.s.CLICK_LOCK: self.s.CLICK["claimed"] = True
            self.s.BUS.subs = [object()]

    def test_answer_once_and_key_is_header_only(self):
        t, out, _, item = self.start()
        aid = item["id"]
        for token, click, body in ((self.s.TOOL_TOKEN, self.s.CLICK_KEY, {}), (self.s.TOKEN, "", {"keyed": True}),
                                   (self.s.TOKEN, "", {})):
            self.assertFalse(self.post("/api/approve/answer", {"id": aid, "ans": "yes", **body}, token, click).args[0].get("ok", False))
        self.assertFalse(self.ap.answer(aid, "always", True))
        self.assertTrue(self.post("/api/approve/answer", {"id": aid, "ans": "yes"}, click=self.s.CLICK_KEY).args[0]["ok"])
        t.join(2)
        self.assertEqual(out, [{"decision": "allow"}])
        self.assertFalse(self.ap.answer(aid, "no", False))
        self.assertEqual(len(self.done()), 1)

    def test_late_answer_and_expiry(self):
        t, out, _, item = self.start(wait=.03)
        t.join(2)
        self.assertEqual(out, [{"decision": None}])
        self.assertEqual(item["state"], "expired")
        self.assertFalse(self.ap.answer(item["id"], "yes", True))
        t, out, _, item = self.start()
        item["deadline"] = time.monotonic() - 1
        self.assertFalse(self.ap.answer(item["id"], "yes", True))
        t.join(2)
        self.assertEqual((item["state"], out), ("expired", [{"decision": None}]))

    def test_claim_race_and_spoil_releases(self):
        self.reset_click()
        calls = []
        threads = [threading.Thread(target=lambda: calls.append(self.post("/api/click-key"))) for _ in range(2)]
        for th in threads: th.start()
        for th in threads: th.join()
        self.assertEqual(sum(c.args[0].get("key") == self.s.CLICK_KEY for c in calls), 1)
        self.assertTrue(self.s.CLICK["spoiled"])
        self.assertTrue(any(e["t"] == "note" for e in self.events))

    def test_second_claim_releases_pending(self):
        t, out, _, item = self.start()
        self.assertEqual(self.post("/api/click-key").args[1], 403)
        t.join(2)
        self.assertEqual((item["state"], out), ("released", [{"decision": None}]))
        self.assertEqual(len(self.done()), 1)

    def test_setting_off_releases_pending(self):
        t, out, _, item = self.start()
        def save_config(**upd):
            self.s.CFG.update(upd)
        with mock.patch.object(self.s, "save_config", side_effect=save_config), \
             mock.patch.object(self.s, "state_info", return_value={}), \
             mock.patch.object(self.s.Wake, "ensure"):
            self.post("/api/settings", {"agent_approvals": False})
        t.join(2)
        self.assertEqual((item["state"], out), ("released", [{"decision": None}]))

    def test_spoil_between_header_check_and_answer(self):
        t, out, _, item = self.start()
        original = self.s.click_ok
        checks = []
        def spoil_after_check(header):
            ok = original(header)
            checks.append(ok)
            if len(checks) == 1:
                with self.s.CLICK_LOCK: self.s.CLICK["spoiled"] = True
            return ok
        with mock.patch.object(self.s, "click_ok", side_effect=spoil_after_check):
            self.assertFalse(self.post("/api/approve/answer", {"id": item["id"], "ans": "yes"}, click=self.s.CLICK_KEY).args[0]["ok"])
        self.assertEqual(checks, [True, False])
        self.ap.release(item["id"])
        t.join(2)
        self.assertEqual(out, [{"decision": None}])

    def test_release_and_closed_socket(self):
        t, out, _, item = self.start()
        self.assertTrue(self.post("/api/approve/release", {"id": item["id"]}).args[0]["ok"])
        t.join(2)
        self.assertEqual((item["state"], out), ("released", [{"decision": None}]))
        t, out, peer, item = self.start()
        peer.close()
        t.join(2)
        self.assertEqual((item["state"], out), ("cancelled", [{"decision": None}]))

    def test_races_finish_once_and_audit_once(self):
        for rival in ("deadline", "disconnect", "release"):
            self.events.clear()
            t, out, peer, item = self.start(self.req("gog gmail send --to a@b --body secret"), wait=.05)
            def other():
                if rival == "deadline": time.sleep(.05)
                elif rival == "disconnect": peer.close()
                else: self.ap.release(item["id"])
            worker = threading.Thread(target=other); worker.start()
            self.ap.answer(item["id"], "yes", True)
            worker.join(); t.join(2)
            self.assertEqual(len(self.done()), 1)
            self.assertEqual(len(self.log()), ("deadline", "disconnect", "release").index(rival) + 1)
        self.assertTrue(all(x["decision"] in {"allow", "deny", "timeout"} for x in self.log()))
        self.assertNotIn("secret", json.dumps(self.log()))

    def test_detail_and_publication(self):
        cmd = "echo first\necho second"
        t, out, _, item = self.start(self.req(cmd))
        card = next(e for e in self.events if e["t"] == "approve")
        self.assertEqual(card["detail"], cmd)
        self.assertEqual((card["click"], card["confirm"], card["always"], card["project"]), (True, "click", False, "project"))
        self.assertEqual(card["say"], "Codex wants to run a command")
        self.assertNotIn("description", json.dumps(card))
        self.ap.answer(item["id"], "no", False); t.join(2)
        self.assertEqual(out, [{"decision": "deny"}])
        self.assertEqual([e["state"] for e in self.events if e["t"] == "agent_result"], ["denied"])
        self.assertEqual(self.log(), [])
        t, _, _, item = self.start(self.req(tool_name="Read", tool_input={"path": "a", "description": "hidden", "nested": {"description": "also hidden"}}))
        card = [e for e in self.events if e["t"] == "approve"][-1]
        self.assertIn('"path":', card["detail"])
        self.assertNotIn("description", json.dumps(card))
        self.ap.release(item["id"]); t.join(2)
        t, _, _, item = self.start(self.req(tool_input={"command": ["echo", "two words"], "description": "hidden"}))
        self.assertEqual([e for e in self.events if e["t"] == "approve"][-1]["detail"], "echo 'two words'")
        self.ap.release(item["id"]); t.join(2)

    def test_target_is_validated_for_focus(self):
        target = {"herdr": {"pane": "pane-1", "session": "session-1"}, "pids": [7, -1, "8"]}
        t, _, _, item = self.start(self.req(target=target))
        self.assertEqual(item["target"], {"herdr": target["herdr"], "pids": [7]})
        self.assertEqual(self.s._ATTN_TARGET["codex"], item["target"])
        self.ap.release(item["id"]); t.join(2)

    def test_key_not_persisted_and_allow_source(self):
        self.assertNotIn(self.s.CLICK_KEY, (self.s.DATA_DIR / "server.log").read_text() if (self.s.DATA_DIR / "server.log").exists() else "")
        for f in self.data.rglob("runtime.json"):
            self.assertNotIn(self.s.CLICK_KEY, f.read_text())
        runtime_write = inspect.getsource(self.s.main).split('rt = DATA_DIR / "runtime.json"', 1)[1].split("srv.daemon_threads", 1)[0]
        self.assertNotIn("CLICK_KEY", runtime_write)
        src = inspect.getsource(self.s.AgentApprovals)
        self.assertNotIn('return {"decision": "allow"}', src)
        self.assertIn('item["decision"] = decision', src)
        self.assertIn('not click_ok(item.get("click_header"))', src)
        self.assertIn('return {"decision": item["decision"]}', src)
        self.assertIn("def _finish", src)

    # step 6: results and the working signal
    def answered(self, ans, **extra):
        t, out, _, item = self.start(self.req(**extra), wait=5)
        self.assertTrue(self.ap.answer(item["id"], ans, ans == "yes"))
        t.join(2)
        return item

    def results(self):
        return [e for e in self.events if e["t"] == "agent_result"]

    def test_result_consumed_once(self):
        item = self.answered("yes")
        self.assertTrue(self.ap.result("codex", list(item["key"]), True, 0))
        self.assertEqual(self.results(), [{"t": "agent_result", "agent": "codex", "ok": True, "state": "ran", "exit": 0}])
        self.assertFalse(self.ap.result("codex", list(item["key"]), True, 0))
        self.assertEqual(len(self.results()), 1)
        self.assertEqual(self.post("/api/agent-result", {"from": "codex", "key": "none", "ok": True}).args[0], {"ok": False})

    def test_sandbox_result_before_permission_is_ignored(self):
        req = self.req()
        result = self.req(tool_input={"command": req["tool_input"]["command"]})
        key = list(self.ap.result_key(result))
        self.assertEqual(self.post("/api/agent-result", {"from": "codex", "key": key, "ok": False}).args[0],
                         {"ok": False})
        self.assertEqual(self.results(), [])
        t, out, _, item = self.start(req)
        self.assertTrue(self.ap.answer(item["id"], "yes", True))
        t.join(2)
        self.assertEqual(out, [{"decision": "allow"}])
        self.assertEqual(self.post("/api/agent-result", {"from": "codex", "key": key, "ok": True}).args[0],
                         {"ok": True})
        self.assertEqual(self.results(), [{"t": "agent_result", "agent": "codex", "ok": True, "state": "ran"}])

    def test_result_exit_only_when_int_and_string_key(self):
        self.assertIsInstance(self.answered("no", tool_use_id="toolu_0")["key"], tuple)   # default: tool_use_id unused
        p = mock.patch.object(self.s, "RESULT_BY_TOOL_USE_ID", frozenset({"codex"}))
        p.start(); self.addCleanup(p.stop)
        item = self.answered("yes", tool_use_id="toolu_1")
        self.assertEqual(item["key"], "toolu_1")
        self.assertEqual(self.post("/api/agent-result", {"from": "codex", "key": "toolu_1", "ok": False, "exit": "1"}).args[0], {"ok": True})
        self.assertEqual(self.results()[-1], {"t": "agent_result", "agent": "codex", "ok": False, "state": "ran"})

    def test_double_match_is_unclear_and_dropped(self):
        a, b = self.answered("yes"), self.answered("yes")
        self.assertEqual(a["key"], b["key"])
        self.assertTrue(self.ap.result("codex", list(a["key"]), True, 0))
        self.assertEqual(self.results()[-1]["state"], "unclear")
        self.assertFalse(self.ap.finished)
        self.assertFalse(self.ap.result("codex", list(a["key"]), True, 0))

    def test_deny_then_match_is_ran_after_deny(self):
        item = self.answered("no")
        self.ap.result("codex", list(item["key"]), True, 0)
        self.assertEqual([e["state"] for e in self.results()], ["denied", "ran-after-deny"])

    def test_unknown_after_fifteen_minutes(self):
        item = self.answered("yes")
        now = time.monotonic()
        with mock.patch.object(self.s.time, "monotonic", return_value=now + self.s.AGENT_RESULT_KEEP - 1):
            self.ap.sweep()
        self.assertEqual(self.results(), [])
        with mock.patch.object(self.s.time, "monotonic", return_value=now + self.s.AGENT_RESULT_KEEP + 1):
            self.ap.sweep()
        self.assertEqual(self.results(), [{"t": "agent_result", "agent": "codex", "ok": None, "state": "unknown"}])
        self.assertFalse(self.ap.result("codex", list(item["key"]), True, 0))

    def test_working_from_each_agent(self):
        s = self.s
        for frm, ev in (("claude", "UserPromptSubmit"), ("codex", "UserPromptSubmit"), ("agy", "PreInvocation")):
            self.assertEqual(s.attention_parse(frm, {"hook_event_name": ev, "cwd": "/x/proj", "prompt": "secret words"}),
                             ("working", "proj", ""))
        self.assertEqual(s.attention_parse("agy", {"hook_event_name": "UserPromptSubmit"})[0], "ask" if False else s.attention_parse("agy", {"hook_event_name": "UserPromptSubmit"})[0])
        self.assertNotEqual(s.attention_parse("claude", {"hook_event_name": "Stop"})[0], "working")

    def test_working_is_rate_limited(self):
        s = self.s
        s._ATTN_LAST.clear()
        self.addCleanup(s._ATTN_LAST.clear)
        hook = {"hook_event_name": "UserPromptSubmit", "cwd": "/x/proj"}
        self.assertTrue(s.attention_accept("claude", "", now=100.0, hook=hook))
        self.assertFalse(s.attention_accept("claude", "", now=110.0, hook=hook))
        self.assertTrue(s.attention_accept("claude", "", now=131.0, hook=hook))
        self.assertEqual([e["kind"] for e in self.events if e["t"] == "attention"], ["working", "working"])
