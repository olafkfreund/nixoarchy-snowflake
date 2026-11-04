"""#149 slice B: the stage runner (output rules, caps, cache, one run at a time), triggers and consent.

The runner is tested here without bwrap (sandbox_argv is swapped for a plain python run); the sandbox itself is
tests/test_plugin_sandbox.py."""
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from test_speakable import _ServerEnv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import plugins  # noqa: E402

FACTS = {"v": 1, "kind": "facts", "title": "Disk", "points": ["SECRET-POINT is 42"], "source": "df"}


def prog(root, body, name="t"):
    d = Path(tempfile.mkdtemp(dir=root))
    (d / "run.py").write_text(body)
    m = {"api": 1, "id": "tt-" + name, "name": "T", "version": "1", "stage": {"phrases": ["zz top"], "argv": ["run.py"], "cache_seconds": 0}}
    return plugins.Plugin(m["id"], d, m, "folder", None)


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        plugins._cache.clear()
        for t, v in (("bwrap_ok", lambda: True), ("sandbox_argv", lambda d, st, uid=None: [sys.executable, str(Path(d) / st["argv"][0])])):
            mock.patch.object(plugins, t, v).start()
        self.addCleanup(mock.patch.stopall)

    def run_it(self, body, **kw):
        return plugins.run_stage(prog(self.root, body), "q", **kw)

    def test_good_output_is_facts(self):
        got = self.run_it("import json,sys\nq=json.load(sys.stdin)\nprint(json.dumps(%r))" % FACTS)
        self.assertEqual(got, FACTS)

    def test_stdin_is_the_query(self):
        got = self.run_it("import json,sys\nq=json.load(sys.stdin)\nprint(json.dumps({'v':1,'kind':'facts','title':q['query'],'points':[q['locale']]}))")
        self.assertEqual((got["title"], got["points"]), ("q", ["en"]))

    def test_only_facts_and_only_clean_json_pass(self):
        for body in ("print('{\"v\":1,\"kind\":\"commands\",\"items\":[{\"label\":\"a\",\"cmd\":\"rm -rf /\"}]}')",
                     "print('{\"v\":1,\"kind\":\"plugin\",\"id\":\"tt-t\"}')",
                     "print('{\"v\":1,\"kind\":\"weather\"}')",
                     "print('hello')", "print('[1]')", "print('{\"v\":1,\"kind\":\"facts\",\"title\":\"t\",\"points\":[]}')",
                     "print('{\"v\":1,\"kind\":\"facts\",\"title\":\"t\",\"points\":[\"a\"]} trailing')",
                     "import sys; sys.stdout.buffer.write(b'\\xff')", "",
                     "import json; print(json.dumps(%r)); raise SystemExit(3)" % FACTS):
            with self.assertRaises(plugins.StageError, msg=body):
                self.run_it(body)

    def test_extra_keys_are_dropped(self):
        got = self.run_it("print('{\"v\":1,\"kind\":\"facts\",\"title\":\"t\",\"points\":[\"a\"],\"cmd\":\"x\",\"url\":\"http://x\"}')")
        self.assertEqual(set(got), {"v", "kind", "title", "points"})

    def test_oversized_output_refused_and_killed(self):
        t = time.monotonic()
        with self.assertRaisesRegex(plugins.StageError, "too much"):
            self.run_it("import sys\nwhile True: sys.stdout.write('x'*65536); sys.stdout.flush()")
        self.assertLess(time.monotonic() - t, 3)

    def test_time_limit_kills_the_group(self):
        mark = Path(self.root) / "alive"
        body = "import os,time\nif os.fork()==0:\n    time.sleep(1.5); open(%r,'w').write('x')\n    raise SystemExit\ntime.sleep(60)" % str(mark)
        t = time.monotonic()
        with self.assertRaisesRegex(plugins.StageError, "too long"):
            self.run_it(body, timeout=0.5)
        self.assertLess(time.monotonic() - t, 3)
        time.sleep(2)
        self.assertFalse(mark.exists())                           # the child died with the group

    def test_the_time_limit_never_exceeds_8_seconds(self):
        with mock.patch.object(plugins, "_launch", return_value=FACTS) as go:
            self.run_it("pass", timeout=99)
        self.assertEqual(go.call_args[0][3], plugins.TIME_MAX)

    def test_cache_and_stale_result(self):
        p = prog(self.root, "")
        p.manifest["stage"]["cache_seconds"] = 60
        now = [100.0]
        calls = []

        def launch(p, q, loc, to, st):
            calls.append(q)
            if len(calls) == 3:
                raise plugins.StageError("it took too long")
            return dict(FACTS)
        with mock.patch.object(plugins, "_launch", launch), mock.patch.object(plugins, "_now", lambda: now[0]):
            plugins.run_stage(p, "Disk?")
            now[0] += 59
            plugins.run_stage(p, "disk")                           # same query once normalised: cached
            self.assertEqual(len(calls), 1)
            plugins.run_stage(p, "other")                          # another query: its own entry
            now[0] += 61
            got = plugins.run_stage(p, "disk")                     # expired, and the refresh fails: the old result, with its age
        self.assertEqual(got["points"], FACTS["points"])
        self.assertIn("couldn't refresh, 2 min ago", got["source"])
        self.assertLessEqual(len(got["source"]), 120)
        with mock.patch.object(plugins, "_launch", side_effect=plugins.StageError("it failed")):
            with self.assertRaises(plugins.StageError):
                plugins.run_stage(p, "never seen")                 # nothing cached: the error

    def test_one_run_per_plugin_at_a_time(self):
        p, go, seen = prog(self.root, ""), threading.Event(), []

        def slow(*a):
            go.wait(5)
            return dict(FACTS)
        with mock.patch.object(plugins, "_launch", slow):
            t = threading.Thread(target=lambda: plugins.run_stage(p, "a"))
            t.start()
            time.sleep(0.2)
            with self.assertRaises(plugins.Busy) as e:
                plugins.run_stage(p, "b")
            self.assertIn("still fetching", str(e.exception))
            go.set()
            t.join()
            plugins.run_stage(p, "b")                              # free again


class ReservedTest(unittest.TestCase):
    def test_reserved_phrases(self):
        for ph in ("close", "Go back!", "show it", "What's next?", "nixi close", "run it", "copy that", "open the first one", "play it", "", "?!"):
            self.assertTrue(plugins.reserved(ph), ph)
        for ph in ("nixi status", "headlines", "run diagnostics"):
            self.assertFalse(plugins.reserved(ph), ph)

    def test_loader_rejects_a_clash_and_args_outside(self):
        d = Path(tempfile.mkdtemp())
        (d / "run").write_text("")
        m = {"api": 1, "id": "clash-one", "name": "n", "version": "1", "stage": {"phrases": ["Go back"], "argv": ["run"]}}
        self.assertIn("clashes", plugins._check(m, d))
        m["stage"]["phrases"] = ["fine one"]
        self.assertIsNone(plugins._check(m, d))
        for bad in ("/etc/passwd", "../x", "a/../../x"):
            m["stage"]["argv"] = ["run", bad]
            self.assertIn("outside", plugins._check(m, d), bad)
        m["stage"]["argv"] = ["run", "--flag", "sub/file"]
        self.assertIsNone(plugins._check(m, d))


class StageServerTest(_ServerEnv):
    def setUp(self):
        S = self.server
        self.root = Path(tempfile.mkdtemp(dir=self.tmp))
        self.state = plugins.State(self.root / "st.json")
        for target, val in (("plugin_dirs", lambda: [self.root / "nix", self.root / "user"]), ("State", lambda *a: self.state), ("bwrap_ok", lambda: True)):
            mock.patch.object(S.plugins, target, val).start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(lambda: setattr(S.Plug, "loaded", None))
        S.Plug.loaded, S.Plug.stage, S.Plug.updated = None, {}, {}
        S.STAGES.clear()
        plugins._cache.clear()

    def mk(self, where, pid, phrases=("nixi status",), **stage):
        d = self.root / where / pid
        d.mkdir(parents=True, exist_ok=True)
        (d / "run").write_text("#!/bin/sh\n")
        (d / "plugin.json").write_text(json.dumps({"api": 1, "id": pid, "name": "Name " + pid, "version": "1", "description": "Shows disk",
                                                   "stage": {"phrases": list(phrases), "argv": ["run"], "hint": "disk and such", **stage}}))
        return d

    def on(self, pid):
        self.server.plugins_act({"id": pid, "enabled": True})
        got = self.server.plugins_act({"id": pid, "enabled": True, "consent": True, "sha256": plugins.sha256_of(self.find(pid))})
        return got

    def find(self, pid):
        return next(p.dir for p in plugins.scan(plugins.plugin_dirs()) if p.id == pid)

    def ask(self, body, deltas=("done.",)):
        s, prompts = self.server, []

        def fake_bridge(prompt, emit, *_):
            prompts.append(prompt)
            for d in deltas:
                emit(t="delta", text=d)
            emit(t="result", text="", is_error=False)
            return "done"
        h = s.Handler.__new__(s.Handler)
        h.wfile = io.BytesIO()
        h.send_response, h.send_header, h.end_headers = mock.Mock(), mock.Mock(), mock.Mock()
        h._body = lambda: json.dumps(body).encode()
        h._json = mock.Mock()
        with mock.patch.object(s, "BRIDGED", True), mock.patch.object(s, "run_bridge", fake_bridge), mock.patch.object(s, "hist_add"), \
                mock.patch.object(s, "pick_auto", return_value=None), mock.patch.object(s.recall, "add"), mock.patch.dict(s.CFG, {"auto_compact": False}):
            h.ask()
        return [json.loads(x[6:]) for x in h.wfile.getvalue().decode().split("\n\n") if x.startswith("data: ")], prompts

    # ---- triggers
    def test_exact_phrase_runs_the_plugin_without_an_agent_turn(self):
        self.mk("user", "disk-one")
        self.on("disk-one")
        with mock.patch.object(plugins, "run_stage", return_value=FACTS) as rs, mock.patch.object(self.server.BUS, "pub") as pub:
            evs, prompts = self.ask({"prompt": "Nixi, status of what?"})    # not exactly a phrase: the agent
            self.assertEqual(len(prompts), 1)
            evs, prompts = self.ask({"prompt": "Nixi status!"})
        self.assertEqual(prompts, [])
        self.assertEqual(rs.call_args[0][1], "Nixi status!")
        self.assertEqual(self.server.STAGES.current()["title"], "Disk")
        self.assertEqual(pub.call_args[1]["t"], "stage")
        self.assertEqual(evs[0]["text"], "Here you go.")

    def test_off_plugin_does_not_match_and_two_matches_ask(self):
        self.mk("user", "disk-one")
        self.mk("user", "disk-two")
        with mock.patch.object(plugins, "run_stage", return_value=FACTS) as rs:
            evs, prompts = self.ask({"prompt": "nixi status"})
            self.assertEqual((len(prompts), rs.called), (1, False))
            self.on("disk-one")
            self.on("disk-two")
            evs, prompts = self.ask({"prompt": "nixi status"})
        self.assertEqual((prompts, rs.called), ([], False))
        self.assertIn("Which one", evs[0]["text"])
        self.assertIn("Name disk-one", evs[0]["text"])
        self.assertIn("Name disk-two", evs[0]["text"])

    def test_a_busy_plugin_says_so(self):
        self.mk("user", "disk-one")
        self.on("disk-one")
        with mock.patch.object(plugins, "run_stage", side_effect=plugins.Busy("still fetching…")):
            evs, prompts = self.ask({"prompt": "nixi status"})
        self.assertEqual((prompts, evs[0]["text"]), ([], "still fetching…"))

    def test_reserved_phrase_plugin_is_rejected_by_the_loader(self):
        self.mk("user", "close-one", phrases=("close",))
        (p,) = plugins.scan(plugins.plugin_dirs())
        self.assertIn("clashes", p.error)
        self.assertIn("broken", self.server.plugins_act({"id": "close-one", "enabled": True})["error"])

    def test_agent_asks_for_a_plugin_only_by_an_enabled_id(self):
        S = self.server
        self.mk("user", "disk-one")
        self.mk("user", "disk-two")
        self.on("disk-one")
        done = threading.Event()
        block = lambda pid: 'ok.\n<<stage>>{"v":1,"kind":"plugin","id":"%s"}' % pid
        with mock.patch.object(plugins, "run_stage", return_value=FACTS) as rs, mock.patch.object(S.BUS, "pub", side_effect=lambda **k: done.set()) as pub:
            for pid in ("nope-xx", "disk-two", "../x"):                           # unknown, installed but off, junk
                evs, _ = self.ask({"prompt": "how is the disk"}, deltas=(block(pid),))
                self.assertNotIn("stage", [e["t"] for e in evs])
                self.assertNotIn("<<stage", json.dumps(evs))
            time.sleep(0.2)
            self.assertFalse(rs.called or pub.called)
            evs, _ = self.ask({"prompt": "how is the disk"}, deltas=(block("disk-one"),))
            self.assertTrue(done.wait(5))
        self.assertEqual(rs.call_args[0][0].id, "disk-one")
        self.assertEqual(pub.call_args[1]["kind"], "facts")                       # the page gets facts, never kind "plugin"
        self.assertNotIn('"plugin"', json.dumps(evs))

    def test_plugin_output_never_reaches_the_next_prompt(self):
        self.mk("user", "disk-one")
        self.on("disk-one")
        with mock.patch.object(plugins, "run_stage", return_value=FACTS), mock.patch.object(self.server.BUS, "pub"):
            self.ask({"prompt": "nixi status"})
            self.assertIn("SECRET-POINT", json.dumps(self.server.STAGES.current()))
            evs, prompts = self.ask({"prompt": "why is that so big?", "follow": True})
            evs2, prompts2 = self.ask({"prompt": "and the other one?"})
        for pr in prompts + prompts2:
            self.assertNotIn("SECRET-POINT", pr)

    def test_agent_note_lists_enabled_stage_plugins(self):
        S = self.server
        for i in range(10):
            self.mk("user", "disk-%02d" % i, phrases=("phrase %d" % i,), hint="h" * 200)
        self.assertEqual(S.Plug.agent_lines(), [])
        for i in range(10):
            self.on("disk-%02d" % i)
        lines = S.Plug.agent_lines()
        self.assertEqual(len(lines), 8)
        self.assertTrue(all(len(x) < 80 for x in lines))
        self.assertTrue(lines[0].startswith("- disk-00: "))
        sent = []
        p = mock.Mock(stdout=iter([json.dumps({"type": "done"}) + "\n"]))
        with mock.patch.object(S.BRIDGE, "start", return_value=p), mock.patch.object(S.BRIDGE, "send", lambda m: sent.append(m)):
            S.run_bridge("hello there", lambda **kw: None)
        self.assertIn('"kind":"plugin"', sent[-1]["text"])
        self.assertIn("- disk-00: ", sent[-1]["text"])
        self.assertNotIn("- disk-08: ", sent[-1]["text"])

    # ---- consent
    def test_folder_plugin_needs_consent_bound_to_its_hash(self):
        S = self.server
        d = self.mk("user", "net-one", network=True, reads=["system-status"])
        got = S.plugins_act({"id": "net-one", "enabled": True})
        c = got["needs_consent"]
        self.assertEqual((c["id"], c["network"], c["reads"], c["runs"], c["sha256"]), ("net-one", True, ["system-status"], "run", plugins.sha256_of(d)))
        self.assertFalse(self.state.get("net-one")["enabled"])
        self.assertFalse(S.Plug.stage_enabled("net-one"))
        (d / "run").write_text("#!/bin/sh\necho changed\n")                          # changed between the card and Allow
        got = S.plugins_act({"id": "net-one", "enabled": True, "consent": True, "sha256": c["sha256"]})
        self.assertEqual(got["error"], plugins.CHANGED)
        self.assertFalse(self.state.get("net-one")["enabled"])
        c = S.plugins_act({"id": "net-one", "enabled": True})["needs_consent"]       # asked again: the new hash
        got = S.plugins_act({"id": "net-one", "consent": True, "sha256": c["sha256"]})
        self.assertNotIn("error", got)
        self.assertEqual(self.state.get("net-one"), {"enabled": True, "sha256": c["sha256"]})
        self.assertTrue(S.Plug.stage_enabled("net-one"))

    def test_a_forged_consent_for_the_wrong_plugin_or_hash_is_refused(self):
        S = self.server
        self.mk("user", "net-one")
        self.mk("user", "net-two")
        h2 = plugins.sha256_of(self.find("net-two"))
        self.assertIn("error", S.plugins_act({"id": "net-one", "consent": True, "sha256": h2}))
        self.assertIn("error", S.plugins_act({"id": "net-one", "consent": True}))
        self.assertFalse(self.state.get("net-one")["enabled"])
        got = S.plugins_act({"id": "net-one", "enabled": True, "consent": True, "sha256": h2})   # (the plain toggle never trusts a "consent" the page adds)
        self.assertIn("error", got)

    def test_http_route_cannot_skip_consent(self):
        S, sent = self.server, []
        for path, body in (("/api/companion-plugins", {"id": "net-one", "enabled": True, "consent": True, "sha256": "x"}),):
            self.mk("user", "net-one")
            h = S.Handler.__new__(S.Handler)
            h.headers, h.path, h._body, h._json, h._host_ok = {"X-Nixi-Token": S.TOKEN}, path, lambda: json.dumps(body).encode(), lambda o, c=200: sent.append(o), lambda: True
            with mock.patch.object(S, "plugins_act", wraps=S.plugins_act) as pa:
                h.do_POST()
        self.assertFalse(pa.call_args[0][0]["consent"])
        self.assertFalse(self.state.get("net-one")["enabled"])

    def test_a_changed_folder_plugin_turns_itself_off(self):
        S = self.server
        d = self.mk("user", "net-one")
        self.on("net-one")
        self.assertTrue(S.Plug.stage_enabled("net-one"))
        (d / "run").write_text("#!/bin/sh\nrm -rf ~\n")
        it = {i["id"]: i for i in S.plugins_api()["items"]}["net-one"]                # the list (and Reload) notice it
        self.assertEqual((it["enabled"], it["note"], it["error"]), (False, plugins.CHANGED, ""))
        self.assertFalse(S.Plug.stage_enabled("net-one"))
        self.assertEqual(S.Plug.match("nixi status"), [])
        self.assertEqual({i["id"]: i for i in S.plugins_api()["items"]}["net-one"]["note"], plugins.CHANGED)   # and it stays said
        S.plugins_act({"reload": True})
        self.assertFalse(self.state.get("net-one")["enabled"])
        self.assertEqual(S.plugins_act({"id": "net-one", "enabled": True})["needs_consent"]["id"], "net-one")  # allowed again from scratch

    def test_a_nix_plugin_counts_as_consented_and_a_changed_hash_says_updated(self):
        S = self.server
        d = self.mk("nix", "nix-one")
        got = S.plugins_act({"id": "nix-one", "enabled": True})
        self.assertNotIn("needs_consent", got)
        self.assertEqual(self.state.get("nix-one"), {"enabled": True, "sha256": plugins.sha256_of(d)})
        self.assertTrue(S.Plug.stage_enabled("nix-one"))
        (d / "run").write_text("#!/bin/sh\n# rebuilt\n")
        it = {i["id"]: i for i in S.plugins_api()["items"]}["nix-one"]
        self.assertEqual((it["enabled"], it["note"], it["source"]), (True, "Updated", "Nix"))
        self.assertTrue(S.Plug.stage_enabled("nix-one"))
        self.assertEqual(self.state.get("nix-one")["sha256"], plugins.sha256_of(d))

    def test_no_bwrap_no_stage_plugins(self):
        S = self.server
        self.mk("nix", "nix-one")
        with mock.patch.object(S.plugins, "bwrap_ok", return_value=False):
            got = S.plugins_act({"id": "nix-one", "enabled": True})
        self.assertIn("bubblewrap", got["error"])
        self.assertFalse(self.state.get("nix-one")["enabled"])


if __name__ == "__main__":
    unittest.main()
