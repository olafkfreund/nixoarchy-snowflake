import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
CMD = "nix profile install nixpkgs#firefox"
OPTS = [{"id": "a1", "kind": "allow_once"}, {"id": "r1", "kind": "reject_once"}, {"id": "r2", "kind": "reject_always"}]


class StageActionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_env = os.environ.copy()
        cls.tmp = tempfile.mkdtemp(prefix="nixi-stageact-test-")
        for k, d in (("HOME", ""), ("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
            os.environ[k] = os.path.join(cls.tmp, d)
            os.makedirs(os.environ[k], exist_ok=True)
        sys.path.insert(0, str(REPO_ROOT / "app"))
        import server
        import stages
        cls.server, cls.stages = server, stages

    @classmethod
    def tearDownClass(cls):
        os.environ.clear()
        os.environ.update(cls._orig_env)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.s = self.server
        self.page = self.s.STAGES.put(self.stages.validate(
            {"v": 1, "kind": "commands", "items": [{"label": "Install", "cmd": CMD}, {"label": "Try", "cmd": "nix run nixpkgs#firefox"}]}))
        self.tok = self.page["items"][0]["token"]
        self.s.STAGES.set_visible(True)                       # the page drew it

    def tearDown(self):
        self.s.ST.stage_run = self.s.ST.stage_run_tok = None

    # ---- the byte-exact check, through run_bridge's real approve()
    def permission(self, perm, stage_run):
        sent, events = [], []
        lines = [json.dumps({"type": "permission", "id": 7, "title": "Bash", "options": OPTS, **perm}) + "\n"]
        p = mock.Mock(stdout=iter(lines + [json.dumps({"type": "done"}) + "\n"]))
        ask = mock.Mock(return_value="a1")
        self.s.ST.stage_run, self.s.ST.stage_run_tok = stage_run, "tk"
        with mock.patch.object(self.s.BRIDGE, "start", return_value=p), mock.patch.object(self.s.BRIDGE, "send", lambda m: sent.append(m)), \
                mock.patch.object(self.s.BRIDGE, "proc", p), mock.patch.object(self.s.APPROVALS, "ask_bridge", ask):
            self.s.run_bridge("x", lambda **kw: events.append(kw))
            for _ in range(100):                                  # (approve is a worker thread)
                if len(sent) > 1 or ask.called:
                    break
                time.sleep(0.02)
        return [m for m in sent if m.get("type") == "permission"], events, ask

    def test_mismatch_denied_with_reject_once(self):
        sent, events, ask = self.permission({"command": CMD + " && rm -rf ~"}, CMD)
        self.assertEqual(sent, [{"type": "permission", "id": 7, "optionId": "r1"}])
        self.assertFalse(ask.called)
        self.assertIn({"t": "stage_status", "state": "other", "token": "tk"}, events)

    def test_missing_command_denied(self):
        sent, events, ask = self.permission({}, CMD)
        self.assertEqual([m["optionId"] for m in sent], ["r1"])
        self.assertFalse(ask.called)

    def test_exact_match_shows_the_card(self):
        sent, events, ask = self.permission({"command": CMD}, CMD)
        self.assertTrue(ask.called)
        self.assertEqual([m["optionId"] for m in sent], ["a1"])

    def test_no_reject_option_sends_nothing(self):
        global OPTS
        saved, OPTS = OPTS, [{"id": "a1", "kind": "allow_once"}]
        try:
            sent, events, ask = self.permission({"command": "other"}, CMD)
        finally:
            OPTS = saved
        self.assertEqual(sent, [])
        self.assertIn({"t": "stage_status", "state": "other", "token": "tk"}, events)

    def test_not_a_stage_run_unchanged(self):
        sent, _, ask = self.permission({"command": "anything"}, None)
        self.assertTrue(ask.called)

    # ---- actions
    def test_copy_sends_exact_bytes(self):
        with mock.patch.object(self.s.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            self.assertEqual(self.s.stage_act(self.tok, "copy"), {"ok": True})
        self.assertEqual(run.call_args[0][0], ["wl-copy"])
        self.assertEqual(run.call_args[1]["input"], CMD.encode())
        self.assertNotIn("shell", run.call_args[1])

    def test_stale_or_foreign_token_refused(self):
        old = self.tok
        self.s.STAGES.put(self.stages.validate({"v": 1, "kind": "facts", "title": "t", "points": ["p"]}))
        with mock.patch.object(self.s.subprocess, "run") as run:
            for tk in (old, "made-up", ""):
                self.assertFalse(self.s.stage_act(tk, "copy")["ok"])
        self.assertFalse(run.called)

    def test_open_play_not_yet_and_unknown(self):
        self.assertEqual(self.s.stage_act(self.tok, "open")["error"], "not yet")
        self.assertFalse(self.s.stage_act(self.tok, "run")["ok"])
        self.assertFalse(self.s.stage_act("nope", "open")["ok"])

    def test_close_and_back(self):
        self.s.STAGES.put(self.stages.validate({"v": 1, "kind": "facts", "title": "t", "points": ["p"]}))
        self.assertTrue(self.s.stage_act("", "back")["ok"])
        self.assertEqual(self.s.STAGES.current()["kind"], "commands")
        self.assertTrue(self.s.stage_act("", "close")["ok"])
        self.assertIsNone(self.s.STAGES.current())

    # ---- /api/ask: Run and the fast path
    def ask(self, body, bridged=True, tool=True, deltas=("done.",)):
        s = self.s
        prompts = []

        def fake_bridge(prompt, emit, *_):
            prompts.append((prompt, s.ST.stage_run))
            if tool:
                emit(t="tool", name="Bash", detail="", id="", input=None)
            for d in deltas:
                emit(t="delta", text=d)
            emit(t="result", text="", is_error=False)
            return "done"

        h = s.Handler.__new__(s.Handler)
        h.wfile = io.BytesIO()
        h.send_response, h.send_header, h.end_headers = mock.Mock(), mock.Mock(), mock.Mock()
        h._body = lambda: json.dumps(body).encode()
        h._json = mock.Mock()
        with mock.patch.object(s, "BRIDGED", bridged), mock.patch.object(s, "run_bridge", fake_bridge), \
                mock.patch.object(s, "hist_add"), mock.patch.object(s, "pick_auto", return_value=None), \
                mock.patch.object(s.recall, "add"), mock.patch.dict(s.CFG, {"auto_compact": False}):
            h.ask()
        evs = [json.loads(x[6:]) for x in h.wfile.getvalue().decode().split("\n\n") if x.startswith("data: ")]
        return evs, prompts, h._json

    def test_run_uses_the_stored_command_and_reports_status(self):
        evs, prompts, _ = self.ask({"stage": self.tok, "act": "run", "prompt": "rm -rf /", "cmd": "rm -rf /"})
        self.assertEqual(prompts, [("Run exactly this one command and nothing else: " + CMD, CMD)])
        self.assertEqual([e["state"] for e in evs if e["t"] == "stage_status"], ["waiting", "running", "done"])
        self.assertTrue(all(e["token"] == self.tok for e in evs if e["t"] == "stage_status"))
        self.assertIsNone(self.s.ST.stage_run)                    # cleared afterwards

    def test_run_with_bad_token_refused_no_turn(self):
        evs, prompts, j = self.ask({"stage": "forged", "act": "run"})
        self.assertEqual(prompts, [])
        self.assertEqual(j.call_args[0][1], 410)

    def test_fast_path_run_first_one(self):
        evs, prompts, _ = self.ask({"prompt": "Run the first one."})
        self.assertEqual(prompts[0][1], CMD)
        self.assertEqual(prompts[0][0], "Run exactly this one command and nothing else: " + CMD)

    def test_fast_path_ask_which_and_no_stage_falls_through(self):
        evs, prompts, _ = self.ask({"prompt": "copy that"})
        self.assertEqual(prompts, [])
        self.assertIn("Which one", evs[0]["text"])
        self.s.STAGES.close()
        evs, prompts, _ = self.ask({"prompt": "run the first one"})
        self.assertEqual(len(prompts), 1)
        self.assertIsNone(prompts[0][1])                          # an ordinary turn, nothing to byte-check

    def test_fast_path_copy_and_close(self):
        with mock.patch.object(self.s.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            evs, prompts, _ = self.ask({"prompt": "copy the second one"})
        self.assertEqual(run.call_args[1]["input"], b"nix run nixpkgs#firefox")
        self.assertEqual((prompts, evs[0]["text"]), ([], "Copied."))
        evs, prompts, _ = self.ask({"prompt": "close"})
        self.assertEqual(prompts, [])
        self.assertIsNone(self.s.STAGES.current())

    # ---- review fixes
    def test_acts_shown_and_hidden_drive_visibility(self):
        self.s.STAGES.put(self.stages.validate({"v": 1, "kind": "facts", "title": "t", "points": ["p"]}))
        self.assertFalse(self.s.STAGES.visible())
        self.s.stage_act("", "shown")
        self.assertTrue(self.s.STAGES.visible())
        self.s.stage_act("", "hidden")
        self.assertFalse(self.s.STAGES.visible())

    def test_fast_path_needs_a_stage_that_is_on_screen(self):
        self.s.STAGES.set_visible(False)
        with mock.patch.object(self.s.subprocess, "run") as run:
            evs, prompts, _ = self.ask({"prompt": "run the first one"})
            self.assertEqual((len(prompts), prompts[0][1]), (1, None))     # an ordinary agent turn
            evs, prompts, _ = self.ask({"prompt": "copy the first one"})
            self.assertFalse(run.called)
            self.assertEqual(len(prompts), 1)

    def test_stage_event_carries_has_prev_and_trust(self):
        ev = self.s.stage_event(self.page)
        self.assertTrue(ev["has_prev"] in (True, False) and "trust" in ev and ev["kind"] == "commands")
        self.s.STAGES.put(self.stages.validate({"v": 1, "kind": "facts", "title": "t", "points": ["p"]}))
        self.assertTrue(self.s.stage_event({"kind": "facts"})["has_prev"])

    def test_done_needs_a_tool_event(self):
        evs, _, _ = self.ask({"stage": self.tok, "act": "run"}, tool=False)
        st = [e for e in evs if e["t"] == "stage_status"]
        self.assertEqual([e["state"] for e in st], ["waiting", "failed"])
        self.assertEqual(st[1]["error"], "Nixi didn't run it")

    def test_no_running_after_other_and_no_done(self):
        s = self.s

        def fake(prompt, emit, *_):
            emit(t="stage_status", state="other", token=self.tok)
            emit(t="tool", name="Bash", detail="", id="", input=None)
            emit(t="result", text="", is_error=False)
            return "done"

        h = s.Handler.__new__(s.Handler)
        h.wfile = io.BytesIO()
        h.send_response, h.send_header, h.end_headers = mock.Mock(), mock.Mock(), mock.Mock()
        h._body = lambda: json.dumps({"stage": self.tok, "act": "run"}).encode()
        with mock.patch.object(s, "run_bridge", fake), mock.patch.object(s, "BRIDGED", True), mock.patch.object(s, "hist_add"), \
                mock.patch.object(s, "pick_auto", return_value=None), mock.patch.object(s.recall, "add"), mock.patch.dict(s.CFG, {"auto_compact": False}):
            h.ask()
        states = [json.loads(x[6:]).get("state") for x in h.wfile.getvalue().decode().split("\n\n") if x.startswith("data: ") and '"stage_status"' in x]
        self.assertEqual(states, ["waiting", "other"])

    def test_no_reject_option_stops_the_turn(self):
        global OPTS
        saved, OPTS = OPTS, [{"id": "a1", "kind": "allow_once"}]
        try:
            with mock.patch.object(self.s, "stop_proc") as stop:
                self.permission({"command": "other"}, CMD)
        finally:
            OPTS = saved
        self.assertTrue(stop.called)

    def test_run_ignores_attachments(self):
        with mock.patch.object(self.s, "attach_prompt", return_value="") as ap:
            self.ask({"stage": self.tok, "act": "run", "attach": [{"kind": "window", "label": "x"}]})
        ap.assert_called_once_with([])

    def test_run_asks_for_no_stage_block_and_drops_one(self):
        block = '\n<<stage>>{"v":1,"kind":"facts","title":"t","points":["p"]}'
        before = self.s.STAGES.current()
        evs, _, _ = self.ask({"stage": self.tok, "act": "run"}, deltas=("ok." + block,))
        self.assertNotIn("stage", [e["t"] for e in evs])
        self.assertNotIn("<<stage", json.dumps(evs))
        self.assertEqual(self.s.STAGES.current(), before)
        sent = []
        p = mock.Mock(stdout=iter([json.dumps({"type": "done"}) + "\n"]))
        for run, want in ((CMD, False), (None, True)):
            self.s.ST.stage_run = run
            with mock.patch.object(self.s.BRIDGE, "start", return_value=p), mock.patch.object(self.s.BRIDGE, "send", lambda m: sent.append(m)):
                p.stdout = iter([json.dumps({"type": "done"}) + "\n"])
                self.s.run_bridge("x", lambda **kw: None)
            self.assertEqual("<<stage>>" in sent[-1]["text"], want)

    def test_run_does_not_change_last_you(self):
        self.s.ST.last_you = "how do I install firefox?"
        self.ask({"stage": self.tok, "act": "run", "prompt": "Install it", "you": "Install it"})
        self.assertEqual(self.s.ST.last_you, "how do I install firefox?")

    def test_stage_trust(self):
        for conf, want in (({"permissionMode": "yolo", "trust": "guide"}, "yolo"), ({"trust": "mechanic"}, "mechanic"), ({}, "unknown")):
            with mock.patch.object(self.s, "nixi_conf", return_value=conf):
                self.assertEqual(self.s.stage_trust(), want)


if __name__ == "__main__":
    unittest.main()
