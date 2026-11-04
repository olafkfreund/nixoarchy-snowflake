import json
import time
import unittest
import urllib.request
from unittest import mock

from test_speakable import _ServerEnv


class FollowHoldTest(_ServerEnv):
    def setUp(self):
        s = self.server
        s.Speaker.stop()
        W = s.Wake
        self.addCleanup(s.CFG.__setitem__, "follow_up", s.CFG.get("follow_up"))
        s.CFG["follow_up"] = 4
        self.addCleanup(self.reset_wake)
        W.held = False
        W.cut = None
        W.hush()
        W.follow_from = 0.0
        self.events = []
        for target, name, kw in (
            (s.MicAuto, "learn", {}),
            (s, "speech_seconds", {"return_value": 1}),
            (s.FLOOR, "floor_overlaps", {"return_value": False}),
            (s.BUS, "pub", {"side_effect": lambda **event: self.events.append(event)}),
        ):
            patch = mock.patch.object(target, name, **kw)
            patch.start()
            self.addCleanup(patch.stop)

    def reset_wake(self):
        W = self.server.Wake
        W.held = False
        W.cut = None
        W.hush()
        W.follow_from = 0.0

    def test_hold_blocks_new_window(self):
        W = self.server.Wake
        end = time.monotonic()
        W.held = True
        W.talking_until(end)
        self.assertEqual(W.follow_until, 0)
        self.assertFalse(W.window_open())
        W.held = False
        W.talking_until(end)
        self.assertGreater(W.follow_until, end)
        self.assertTrue(W.window_open())

    def test_follow_route_holds_and_keeps_existing_actions(self):
        s, W = self.server, self.server.Wake
        srv = s.ThreadingHTTPServer(("127.0.0.1", 0), s.Handler)
        s.threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        base = "http://127.0.0.1:%d/api/follow" % srv.server_address[1]

        def post(body):
            req = urllib.request.Request(base, data=json.dumps(body).encode(),
                                         headers={"X-Nixi-Token": s.TOKEN, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(json.load(resp), {"ok": True})

        W.talking_until(time.monotonic())
        self.assertTrue(W.window_open())
        post({"act": "hold", "on": True})
        self.assertTrue(W.held)
        self.assertEqual(W.follow_until, 0)
        self.assertEqual(W.cut, "cancel")
        post({"act": "hold", "on": False})
        self.assertFalse(W.held)
        self.assertEqual(W.cut, "cancel")
        self.assertEqual(W.follow_until, 0)
        W.talking_until(time.monotonic())
        post({"act": "finish"})
        self.assertEqual(W.cut, "finish")
        self.assertGreater(W.follow_until, 0)
        post({"act": "cancel"})
        self.assertEqual(W.cut, "cancel")
        self.assertEqual(W.follow_until, 0)

    def test_cancel_during_transcription_drops_follow_up(self):
        W = self.server.Wake
        started = time.monotonic()
        W.follow_from, W.follow_until = started - 1, started + 4

        def transcribe(*a, **k):
            W.end_follow("cancel")
            return "what time is it"

        with mock.patch.object(self.server, "transcribe_pcm", side_effect=transcribe):
            W.check(b"\0" * 32000, started)
        self.assertFalse(any(e.get("t") == "wake" for e in self.events))

    def test_expired_window_keeps_started_speech(self):
        W = self.server.Wake
        started = time.monotonic()
        W.follow_from, W.follow_until = started - 1, started + 0.01

        def transcribe(*a, **k):
            time.sleep(0.03)
            return "what time is it"

        with mock.patch.object(self.server, "transcribe_pcm", side_effect=transcribe):
            W.check(b"\0" * 32000, started)
        self.assertIn({"t": "wake", "text": "what time is it", "follow": True}, self.events)

    def test_new_window_drops_old_speech(self):
        W = self.server.Wake
        started = time.monotonic()
        W.follow_from, W.follow_until = started - 1, started + 4

        def transcribe(*a, **k):
            W.follow_from, W.follow_until = started + 1, started + 5
            return "what time is it"

        with mock.patch.object(self.server, "transcribe_pcm", side_effect=transcribe):
            W.check(b"\0" * 32000, started)
        self.assertFalse(any(e.get("t") == "wake" for e in self.events))

    def test_wake_word_survives_closed_window(self):
        W = self.server.Wake
        started = time.monotonic()
        W.follow_from, W.follow_until = started - 1, started + 4

        def transcribe(*a, **k):
            W.end_follow("cancel")
            return "hey nixi what time is it"

        with mock.patch.object(self.server, "transcribe_pcm", side_effect=transcribe):
            W.check(b"\0" * 32000, started)
        self.assertIn({"t": "wake", "text": "what time is it"}, self.events)


if __name__ == "__main__":
    unittest.main()
