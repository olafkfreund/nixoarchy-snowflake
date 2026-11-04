import io
import json
import time
import unittest
import urllib.error
from unittest import mock
from test_speakable import _ServerEnv

CMD = "nix profile install nixpkgs#firefox"
OPTS = [{"id": "a1", "kind": "allow_once"}, {"id": "r1", "kind": "reject_once"}, {"id": "r2", "kind": "reject_always"}]


class StageActionsTest(_ServerEnv):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import day
        import stages
        cls.stages = stages
        globals()["day"] = day

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

    def refresh_page(self):
        stage = {"v": 1, "kind": "gauges", "title": "System", "live": True,
                 "hosts": [{"name": "p620", "meters": [{"label": "CPU", "pct": 12}]}]}
        stage = self.stages.validate(stage)
        page = self.s.STAGES.put(stage, refresh=("status", "system status"))
        return stage, page

    def test_refresh_only_current_enabled_plugin_and_unlocked_desk(self):
        stage, page = self.refresh_page()
        p = object()
        with mock.patch.object(self.s.Plug, "stage", {"status": p}), \
                mock.patch.object(self.s.Desk, "locked", return_value=None), \
                mock.patch.object(self.s.plugins, "run_stage", return_value=stage) as run, \
                mock.patch.object(self.s.BUS, "pub") as pub:
            self.assertEqual(self.s.stage_act(page["refresh"], "refresh"), {"ok": True})
            run.assert_called_once_with(p, "system status", locale="en", fresh=True)   # (#177: plugins get the active locale)
            self.assertEqual(pub.call_args.kwargs["t"], "stage_update")
            pub.reset_mock()
            for token in (page["token"], self.tok, "forged"):
                self.assertEqual(self.s.stage_act(token, "refresh"), {"ok": False})
            with mock.patch.object(self.s.Desk, "locked", return_value=True):
                self.assertEqual(self.s.stage_act(page["refresh"], "refresh"), {"ok": False})
            self.assertFalse(pub.called)
        with mock.patch.object(self.s.Plug, "stage", {}), mock.patch.object(self.s.Desk, "locked", return_value=False), \
                mock.patch.object(self.s.plugins, "run_stage") as run:
            self.assertEqual(self.s.stage_act(page["refresh"], "refresh"), {"ok": False})
            run.assert_not_called()

    def test_refresh_busy_and_changed_send_nothing(self):
        _, page = self.refresh_page()
        with mock.patch.object(self.s.Plug, "stage", {"status": object()}), \
                mock.patch.object(self.s.Desk, "locked", return_value=False), \
                mock.patch.object(self.s.BUS, "pub") as pub, \
                mock.patch.object(self.s.Plug, "reload") as reload, \
                mock.patch.object(self.s.plugins, "run_stage", side_effect=[self.s.plugins.Busy("busy"), self.s.plugins.StageError(self.s.plugins.CHANGED)]):
            self.assertEqual(self.s.stage_act(page["refresh"], "refresh"), {"ok": True, "skipped": True})
            self.assertEqual(self.s.stage_act(page["refresh"], "refresh"), {"ok": False})
            reload.assert_called_once_with()
            pub.assert_not_called()

    def test_refresh_lost_after_close_or_another_put(self):
        stage, page = self.refresh_page()
        with mock.patch.object(self.s.Plug, "stage", {"status": object()}), \
                mock.patch.object(self.s.Desk, "locked", return_value=False), \
                mock.patch.object(self.s.BUS, "pub") as pub:
            for change in (self.s.STAGES.close, lambda: self.s.STAGES.put(self.stages.validate(stage), refresh=("status", "system status"))):
                page = self.s.STAGES.put(self.stages.validate(stage), refresh=("status", "system status"))
                def late(*args, **kwargs):
                    change()
                    return stage
                with mock.patch.object(self.s.plugins, "run_stage", side_effect=late):
                    self.assertEqual(self.s.stage_act(page["refresh"], "refresh"), {"ok": False, "error": "gone"})
                pub.assert_not_called()

    def test_refresh_updates_copy_text(self):
        stage, page = self.refresh_page()
        newer = self.stages.validate({**stage, "hosts": [{"name": "p620", "meters": [{"label": "CPU", "pct": 83}]}]})
        with mock.patch.object(self.s.Plug, "stage", {"status": object()}), \
                mock.patch.object(self.s.Desk, "locked", return_value=False), \
                mock.patch.object(self.s.plugins, "run_stage", return_value=newer), \
                mock.patch.object(self.s.BUS, "pub"), mock.patch.object(self.s.subprocess, "run", return_value=mock.Mock(returncode=0)) as copy:
            self.assertEqual(self.s.stage_act(page["refresh"], "refresh"), {"ok": True})
            self.assertEqual(self.s.stage_act(page["token"], "copy"), {"ok": True})
            self.assertIn(b"83", copy.call_args.kwargs["input"])

    def test_refresh_rejects_plugin_changing_kind_or_live(self):
        _, page = self.refresh_page()
        facts = self.stages.validate({"v": 1, "kind": "facts", "title": "Status", "points": ["changed"]})
        inactive = self.stages.validate({"v": 1, "kind": "gauges", "title": "Status", "live": False,
                                         "hosts": [{"name": "p620", "meters": [{"label": "CPU", "pct": 12}]}]})
        with mock.patch.object(self.s.Plug, "stage", {"status": object()}), \
                mock.patch.object(self.s.Desk, "locked", return_value=False), \
                mock.patch.object(self.s.plugins, "run_stage", side_effect=[facts, inactive]), \
                mock.patch.object(self.s.BUS, "pub") as pub:
            self.assertEqual(self.s.stage_act(page["refresh"], "refresh"), {"ok": False})
            self.assertEqual(self.s.stage_act(page["refresh"], "refresh"), {"ok": False})
            pub.assert_not_called()
        self.assertEqual(self.s.STAGES.current()["kind"], "gauges")

    def test_open_play_not_yet_and_unknown(self):
        self.assertEqual(self.s.stage_act(self.tok, "open")["error"], "not yet")
        self.assertFalse(self.s.stage_act(self.tok, "run")["ok"])
        self.assertFalse(self.s.stage_act("nope", "open")["ok"])

    def test_open_a_map_runs_xdg_open_with_the_server_url(self):
        page = self.s.STAGES.put(self.stages.validate({"v": 1, "kind": "place", "dest": "Oslo S", "mode": "transit"}))
        with mock.patch.object(self.s.subprocess, "Popen") as po:
            self.assertTrue(self.s.stage_act(page["open"], "open")["ok"])
            self.assertEqual(po.call_args[0][0], ["xdg-open", "https://www.google.com/maps/dir/?api=1&destination=Oslo+S&travelmode=transit"])
            po.reset_mock()
            self.assertFalse(self.s.stage_act(page["copy"], "open")["ok"])   # the copy token has no URL
            self.assertFalse(po.called)

    def video_page(self):
        v = self.stages.validate({"v": 1, "kind": "video", "query": "cats"})
        return self.s.STAGES.put({**v, "items": [{"id": "abcdefghijk", "title": "t", "channel": "c", "duration": "1:00"}]})

    def test_play_uses_mpv_else_browser_and_search_opens(self):
        page = self.video_page(); url = "https://www.youtube.com/watch?v=abcdefghijk"
        with mock.patch.object(self.s.subprocess, "Popen") as po:
            with mock.patch.object(self.s.shutil, "which", side_effect=lambda name: "/bin/mpv" if name == "mpv" else None):
                self.assertTrue(self.s.stage_act(page["items"][0]["play"], "play")["ok"])
                self.assertEqual(po.call_args[0][0], ["mpv", url])
            with mock.patch.object(self.s.shutil, "which", return_value=None):
                self.s.stage_act(page["items"][0]["play"], "play")
                self.assertEqual(po.call_args[0][0], ["xdg-open", url])
            self.s.stage_act(page["search"], "open")
            self.assertEqual(po.call_args[0][0], ["xdg-open", "https://www.youtube.com/results?search_query=cats"])

    def fallback(self, first_rc, procs, have_ytdlp=True):
        first = mock.Mock(); first.wait.return_value = first_rc
        with mock.patch.object(self.s.subprocess, "Popen", side_effect=procs) as po, \
                mock.patch.object(self.s.shutil, "which", return_value="/bin/yt-dlp" if have_ytdlp else None):
            self.s._play_fallback(first, "https://www.youtube.com/watch?v=abcdefghijk")
        return [c.args[0] for c in po.call_args_list], po

    def test_play_ok_or_closed_takes_no_fallback(self):
        for rc in (0, 4, -15):
            self.assertEqual(self.fallback(rc, [])[0], [])

    def test_play_refused_stream_takes_the_pipe(self):
        url = "https://www.youtube.com/watch?v=abcdefghijk"
        yt = mock.Mock(stdout=mock.Mock()); player = mock.Mock(); player.wait.return_value = 0
        argv, po = self.fallback(2, [yt, player])
        self.assertEqual(argv, [["yt-dlp", "--ignore-config", "-q", "-o", "-", "--", url], ["mpv", "--force-window=immediate", "-"]])
        self.assertIs(po.call_args_list[1].kwargs["stdin"], yt.stdout)
        yt.stdout.close.assert_called_once_with()

    def test_play_falls_back_to_the_browser(self):
        url = "https://www.youtube.com/watch?v=abcdefghijk"
        yt = mock.Mock(stdout=mock.Mock()); player = mock.Mock(); player.wait.return_value = 2
        self.assertEqual(self.fallback(2, [yt, player, mock.Mock()])[0][-1], ["xdg-open", url])    # the pipe failed too
        yt = mock.Mock(stdout=mock.Mock())
        self.assertEqual(self.fallback(2, [yt, OSError("no mpv"), mock.Mock()])[0][-1], ["xdg-open", url])    # mpv would not start
        yt.kill.assert_called_once_with(); yt.wait.assert_called()
        self.assertEqual(self.fallback(2, [mock.Mock()], have_ytdlp=False)[0], [["xdg-open", url]])

    def test_play_refused_for_a_command_token(self):
        with mock.patch.object(self.s.subprocess, "Popen") as po:
            self.assertFalse(self.s.stage_act(self.tok, "play")["ok"])
        self.assertFalse(po.called)

    def test_thumb_route_serves_only_ytimg_posters_of_the_stage(self):
        import urllib.request
        page = self.video_page(); s = self.s
        with mock.patch.object(s.stages, "fetch_thumb", return_value=(b"JPG", "image/jpeg")) as ft:
            srv = s.ThreadingHTTPServer(("127.0.0.1", 0), s.Handler)
            threading_t = s.threading.Thread(target=srv.serve_forever, daemon=True); threading_t.start()
            try:
                base = "http://127.0.0.1:%d/api/stage/thumb/" % srv.server_address[1]
                self.assertEqual(urllib.request.urlopen(base + page["items"][0]["thumb"]).read(), b"JPG")
                urllib.request.urlopen(base + page["items"][0]["thumb"]).read()
                self.assertEqual(ft.call_count, 1)               # cached
                for bad in (page["items"][0]["play"], "nope"):   # a non-poster token, an unknown one
                    with self.assertRaises(urllib.error.HTTPError):
                        urllib.request.urlopen(base + bad)
            finally:
                srv.shutdown(); srv.server_close()

    def test_video_search_does_not_hold_the_turn(self):
        gate, done = self.s.threading.Event(), self.s.threading.Event()

        def slow(q):
            gate.wait(5)
            return [{"id": "abcdefghijk", "title": "t", "channel": "c", "duration": "1:00"}]
        pub = mock.Mock(side_effect=lambda **kw: done.set())
        with mock.patch.object(self.s.stages, "video_search", slow), mock.patch.object(self.s.BUS, "pub", pub):
            evs, _, _ = self.ask({"prompt": "find me cat videos"}, tool=False, deltas=('ok. <<stage>>{"v":1,"kind":"video","query":"cats"}',))
            self.assertIn("result", [e["t"] for e in evs])          # the turn ended while the search was still blocked
            self.assertFalse(pub.called)
            gate.set()
            self.assertTrue(done.wait(5))
        self.assertEqual(pub.call_args[1]["t"], "stage")
        self.assertEqual(pub.call_args[1]["kind"], "video")

    def test_video_result_dropped_if_the_stage_changed(self):
        before = self.s.STAGES.current()
        self.s.STAGES.put(self.stages.validate({"v": 1, "kind": "facts", "title": "t", "points": ["p"]}))
        with mock.patch.object(self.s.stages, "video_search", return_value=[]), mock.patch.object(self.s.BUS, "pub") as pub:
            self.s.video_stage({"v": 1, "kind": "video", "query": "q"}, before)
        self.assertFalse(pub.called)

    def test_copy_needs_text_and_search_token_cannot_play(self):
        page = self.video_page()
        with mock.patch.object(self.s.subprocess, "run") as run, mock.patch.object(self.s.subprocess, "Popen") as po:
            self.assertFalse(self.s.stage_act(page["search"], "copy")["ok"])
            self.assertFalse(self.s.stage_act(page["search"], "play")["ok"])
        self.assertFalse(run.called or po.called)

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
                emit(t="tool", name="Bash", detail="", id="", input=None, status=tool if isinstance(tool, str) else "completed")
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

    def test_headlines_voice_opens_and_copies(self):
        stage = {"v": 1, "kind": "headlines", "title": "News", "items": [
            {"title": "First", "source": "BBC", "at": None, "url": "https://www.bbc.co.uk/news/first"},
            {"title": "Second", "source": "Guardian", "at": None, "url": "https://www.theguardian.com/world/second"}]}
        self.s.STAGES.put(self.stages.validate(stage))
        self.s.STAGES.set_visible(True)
        with mock.patch.object(self.s.subprocess, "Popen") as po:
            evs, prompts, _ = self.ask({"prompt": "open the second one"})
        self.assertEqual((prompts, evs[0]["text"]), ([], "Opening it."))
        self.assertEqual(po.call_args[0][0], ["xdg-open", "https://www.theguardian.com/world/second"])
        for phrase in ("copy that", "copy the first one"):
            with mock.patch.object(self.s.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
                evs, prompts, _ = self.ask({"prompt": phrase})
            self.assertEqual((prompts, evs[0]["text"]), ([], "Copied."))
            self.assertEqual(run.call_args.kwargs["input"], b"First \xe2\x80\x94 BBC\nSecond \xe2\x80\x94 Guardian")

    def test_headlines_voice_plays_clip_but_opens_story(self):
        stage = {"v": 1, "kind": "headlines", "title": "News", "items": [
            {"title": "First", "source": "BBC", "at": None, "url": "https://www.bbc.co.uk/news/first"},
            {"title": "Second", "source": "Guardian", "at": None, "url": "https://www.theguardian.com/world/second"}]}
        page = self.s.STAGES.put(self.stages.validate(stage))
        self.s.STAGES.add_clips(page["copy"], [
            {"id": "abcdefghijk", "title": "One", "channel": "A", "duration": "1:00"},
            {"id": "lmnopqrstuv", "title": "Two", "channel": "B", "duration": "2:00"}])
        self.s.STAGES.set_visible(True)
        with mock.patch.object(self.s.subprocess, "Popen") as po, mock.patch.object(self.s.shutil, "which", side_effect=lambda name: "/bin/mpv" if name == "mpv" else None):
            evs, prompts, _ = self.ask({"prompt": "play the second video"})
            self.assertEqual((prompts, evs[0]["text"], po.call_args[0][0]),
                             ([], "Playing it.", ["mpv", "https://www.youtube.com/watch?v=lmnopqrstuv"]))
            evs, prompts, _ = self.ask({"prompt": "open the first one"})
            self.assertEqual((prompts, evs[0]["text"], po.call_args[0][0]),
                             ([], "Opening it.", ["xdg-open", "https://www.bbc.co.uk/news/first"]))

    def test_fast_path_reaches_map_and_cinema_tokens(self):           # Codex review: voice used .token, which these sets lack
        page = self.s.STAGES.put(self.stages.validate({"v": 1, "kind": "place", "dest": "Oslo S"})); self.s.STAGES.set_visible(True)
        with mock.patch.object(self.s.subprocess, "Popen") as po:
            evs, prompts, _ = self.ask({"prompt": "open it"})
        self.assertEqual((prompts, evs[0]["text"], po.call_args[0][0][0]), ([], "Opening it.", "xdg-open"))
        self.video_page(); self.s.STAGES.set_visible(True)
        with mock.patch.object(self.s.subprocess, "Popen") as po, mock.patch.object(self.s.shutil, "which", side_effect=lambda name: "/bin/mpv" if name == "mpv" else None):
            evs, prompts, _ = self.ask({"prompt": "play the first one"})
        self.assertEqual((prompts, evs[0]["text"], po.call_args[0][0]), ([], "Playing it.", ["mpv", "https://www.youtube.com/watch?v=abcdefghijk"]))
        evs, prompts, _ = self.ask({"prompt": "run the first one"})     # no KeyError: Run is only for commands, so it is an ordinary turn
        self.assertEqual((len(prompts), prompts[0][1]), (1, None))

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

    # ---- the day desk (#144 slice 4)
    SNAP = {"date": "", "at": "09:00", "next": {"when": "09:40", "title": "Stand-up", "in": "in 40 min", "link": None, "url": "https://calendar.google.com"},
            "today": [], "tasks": [], "github": [], "count": {"today": 0, "tasks": 0, "github": 0}, "status": {"cal": "ok", "tasks": "ok", "gh": "off"}}

    def snap(self, **kw):
        return {**self.SNAP, "date": time.strftime("%Y-%m-%d"), **kw}

    def test_day_block_is_fetched_off_the_turn(self):
        gate, done = self.s.threading.Event(), self.s.threading.Event()

        def slow(*a, **k):
            gate.wait(5)
            return self.snap()
        pub = mock.Mock(side_effect=lambda **kw: done.set())
        with mock.patch.object(self.s.day, "snapshot", slow), mock.patch.object(self.s.BUS, "pub", pub):
            evs, _, _ = self.ask({"prompt": "how does my day look?"}, tool=False, deltas=('Here.\n<<stage>>{"v":1,"kind":"day"}',))
            self.assertIn("result", [e["t"] for e in evs])          # the turn ended while the fetch was still blocked
            self.assertNotIn("stage", [e["t"] for e in evs])
            self.assertFalse(pub.called)
            gate.set()
            self.assertTrue(done.wait(5))
        self.assertEqual((pub.call_args[1]["t"], pub.call_args[1]["kind"]), ("stage", "day"))
        self.assertEqual(self.s.STAGES.current()["kind"], "day")

    def test_day_result_dropped_if_the_stage_changed(self):
        before = self.s.STAGES.current()
        self.s.STAGES.put(self.stages.validate({"v": 1, "kind": "facts", "title": "t", "points": ["p"]}))
        with mock.patch.object(self.s.day, "snapshot", return_value=self.snap()), mock.patch.object(self.s.BUS, "pub") as pub:
            self.s.day_stage({"v": 1, "kind": "day"}, before)
        self.assertFalse(pub.called)

    def test_whats_next_is_answered_from_the_cache_without_a_turn(self):
        with mock.patch.object(self.s, "BRIDGED", True), mock.patch.object(self.s.day, "snapshot", return_value=self.snap()) as sn:
            r = self.s.day_next()
        self.assertEqual(r["say"], "Stand-up in 40 minutes.")
        self.assertTrue(sn.call_args[1]["cache_only"])              # (never a subprocess on the request thread)

    def test_whats_next_with_a_cold_cache_looks_in_a_thread(self):
        with mock.patch.object(self.s, "BRIDGED", True), mock.patch.object(self.s.threading, "Thread") as th:
            with mock.patch.object(self.s.day, "snapshot", return_value=None):
                r = self.s.day_next()
        self.assertEqual(r["say"], "Let me look at your day.")
        self.assertIs(th.call_args[1]["target"], self.s.day_stage)
        th.return_value.start.assert_called_once()

    def test_cold_whats_next_fetches_once_at_a_time(self):
        self.assertTrue(self.s.day._busy.acquire(blocking=False))   # (a fetch is running)
        try:
            with mock.patch.object(self.s, "BRIDGED", True), mock.patch.object(self.s.threading, "Thread") as th, \
                    mock.patch.object(self.s.day, "snapshot", return_value=None):
                r = self.s.day_next()
            self.assertEqual(r["say"], "Let me look at your day.")
            th.assert_not_called()
        finally:
            self.s.day._busy.release()
        with mock.patch.object(self.s, "BRIDGED", True), mock.patch.object(self.s.threading, "Thread") as th, \
                mock.patch.object(self.s.day, "snapshot", return_value=None):
            self.s.day_next()
            th.return_value.start.assert_called_once()
            self.assertFalse(self.s.day._busy.acquire(blocking=False))     # (held until the thread's day_stage lets go)
        with mock.patch.object(self.s.day, "snapshot", return_value=self.snap()):
            self.s.day_stage(None, self.s.STAGES.current(), True)
        self.assertTrue(self.s.day._busy.acquire(blocking=False))
        self.s.day._busy.release()

    def test_day_snapshot_is_kept_only_when_it_is_shown(self):
        before = self.s.STAGES.current()
        self.s.DAY["snap"] = None
        self.s.STAGES.put(self.stages.validate({"v": 1, "kind": "facts", "title": "t", "points": ["p"]}))
        with mock.patch.object(self.s.day, "snapshot", return_value=self.snap()), mock.patch.object(self.s.BUS, "pub"):
            self.s.day_stage(None, before)
        self.assertIsNone(self.s.DAY["snap"])

    def test_whats_next_phrase_reaches_the_server_and_not_the_agent(self):
        import quick
        for t in ("what's next?", "Nixi, what's next", "whats next please"):
            self.assertEqual(quick.handle(t), {"whats_next": True}, t)
        self.assertNotEqual(quick.handle("what's next on the calendar for tomorrow"), {"whats_next": True})

    def prompt_sent(self):
        sent = []
        p = mock.Mock(stdout=iter([json.dumps({"type": "done"}) + "\n"]))
        with mock.patch.object(self.s.BRIDGE, "start", return_value=p), mock.patch.object(self.s.BRIDGE, "send", lambda m: sent.append(m)):
            self.s.run_bridge("any other question", lambda **kw: None)
        return sent[-1]["text"]

    def desk(self, snap):
        st = day.stage(snap)
        st["note"], st["date"] = day.summary(snap), snap["date"]       # (as day_stage stores it)
        return self.s.STAGES.put(st)

    def test_summary_rides_along_only_while_the_day_desk_is_current(self):
        s = self.s
        s.STAGES.close()
        self.assertNotIn("from Nixi's desk", self.prompt_sent())     # (no desk is current)
        self.desk(self.snap())
        self.assertIn("(today, from Nixi's desk", self.prompt_sent())
        self.desk(self.snap(date="2000-01-01"))
        self.assertNotIn("from Nixi's desk", self.prompt_sent())     # (yesterday's desk is never passed off as today's)
        s.STAGES.close()

    def test_previous_answer_brings_back_its_own_summary(self):
        """Codex on PR #30: two desks, then Previous answer: the agent gets the summary of the desk on screen."""
        s = self.s
        one = [{"when": "all day", "title": "Alpha day", "url": None, "link": None}]
        two = [{"when": "all day", "title": "Beta day", "url": None, "link": None}]
        self.desk(self.snap(today=one, count={"today": 1, "tasks": 0, "github": 0}))
        self.desk(self.snap(today=two, count={"today": 1, "tasks": 0, "github": 0}))
        self.assertIn("Beta day", self.prompt_sent())
        s.STAGES.back()
        sent = self.prompt_sent()
        self.assertIn("Alpha day", sent)
        self.assertNotIn("Beta day", sent)
        s.STAGES.close()

    def test_a_run_never_gets_the_summary(self):
        s = self.s
        self.desk(self.snap())
        s.ST.stage_run = "x"
        self.assertNotIn("from Nixi's desk", self.prompt_sent())
        s.ST.stage_run = None
        s.STAGES.close()

    def test_day_item_opens_with_xdg_open_and_a_foreign_url_has_no_token(self):
        sn = self.snap(today=[{"when": "all day", "title": "A", "url": "https://calendar.google.com/x", "link": None},
                              {"when": "all day", "title": "B", "url": "javascript:alert(1)", "link": None}], count={"today": 2, "tasks": 0, "github": 0})
        page = self.s.STAGES.put(day.stage(sn))
        ok, bad = page["rows"][0]["items"]
        self.assertIsNone(bad["open"])
        with mock.patch.object(self.s.subprocess, "Popen") as po:
            self.assertEqual(self.s.stage_act(ok["open"], "open"), {"ok": True})
        self.assertEqual(po.call_args[0][0], ["xdg-open", "https://calendar.google.com/x"])
        self.assertFalse(po.call_args[1].get("shell"))
        self.assertFalse(self.s.stage_act("not-a-token", "open")["ok"])

    # ---- Copilot review
    def post(self, path, body):
        s = self.s
        h = s.Handler.__new__(s.Handler)
        h.path, h.headers = path, {"Host": "127.0.0.1", "X-Nixi-Token": s.TOKEN}
        h._body = lambda: json.dumps(body).encode()
        h._json = mock.Mock()
        h.do_POST()
        return h._json

    def test_turning_stages_off_clears_and_gates(self):
        s = self.s
        seen = []
        with mock.patch.object(s.BUS, "pub", lambda **kw: seen.append(kw)), mock.patch.object(s.quick, "projects", return_value={}):
            self.post("/api/settings", {"answer_stages": False})
            self.assertFalse(s.CFG.get("answer_stages", True))
            self.assertIn({"t": "stage_close"}, seen)
            self.assertIsNone(s.STAGES.current())
            self.assertIsNone(s.STAGES.back())                    # nothing to restore either
            self.assertEqual(s.stage_act(self.tok, "copy"), {"ok": False, "error": "off"})
            self.assertEqual(s.stage_act("", "back"), {"ok": False, "error": "off"})
            s.CFG["answer_stages"] = True

    def test_off_means_no_fast_path_and_no_run(self):
        with mock.patch.dict(self.s.CFG, {"answer_stages": False}):
            evs, prompts, j = self.ask({"stage": self.tok, "act": "run"})
            self.assertEqual((prompts, j.call_args[0][1]), ([], 410))
            evs, prompts, _ = self.ask({"prompt": "run the first one"})
            self.assertEqual(prompts[0][1], None)                 # an ordinary turn

    def test_reply_finished_after_turning_off_gets_no_stage(self):
        s = self.s
        block = '\n<<stage>>{"v":1,"kind":"facts","title":"t","points":["p"]}'

        def fake(prompt, emit, *_):
            emit(t="delta", text="Here." + block)
            s.CFG["answer_stages"] = False
            emit(t="result", text="", is_error=False)
            return "done"

        h = s.Handler.__new__(s.Handler)
        h.wfile = io.BytesIO()
        h.send_response, h.send_header, h.end_headers = mock.Mock(), mock.Mock(), mock.Mock()
        h._body = lambda: json.dumps({"prompt": "tides?"}).encode()
        try:
            with mock.patch.object(s, "run_bridge", fake), mock.patch.object(s, "BRIDGED", True), mock.patch.object(s, "hist_add"), \
                    mock.patch.object(s, "pick_auto", return_value=None), mock.patch.object(s.recall, "add"), mock.patch.dict(s.CFG, {"auto_compact": False}):
                h.ask()
        finally:
            s.CFG["answer_stages"] = True
        out = h.wfile.getvalue().decode()
        self.assertNotIn('"stage"', out)
        self.assertNotIn("<<stage", out)

    def test_quick_leaves_stage_phrases_to_ask(self):
        s = self.s
        with mock.patch.object(s, "BRIDGED", True), mock.patch.object(s.quick, "handle", side_effect=AssertionError("music took it")):
            self.assertEqual(self.post("/api/quick", {"text": "go back"}).call_args[0][0], {"handled": False})
            s.STAGES.close()                                       # nothing on screen, but one to come back to
            self.assertEqual(self.post("/api/quick", {"text": "go back"}).call_args[0][0], {"handled": False})
            self.assertEqual(self.post("/api/quick", {"text": "show it"}).call_args[0][0], {"handled": False})

    def test_quick_still_does_music_without_a_stage(self):
        s = self.s
        s.STAGES.clear()
        with mock.patch.object(s, "BRIDGED", True), mock.patch.object(s.quick, "handle", return_value={"say": "Going back."}) as h, \
                mock.patch.object(s.recall, "answer", return_value=None), mock.patch.object(s, "state_info", return_value={}):
            j = self.post("/api/quick", {"text": "go back"})
        self.assertTrue(h.called)
        self.assertTrue(j.call_args[0][0]["handled"])

    def test_run_done_needs_a_completed_tool_and_failed_shows_why(self):
        for status, want in (("completed", ["waiting", "running", "done"]), ("failed", ["waiting", "running", "failed"]), ("", ["waiting", "running", "failed"])):
            evs, _, _ = self.ask({"stage": self.tok, "act": "run"}, tool=status or "in_progress")
            st = [e for e in evs if e["t"] == "stage_status"]
            self.assertEqual([e["state"] for e in st], want, status)
        evs, _, _ = self.ask({"stage": self.tok, "act": "run"}, tool="failed")
        self.assertEqual([e for e in evs if e.get("state") == "failed"][0]["error"], "Bash failed")

    def test_run_bridge_passes_the_tool_status_on(self):
        events = []
        p = mock.Mock(stdout=iter([json.dumps({"type": "tool", "title": "Bash", "status": "failed"}) + "\n", json.dumps({"type": "done"}) + "\n"]))
        with mock.patch.object(self.s.BRIDGE, "start", return_value=p), mock.patch.object(self.s.BRIDGE, "send"):
            self.s.run_bridge("x", lambda **kw: events.append(kw))
        self.assertEqual([e["status"] for e in events if e["t"] == "tool"], ["failed"])

    def test_stage_trust(self):
        for conf, want in (({"permissionMode": "yolo", "trust": "guide"}, "yolo"), ({"trust": "mechanic"}, "mechanic"), ({}, "unknown")):
            with mock.patch.object(self.s, "nixi_conf", return_value=conf):
                self.assertEqual(self.s.stage_trust(), want)


if __name__ == "__main__":
    unittest.main()
