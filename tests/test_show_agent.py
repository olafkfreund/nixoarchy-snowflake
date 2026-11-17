"""#96: agents from every herdr session, and focusing the agent after a confirmed send. Nothing real runs: no herdr, no hyprctl."""
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from test_speakable import _ServerEnv

CMD = "herdr --session Dev-A agent prompt p1 hi"
OPTS = [{"id": "a1", "kind": "allow_once"}, {"id": "r1", "kind": "reject_once"}]
ALLOW, DECLINE = "a1", "r1"
AGENTS = [{"agent": "claude", "agent_status": "idle", "cwd": "/x/proj", "pane_id": "p1", "session": "Dev-A", "terminal_title_stripped": "alpha"},
          {"agent": "claude", "agent_status": "idle", "cwd": "/x/other", "pane_id": "p1", "session": "Dev-B", "terminal_title_stripped": "beta"}]


class ShowAgentTest(_ServerEnv):
    def setUp(self):
        s = self.s = self.server
        self._saved = (s.TURN, dict(s.SENDS), s.ST.send_watch, s.ST.stopped, s.ST.stage_run, s.ST.stage_run_tok)
        s.SENDS.clear()
        s.ST.send_watch, s.ST.stopped, s.ST.stage_run = None, False, None

    def tearDown(self):
        s = self.s
        s.TURN, s.ST.send_watch, s.ST.stopped, s.ST.stage_run, s.ST.stage_run_tok = (
            self._saved[0], self._saved[2], self._saved[3], self._saved[4], self._saved[5])
        s.SENDS.clear()
        s.SENDS.update(self._saved[1])

    # ---- sessions, allowlist, duplicate pane ids
    def test_agents_carry_their_session_and_dup_panes_stay_apart(self):
        s = self.s
        calls = []
        with mock.patch.object(s, "BRIDGED", True), mock.patch.object(s, "nixi_conf", return_value={}), \
                mock.patch.object(s, "herdr_agents", return_value=AGENTS), \
                mock.patch.object(s, "herdr_read", side_effect=lambda p, ss: calls.append((p, ss)) or "ok"), \
                mock.patch.object(s.shutil, "which", return_value=None), mock.patch.object(s.subprocess, "Popen") as po:
            self.assertIn("--session Dev-A agent prompt p1 ", s.session_send("alpha", "hi")[1])
            self.assertIn("--session Dev-B agent prompt p1 ", s.session_send("beta", "hi")[1])
            s.session_status("alpha")
            s.session_status("beta")
            s.session_show("beta")
        self.assertEqual(calls, [("p1", "Dev-A"), ("p1", "Dev-B")])
        self.assertEqual(po.call_args[0][0][-5:], ["--session", "Dev-B", "agent", "attach", "p1"])

    def test_allowlist(self):
        s = self.s
        with mock.patch.object(s.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="x")):
            for ok in (["herdr", "session", "list", "--json"], ["herdr", "--session", "Dev-A", "agent", "focus", "p1"]):
                self.assertEqual(s._herdr(ok), "x")
            for bad in (["herdr", "--session", "--help", "agent", "focus", "p1"], ["herdr", "--session", "a b", "agent", "list"],
                        ["herdr", "--session", "Dev-A", "agent", "focus", "-x"], ["herdr", "--session", "Dev-A", "agent", "prompt", "p1", "x"]):
                with self.assertRaises(ValueError):
                    s._herdr(bad)

    # ---- SENDS
    def test_send_records_two_quick_sends_and_caps(self):
        s = self.s
        with mock.patch.object(s, "BRIDGED", True), mock.patch.object(s, "nixi_conf", return_value={}), mock.patch.object(s, "herdr_agents", return_value=AGENTS):
            a = s.session_send("alpha", "one")[1]
            b = s.session_send("alpha", "two")[1]
        self.assertEqual(set(s.SENDS), {a, b})
        self.assertEqual(s.SENDS[a], {**s.SENDS[a], "command": "herdr --session Dev-A agent prompt p1 one", "session": "Dev-A", "pane": "p1"})
        for i in range(10):
            s._record_send("c", f"k{i}", "Dev-A", "p1")
        self.assertEqual(len(s.SENDS), 8)
        self.assertIn("k9", s.SENDS)
        self.assertNotIn("k0", s.SENDS)

    def test_records_expire_on_insert(self):
        s = self.s
        s._record_send("c", "old", "Dev-A", "p1")
        s.SENDS["old"]["at"] -= 901
        s._record_send("c", "new", "Dev-A", "p1")
        self.assertEqual(list(s.SENDS), ["new"])

    def ask(self, prompt, seen):
        s = self.s

        def fake_bridge(p, emit, *_):
            seen.append((s.TURN, s.ST.send_watch))
            emit(t="result", text="", is_error=False)
            return "done"
        h = s.Handler.__new__(s.Handler)
        h.wfile = io.BytesIO()
        h.send_response, h.send_header, h.end_headers = mock.Mock(), mock.Mock(), mock.Mock()
        h._body = lambda: json.dumps({"prompt": prompt}).encode()
        h._json = mock.Mock()
        with mock.patch.object(s, "BRIDGED", True), mock.patch.object(s, "run_bridge", fake_bridge), mock.patch.object(s, "hist_add"), \
                mock.patch.object(s, "pick_auto", return_value=None), mock.patch.object(s.recall, "add"), mock.patch.dict(s.CFG, {"auto_compact": False}):
            h.ask()

    def test_ask_turns_a_record_into_a_watch_once_and_clears_it(self):
        s, seen = self.s, []
        s._record_send(CMD, "the ask prompt", "Dev-A", "p1")
        t0 = s.TURN
        self.ask("the ask prompt", seen)
        turn, w = seen[0]
        self.assertEqual(turn, t0 + 1)
        self.assertEqual((w["turn"], w["id"], w["armed"], w["command"]), (t0 + 1, None, False, CMD))
        self.assertIsNone(s.ST.send_watch)                     # the turn's end clears it
        self.assertNotIn("the ask prompt", s.SENDS)            # used once
        self.ask("the ask prompt", seen)
        self.assertIsNone(seen[1][1])

    def test_ask_ignores_an_expired_record_and_other_prompts(self):
        s, seen = self.s, []
        s._record_send(CMD, "p", "Dev-A", "p1")
        s.SENDS["p"]["at"] -= 901                              # expiry at use, with no send in between
        self.ask("p", seen)
        s._record_send(CMD, "q", "Dev-A", "p1")
        self.ask("something else", seen)
        self.assertEqual([w for _, w in seen], [None, None])

    # ---- the watch, through run_bridge's real reader and approve()
    def watch(self, turn=None, command=CMD, **kw):
        s = self.s
        return {"command": command, "session": "Dev-A", "pane": "p1", "at": 0, "turn": s.TURN if turn is None else turn, "id": None, "armed": False, **kw}

    def drive(self, steps, answers, watch="default"):
        """steps: ("line", dict) | ("release", title) | ("await", n permissions sent) | ("do", fn). Returns (sent, show_agent calls)."""
        s = self.s
        sent, sig, shown = [], threading.Condition(), []
        gates = {t: threading.Event() for t in answers if answers[t][1]}
        shown_ev = threading.Event()

        def send(m):
            if m.get("type") == "permission":
                with sig:
                    sent.append(m)
                    sig.notify_all()

        def ask(title, opts, detail, **kw):
            if title in gates:
                gates[title].wait(2)
            return answers[title][0]

        def lines():
            for kind, arg in steps:
                if kind == "line":
                    yield json.dumps(arg) + "\n"
                elif kind == "release":
                    gates[arg].set()
                elif kind == "await":
                    with sig:
                        sig.wait_for(lambda: len(sent) >= arg, 2)
                elif kind == "do":
                    arg()
            yield json.dumps({"type": "done"}) + "\n"

        p = mock.Mock(stdout=lines())
        s.ST.send_watch = self.watch() if watch == "default" else watch
        self.w = s.ST.send_watch
        with mock.patch.object(s.BRIDGE, "start", return_value=p), mock.patch.object(s.BRIDGE, "send", send), mock.patch.object(s.BRIDGE, "proc", p), \
                mock.patch.object(s.APPROVALS, "ask_bridge", ask), \
                mock.patch.object(s, "show_agent", side_effect=lambda *a: (shown.append(a), shown_ev.set())):
            s.run_bridge("x", lambda **kw: None)
            shown_ev.wait(0.2)
        return sent, shown

    @staticmethod
    def perm(title="t1", id=7, tid="T1", command=CMD, confirm="click"):
        d = {"type": "permission", "id": id, "title": title, "options": OPTS, "command": command, "confirm": confirm}
        if tid is not None:
            d["toolCallId"] = tid
        return ("line", d)

    @staticmethod
    def tool(status, tid="T1"):
        d = {"type": "tool", "title": "Bash", "status": status}
        if tid is not None:
            d["toolCallId"] = tid
        return ("line", d)

    def test_confirmed_then_completed_focuses_exactly_once(self):
        s = self.s
        t = s.TURN
        sent, shown = self.drive([self.perm(), ("await", 1), self.tool("completed"), self.tool("completed")], {"t1": (ALLOW, False)})
        self.assertEqual(shown, [("Dev-A", "p1", t)])
        self.assertIsNone(s.ST.send_watch)

    def test_things_that_must_not_focus(self):
        s = self.s
        cases = {
            "declined": ([self.perm(), ("await", 1), self.tool("completed")], {"t1": (DECLINE, False)}, {}),
            "failed": ([self.perm(), ("await", 1), self.tool("failed")], {"t1": (ALLOW, False)}, {}),
            "no id on the permission": ([self.perm(tid=None), ("await", 1), self.tool("completed", tid=None)], {"t1": (ALLOW, False)}, {}),
            "other command": ([self.perm(command=CMD + " x"), ("await", 1), self.tool("completed")], {"t1": (ALLOW, False)}, {}),
            "not a click card": ([self.perm(confirm=None), ("await", 1), self.tool("completed")], {"t1": (ALLOW, False)}, {}),
            "other tool id": ([self.perm(), ("await", 1), self.tool("completed", tid="T2")], {"t1": (ALLOW, False)}, {}),
            "stopped before the click": ([self.perm(), ("do", lambda: setattr(s.ST, "stopped", True)), ("release", "t1"), ("await", 1), self.tool("completed")],
                                         {"t1": (ALLOW, True)}, {}),
            "newer turn before the click": ([self.perm(), ("do", lambda: setattr(s, "TURN", s.TURN + 1)), ("release", "t1"), ("await", 1), self.tool("completed")],
                                            {"t1": (ALLOW, True)}, {}),
            "old turn watch": ([self.perm(), ("await", 1), self.tool("completed")], {"t1": (ALLOW, False)}, {"turn": -1}),
        }
        for name, (steps, answers, wkw) in cases.items():
            with self.subTest(name):
                s.ST.stopped = False
                _, shown = self.drive(steps, answers, watch=self.watch(**wkw))
                self.assertEqual(shown, [])

    def test_second_identical_command_after_arming_gives_no_second_focus(self):
        s = self.s
        sent, shown = self.drive([self.perm(), ("await", 1), self.perm("t2", 8, "T2"), ("await", 2), self.tool("completed", "T2"), self.tool("completed", "T1")],
                                 {"t1": (ALLOW, False), "t2": (ALLOW, False)})
        self.assertEqual(len(shown), 1)                         # only T1's completion; T2 never armed it

    def test_unrelated_denied_permission_between_click_and_completed_still_focuses(self):
        sent, shown = self.drive([self.perm(), ("await", 1), self.perm("t2", 8, "T9", command="ls"), ("await", 2), self.tool("completed")],
                                 {"t1": (ALLOW, False), "t2": (DECLINE, False)})
        self.assertEqual(len(shown), 1)

    def test_two_workers_same_command_one_arms_either_order(self):
        for first, second in (("t1", "t2"), ("t2", "t1")):
            for answers, armed in (({"t1": (ALLOW, True), "t2": (DECLINE, True)}, True),):
                with self.subTest(first=first):
                    steps = [self.perm("t1", 7, "T1"), self.perm("t2", 8, "T2"), ("release", first), ("await", 1), ("release", second), ("await", 2),
                             self.tool("completed", "T1"), self.tool("completed", "T2")]
                    _, shown = self.drive(steps, answers)
                    # allow t1 first: arms T1 -> completed T1 focuses once. decline t1 first (t2 allow second) cannot arm: t1 decline clears the watch.
                    self.assertEqual(len(shown), 1 if first == "t1" else 0)

    def test_old_turn_worker_leaves_a_new_turns_watch_alone(self):
        s = self.s
        new = {}

        def swap():
            s.TURN += 1
            new["w"] = self.watch(turn=s.TURN)
            s.ST.send_watch = new["w"]
        sent, shown = self.drive([self.perm("t1"), ("do", swap), ("release", "t1"), ("await", 1)], {"t1": (ALLOW, True)})
        self.assertIs(s.ST.send_watch, new["w"])
        self.assertFalse(new["w"]["armed"])
        self.assertEqual(shown, [])

    # ---- show_agent
    def listing(self, panes=("p1",)):
        return json.dumps({"result": {"agents": [{"pane_id": p} for p in panes]}})

    def test_show_agent_focuses_then_raises_the_window(self):
        s = self.s
        with mock.patch.object(s, "_herdr", side_effect=lambda a: self.listing() if a[-1] == "list" else "") as h, \
                mock.patch.object(s, "herdr_window_pid", return_value=4242) as wp, mock.patch.object(s, "_run") as run:
            s.show_agent("Dev-A", "p1", s.TURN)
        self.assertEqual(h.call_args_list[-1][0][0], ["herdr", "--session", "Dev-A", "agent", "focus", "p1"])
        wp.assert_called_once_with("Dev-A")
        self.assertEqual(run.call_args[0][0], ["hyprctl", "dispatch", "focuswindow", "pid:4242"])

    def test_show_agent_pane_gone_stops_stale_turn_and_bad_ids(self):
        s = self.s
        with mock.patch.object(s, "_herdr", return_value=self.listing(("p2",))) as h, mock.patch.object(s, "herdr_window_pid") as wp, mock.patch.object(s, "_run") as run:
            s.show_agent("Dev-A", "p1", s.TURN)
            self.assertEqual(h.call_count, 1)                   # the list, no focus
            s.show_agent("Dev-A", "p1", s.TURN - 1)             # an old turn
            s.show_agent("--help", "p1", s.TURN)
            s.show_agent("Dev-A", "-x", s.TURN)
            self.assertEqual(h.call_count, 1)
        wp.assert_not_called()
        run.assert_not_called()

    def test_show_agent_paused_at_the_turn_boundary_does_not_focus(self):
        s = self.s
        turn = s.TURN

        def herdr(a):
            if a[-1] == "list":                                 # the new turn begins: counter bumped, stopped reset
                s.TURN += 1
                s.ST.stopped = False
                return self.listing()
            raise AssertionError("focused")
        with mock.patch.object(s, "_herdr", side_effect=herdr), mock.patch.object(s, "_run") as run:
            s.show_agent("Dev-A", "p1", turn)
        run.assert_not_called()

    def test_show_agent_stopped_after_focus_does_not_dispatch(self):
        s = self.s

        def herdr(a):
            if a[-1] == "list":
                return self.listing()
            s.ST.stopped = True
            return ""
        with mock.patch.object(s, "_herdr", side_effect=herdr), mock.patch.object(s, "herdr_window_pid") as wp, mock.patch.object(s, "_run") as run:
            s.show_agent("Dev-A", "p1", s.TURN)
        wp.assert_not_called()
        run.assert_not_called()

    def test_show_agent_swallows_exceptions(self):
        s = self.s
        with mock.patch.object(s, "_herdr", side_effect=RuntimeError("boom")):
            s.show_agent("Dev-A", "p1", s.TURN)
        with mock.patch.object(s, "_herdr", return_value="not json"):
            s.show_agent("Dev-A", "p1", s.TURN)

    # ---- the window matcher, on fake /proc trees
    def tree(self, procs):
        root = tempfile.mkdtemp(prefix="nixi-proc-", dir=os.environ["HOME"])
        for pid, (ppid, argv) in procs.items():
            d = Path(root, str(pid))
            d.mkdir()
            d.joinpath("stat").write_text(f"{pid} (herdr) S {ppid} 1 1 0\n")
            d.joinpath("cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        Path(root, "self").mkdir()
        return root

    def pid_of(self, procs, clients, session="Dev-A"):
        s = self.s
        out = mock.Mock(stdout=json.dumps(clients).encode())
        with mock.patch.object(s, "_run", return_value=out):
            return s.herdr_window_pid(session, self.tree(procs))

    def test_window_matcher(self):
        win = lambda pid, cls="org.omarchy.herdr": {"class": cls, "pid": pid}
        h = ["herdr", "--session", "Dev-A"]
        self.assertEqual(self.pid_of({101: (100, h)}, [win(100)]), 100)
        self.assertEqual(self.pid_of({101: (100, ["/nix/store/x/bin/herdr", "--session", "Dev-A"])}, [win(100)]), 100)
        self.assertIsNone(self.pid_of({101: (100, h), 201: (200, h)}, [win(100), win(200)]))          # two windows: no raise
        self.assertIsNone(self.pid_of({101: (100, ["herdr"])}, [win(100)]))                           # a bare herdr never counts
        self.assertIsNone(self.pid_of({101: (100, ["herdr", "session", "attach", "Dev-A"])}, [win(100)]))
        self.assertIsNone(self.pid_of({101: (100, h)}, [win(100, "kitty")]))
        self.assertIsNone(self.pid_of({101: (100, ["herdr", "--session", "Dev-B"])}, [win(100)]))
        self.assertIsNone(self.pid_of({101: (100, h)}, [win(100)], session="--help"))

    # ---- the desk
    def test_desk_open_session_attaches_with_the_rows_session(self):
        s = self.s
        import stages
        page = s.STAGES.put(stages.status_stage([{"title": "a", "status": "idle", "pane": "p1", "session": "Dev-A"},
                                                  {"title": "b", "status": "idle", "pane": "p1", "session": "Dev-B"}], [], True))
        with mock.patch.object(s.shutil, "which", return_value=None), mock.patch.object(s.subprocess, "Popen") as po:
            for row, sess in zip(page["sessions"], ("Dev-A", "Dev-B")):
                self.assertTrue(s.stage_act(row["open"], "session")["ok"])
                self.assertEqual(po.call_args[0][0][-5:], ["--session", sess, "agent", "attach", "p1"])


if __name__ == "__main__":
    unittest.main()
