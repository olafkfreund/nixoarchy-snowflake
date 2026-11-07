"""#216: voice outcome counts and corrections, with no real mic, pactl or HTTP listener."""
import datetime
import io
import json
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from test_speakable import _ServerEnv


class HeardCountsTest(_ServerEnv):
    def setUp(self):
        s = self.server
        self.data = tempfile.TemporaryDirectory(prefix="nixi-heard-")
        self.addCleanup(self.data.cleanup)
        patch = mock.patch.object(s, "DATA_DIR", Path(self.data.name) / "data")
        patch.start()
        self.addCleanup(patch.stop)
        C = s.HeardCounts
        C._days, C._saved, C.last = None, 0.0, None
        self.addCleanup(setattr, C, "_days", None)
        self.addCleanup(setattr, C, "_saved", 0.0)
        self.addCleanup(setattr, C, "last", None)

    def day(self, date):
        real = datetime.datetime

        class Clock(real):
            @classmethod
            def now(cls):
                return real.combine(date, datetime.time())

        return mock.patch.object(self.server, "datetime", types.SimpleNamespace(datetime=Clock, date=datetime.date))

    def handler(self, path, body=None, token=True):
        s = self.server
        h = s.Handler.__new__(s.Handler)
        h.path = path
        h.headers = {"Host": "127.0.0.1", "X-Nixi-Token": s.TOKEN if token else ""}
        h.wfile = io.BytesIO()
        h._body = lambda: json.dumps(body or {}).encode()
        h.send_response = mock.Mock()
        h.send_header = mock.Mock()
        h.end_headers = mock.Mock()
        return h

    def reply(self, h):
        raw = h.wfile.getvalue()
        return json.loads(raw) if raw and raw[:1] == b"{" else raw

    def test_cells_rollover_prune_and_numeric_file(self):
        s, C = self.server, self.server.HeardCounts
        today = datetime.date(2026, 11, 7)
        with self.day(today - datetime.timedelta(days=13)):
            C.add("wake", "on", "sent")
            C.save()
        with self.day(today - datetime.timedelta(days=6)):
            C.add("follow", "unknown", "ignored")
        with self.day(today):
            C.add("wake", "on", "sent")
            C.add("barge", "off", "not_me")
            snap = C.snapshot()
            self.assertEqual(snap["totals"]["wake"]["on"]["sent"], 1)
            self.assertEqual(snap["totals"]["follow"]["unknown"]["ignored"], 1)
            self.assertNotIn((today - datetime.timedelta(days=13)).isoformat(), snap["days"])
            C.save()
            stored = json.loads((s.DATA_DIR / "heard-counts.json").read_text())
            self.assertIn((today - datetime.timedelta(days=13)).isoformat(), stored)
            self.assertEqual(stored[today.isoformat()]["barge"]["off"]["not_me"], 1)
            self.assertTrue(all(isinstance(v, int) and not isinstance(v, bool)
                                for paths in stored.values() for medias in paths.values()
                                for outcomes in medias.values() for v in outcomes.values()))
            self.assertTrue(set(stored).issubset({(today - datetime.timedelta(days=i)).isoformat() for i in range(14)}))
            C._days = None
            self.assertEqual(C.snapshot()["totals"], snap["totals"])
        with self.day(today + datetime.timedelta(days=1)):
            C.snapshot()
            self.assertNotIn((today - datetime.timedelta(days=13)).isoformat(), C._days)

    def test_load_filters_bad_values_and_save_failure_is_harmless(self):
        s, C = self.server, self.server.HeardCounts
        day = datetime.date.today().isoformat()
        path = s.DATA_DIR / "heard-counts.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({day: {"wake": {"on": {"sent": 3, "ignored": "2", "not_me": True},
                                             "bad": {"sent": 9}}, "other": {"on": {"sent": 2}}},
                                    "invalid": {"wake": {"on": {"sent": 8}}}}))
        self.assertEqual(C.snapshot()["totals"], {"wake": {"on": {"sent": 3}}})
        C.add("wake", "on", "sent")
        with mock.patch.object(s.os, "replace", side_effect=OSError("disk full")):
            C.save()
        self.assertEqual(C.snapshot()["totals"]["wake"]["on"]["sent"], 4)

    def test_add_limits_writes_to_once_a_minute(self):
        C = self.server.HeardCounts
        with mock.patch.object(C, "save", wraps=C.save) as save, mock.patch.object(self.server.time, "monotonic", side_effect=[100, 100, 130, 161, 161]):
            C.add("wake", "off", "sent")
            C.add("wake", "off", "sent")
            C.add("wake", "off", "sent")
        self.assertEqual(save.call_count, 2)

    def test_wake_barge_and_follow_events_have_path_and_media(self):
        s, W = self.server, self.server.Wake
        events = []
        with mock.patch.object(s.FLOOR, "floor_overlaps", return_value=False), \
             mock.patch.object(s.MicAuto, "learn"), mock.patch.object(s, "speech_seconds", return_value=1), \
             mock.patch.object(s, "transcribe_pcm", side_effect=["hey nixi hello", "hey nixi hello", "hello there"]), \
             mock.patch.object(s, "media_playing", side_effect=[True, False, None]), \
             mock.patch.object(s.BUS, "pub", side_effect=lambda **kw: events.append(kw)), \
             mock.patch.object(W, "in_window", side_effect=[False, False, True, True]):
            for speaking in (False, True, False):
                with mock.patch.object(W, "speaking", return_value=speaking):
                    W.check(b"\0" * 32000, time.monotonic())
        self.assertIn({"t": "wake", "text": "hello", "path": "wake", "media": "on"}, events)
        self.assertIn({"t": "barge", "listen": True, "text": "hello", "path": "barge", "media": "off"}, events)
        self.assertIn({"t": "wake", "text": "hello there", "follow": True, "path": "follow", "media": "unknown"}, events)

    def test_not_me_all_languages_full_phrase_speech_and_expiry(self):
        s, W, C = self.server, self.server.Wake, self.server.HeardCounts
        for language, phrase in (("en", "that wasn't for you"), ("en", "not you"),
                                 ("en", "I wasn't talking to you"), ("en", "that wasn't meant for you"),
                                 ("nb", "det var ikke til deg"), ("nb", "ikke deg"),
                                 ("pl", "to nie do ciebie"), ("pl", "nie ty")):
            with self.subTest(language=language, phrase=phrase), \
                 mock.patch.object(s.stages, "lang_active", return_value=language), \
                 mock.patch.object(s.FLOOR, "floor_overlaps", return_value=False), \
                 mock.patch.object(s, "speech_seconds", return_value=1), \
                 mock.patch.object(s, "transcribe_pcm", return_value=phrase), \
                 mock.patch.object(s, "media_playing", return_value=False), \
                 mock.patch.object(s.MicAuto, "learn"), mock.patch.object(s.BUS, "pub") as pub, \
                 mock.patch.object(s.Speaker, "say") as say, mock.patch.object(W, "hush") as hush:
                C.last = ("wake", "on", time.monotonic())
                with mock.patch.object(W, "speaking", return_value=True):
                    W.check(b"\0" * 32000, time.monotonic())
                pub.assert_called_once_with(t="barge", listen=False, text="")
                hush.assert_called_once()
                say.assert_not_called()
                self.assertFalse(C.mark_open())
                C.last = ("follow", "unknown", time.monotonic())
                pub.reset_mock()
                with mock.patch.object(W, "speaking", return_value=False):
                    W.check(b"\0" * 32000, time.monotonic())
                pub.assert_not_called()
                say.assert_called_once_with("Sorry.", None, None, False, None)
                self.assertFalse(C.mark_open())
        with mock.patch.object(s.FLOOR, "floor_overlaps", return_value=False), \
             mock.patch.object(s, "speech_seconds", return_value=1), mock.patch.object(s, "media_playing", return_value=False), \
             mock.patch.object(s.MicAuto, "learn"), mock.patch.object(W, "speaking", return_value=False), \
             mock.patch.object(s.BUS, "pub") as pub, mock.patch.object(s.Speaker, "say") as say:
            for phrase in ("not you please answer", "that wasn't for you today", "not you"):
                C.last = ("wake", "off", time.monotonic() - 121)
                with mock.patch.object(s, "transcribe_pcm", return_value=phrase):
                    W.check(b"\0" * 32000, time.monotonic())
            pub.assert_not_called()
            say.assert_not_called()

    def test_ask_counts_sent_ignored_and_no_heard(self):
        s, C = self.server, self.server.HeardCounts
        def answer(prompt, emit, partial):
            emit(t="delta", text="[ignore]" if "ignore" in prompt else "Hello")
            emit(t="result", text="")
        with mock.patch.object(s, "BRIDGED", False), mock.patch.object(s, "run_claude", side_effect=answer), \
             mock.patch.object(s, "pick_auto", return_value=None), mock.patch.object(s, "hist_add"):
            for body in ({"prompt": "hello", "heard": {"path": "wake", "media": "on"}},
                         {"prompt": "ignore", "follow": True, "heard": {"path": "follow", "media": "unknown"}},
                         {"prompt": "plain"}):
                h = self.handler("/api/ask", body)
                h.do_POST()
                self.assertEqual(h.send_response.call_args.args[0], 200)
        totals = C.snapshot()["totals"]
        self.assertEqual(totals["wake"]["on"]["sent"], 1)
        self.assertEqual(totals["follow"]["unknown"], {"sent": 1, "ignored": 1})
        self.assertIsNone(C.last)      # an ignored reply has nothing to mark "that wasn't me"

    def test_busy_and_stage_answers_do_not_count_or_replace_last(self):
        s, C = self.server, self.server.HeardCounts
        old = ("barge", "off", time.monotonic())
        C.last = old
        body = {"prompt": "hello", "heard": {"path": "wake", "media": "on"}}
        s.ST.lock.acquire()
        try:
            with mock.patch.object(s, "BRIDGED", False), mock.patch.object(s, "pick_auto", return_value=None):
                h = self.handler("/api/ask", body)
                h.do_POST()
            self.assertEqual(h.send_response.call_args.args[0], 409)
        finally:
            s.ST.lock.release()
        with mock.patch.object(s, "BRIDGED", True), mock.patch.object(s, "stages_on", return_value=True), \
             mock.patch.object(s.STAGES, "current", return_value={"kind": "facts"}), \
             mock.patch.object(s.STAGES, "visible", return_value=True), \
             mock.patch.object(s.stages, "fast_path", return_value=("ask", 0)):
            h = self.handler("/api/ask", body)
            h.do_POST()
            self.assertEqual(h.send_response.call_args.args[0], 200)
        self.assertEqual(C.snapshot()["totals"], {})
        self.assertEqual(C.last, old)

    def test_routes_need_window_token_and_mark_once(self):
        s, C = self.server, self.server.HeardCounts
        C.last = ("wake", "on", time.monotonic())
        for path, method in (("/api/heard", "do_GET"), ("/api/heard/not-me", "do_POST")):
            h = self.handler(path, token=False)
            getattr(h, method)()
            self.assertEqual(h.send_response.call_args.args[0], 403)
            self.assertEqual(C.last[:2], ("wake", "on"))
        h = self.handler("/api/heard")
        h.do_GET()
        self.assertTrue(self.reply(h)["mark_open"])
        h = self.handler("/api/heard/not-me")
        h.do_POST()
        self.assertEqual(self.reply(h), {"ok": True})
        h = self.handler("/api/heard/not-me")
        h.do_POST()
        self.assertEqual(self.reply(h), {"ok": False})
        self.assertEqual(C.snapshot()["totals"]["wake"]["on"]["not_me"], 1)


    def test_not_me_while_thinking_stops_the_turn_and_english_always_works(self):
        s, W, C = self.server, self.server.Wake, self.server.HeardCounts
        with mock.patch.object(s.stages, "lang_active", return_value="nb"), \
             mock.patch.object(s.FLOOR, "floor_overlaps", return_value=False), \
             mock.patch.object(s, "speech_seconds", return_value=1), \
             mock.patch.object(s, "transcribe_pcm", return_value="that wasn\u2019t for you"), \
             mock.patch.object(s, "media_playing", side_effect=AssertionError("pactl before the not-me check")), \
             mock.patch.object(s.MicAuto, "learn"), mock.patch.object(s.BUS, "pub"), \
             mock.patch.object(s.Speaker, "say") as say, mock.patch.object(s, "stop_proc") as stop, \
             mock.patch.object(W, "speaking", return_value=False), \
             mock.patch.object(s.ST, "lock") as lock:
            lock.locked.return_value = True
            C.last, C.last_turn = ("wake", "on", time.monotonic()), C.turn
            W.check(b"\0" * 32000, time.monotonic())
            stop.assert_called_once()
            say.assert_called_once_with("Sorry.", None, None, False, None)
            stop.reset_mock(); say.reset_mock()
            C.last, C.last_turn = ("wake", "on", time.monotonic()), C.turn - 1    # a later typed turn is running
            W.check(b"\0" * 32000, time.monotonic())
            stop.assert_not_called()                                             # (the earlier answer is marked, the new turn runs on)
            say.assert_called_once_with("Sorry.", None, None, False, None)

    def test_a_late_count_is_saved_by_a_timer(self):
        C = self.server.HeardCounts
        with mock.patch.object(self.server.threading, "Timer") as timer, mock.patch.object(C, "save") as save:
            C._saved, C._flush = time.monotonic(), None
            C.add("wake", "off", "sent")
            C.add("wake", "off", "ignored")
            timer.assert_called_once()
            self.assertEqual(timer.call_args.args[0], 60)
            save.assert_not_called()
            timer.call_args.args[1]()                    # the minute passes
            save.assert_called_once()
            self.assertIsNone(C._flush)


if __name__ == "__main__":
    unittest.main()
