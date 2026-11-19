import io
import threading
import unittest
from unittest import mock

from test_speakable import _ServerEnv


class CodePauseTest(_ServerEnv):
    def setUp(self):
        self.S = self.server
        self.C = self.S.CodePause
        with self.C.lock:
            self.C.keys.clear()
            self.C.pending = self.C.sent = 0
            self.C.last_watch = -1e9
            self.C.until = 0.0
            self.C.logged = False
        self.C.wake.clear()
        saved = dict(self.S.CFG)
        self.addCleanup(lambda: (self.S.CFG.clear(), self.S.CFG.update(saved)))
        self.S.CFG["phone_on"] = True
        self.phone = mock.Mock(session=1, connected=True, snap={"clipboardPauses": []})
        patch = mock.patch.object(self.S, "Phone", self.phone)
        patch.start()
        self.addCleanup(patch.stop)
        self.phone.call.return_value = {"expires": 120}
        self.toasts = mock.patch.object(self.S.BUS, "pub")
        self.pub = self.toasts.start()
        self.addCleanup(self.toasts.stop)
        asleep = mock.patch.object(self.S.Wake, "asleep", False)
        asleep.start()
        self.addCleanup(asleep.stop)

    def test_fallback_counts_only_without_recent_watch(self):
        with mock.patch.object(self.S.time, "monotonic", return_value=100):
            self.C.seen("w")
        with mock.patch.object(self.S.time, "monotonic", return_value=101):
            self.C.seen("s", fallback=True)
        self.assertEqual(self.C.pending, 1)
        self.assertIn("s", self.C.keys)
        with mock.patch.object(self.S.time, "monotonic", return_value=111):
            self.C.seen("s2", fallback=True)
            self.C.seen("s2", fallback=True)
        self.assertEqual(self.C.pending, 2)
        with mock.patch.object(self.S.time, "monotonic", return_value=112):
            self.C.seen("w")
        self.assertEqual(self.C.last_watch, 100)
        with mock.patch.object(self.S.time, "monotonic", return_value=113):
            self.C.seen("s3", fallback=True)
        self.assertEqual(self.C.pending, 3)

    def test_fallback_counts_without_watch(self):
        self.C.seen("shell", fallback=True)
        self.assertEqual(self.C.pending, 1)

    def test_confirmed_hold_is_silent_while_asleep(self):
        self.C.seen("a")
        with mock.patch.object(self.S.time, "time", return_value=0), mock.patch.object(self.S.Wake, "asleep", True):
            self.C.turn()
        self.assertEqual(self.C.until, 120)
        self.pub.assert_not_called()

    def test_request_and_coalescing(self):
        for key in ("a", "b", "c"):
            self.C.seen(key)
        with mock.patch.object(self.S.time, "time", return_value=0):
            self.C.turn()
        self.phone.call.assert_called_once_with("clipboard.pauseOwned", owner="nixi-otp", expires=120)
        self.assertEqual((self.C.sent, self.C.until), (1, 120))
        self.pub.assert_called_once_with(t="toast", text=self.S.lang.t("phone.clip_paused"))

    def test_dedupe_eviction_and_age(self):
        for i in range(64):                                      # (keys "9" < "10" in age, not in name: eviction goes by time)
            with mock.patch.object(self.S.time, "monotonic", return_value=1000 + 63 - i):
                self.C.seen(str(i))
        with mock.patch.object(self.S.time, "monotonic", return_value=1100):
            self.C.seen("0")
            self.assertEqual(self.C.pending, 64)
            self.C.seen("64")                                    # evicts "63", the oldest, not "0"
            self.assertNotIn("63", self.C.keys)
            self.C.seen("0")
            self.assertEqual((len(self.C.keys), self.C.pending), (64, 65))
            self.C.seen("63")
            self.assertEqual(self.C.pending, 66)
        with mock.patch.object(self.S.time, "monotonic", return_value=1700):
            self.C.seen("64")
            self.assertEqual(self.C.pending, 67)

    def test_arrival_during_call_waits_for_next_turn(self):
        entered, release = threading.Event(), threading.Event()

        def call(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(2))
            return {"expires": 120}

        self.phone.call.side_effect = call
        self.C.seen("a")
        clock = mock.patch.object(self.S.time, "time", return_value=0)
        clock.start()
        self.addCleanup(clock.stop)
        worker = threading.Thread(target=self.C.turn)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.C.seen("b")
            self.assertEqual(self.C.pending, 1)
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.C.turn()
        self.assertEqual(self.phone.call.call_count, 2)

    def test_five_requests_per_hold_then_resets_after_expiry(self):
        with mock.patch.object(self.S.time, "time", return_value=0):
            for i in range(6):
                self.C.seen(str(i))
                self.C.turn()
            self.assertEqual((self.phone.call.call_count, self.C.sent, self.C.pending), (5, 5, 0))
        with mock.patch.object(self.S.time, "time", return_value=121):
            self.phone.call.return_value = {"expires": 240}
            self.C.seen("new")
            self.C.turn()
        self.assertEqual((self.phone.call.call_count, self.C.sent), (6, 1))

    def test_timeout_renewal_extends_unconfirmed_hold(self):
        with mock.patch.object(self.S.time, "time", return_value=0):
            self.C.seen("first")
            self.C.turn()
        with mock.patch.object(self.S.time, "time", return_value=119):
            self.phone.call.side_effect = TimeoutError()
            self.C.seen("second")
            self.C.turn()
        self.assertEqual((self.C.sent, self.C.until), (2, 239))
        with mock.patch.object(self.S.time, "time", return_value=130):
            self.C.seen("third")
            self.C.turn()
        self.assertEqual(self.C.sent, 3)

    def test_outcome_accounting_and_one_safe_error_line(self):
        failures = (
            (self.S.phone.NotSent("private row"), 0, 0),
            (TimeoutError("private row"), 1, 120),
            (ConnectionError("private row"), 1, 120),
            (RuntimeError("private row"), 1, 0),
            (ValueError("private row"), 1, 0),
            ({}, 1, 120),
            ({"expires": "x"}, 1, 120),
            ({"expires": True}, 1, 120),
            ({"expires": -5}, 1, 120),
            (None, 1, 120),
            ("changed", 1, 120),
            ({"expires": 120}, 1, 120),
        )
        err = io.StringIO()
        with mock.patch.object(self.S.time, "time", return_value=0), mock.patch.object(self.S.sys, "stderr", err):
            for i, (outcome, sent, until) in enumerate(failures):
                with self.subTest(outcome=outcome):
                    self.C.sent, self.C.until = 0, 0
                    self.pub.reset_mock()
                    self.phone.session = 1
                    self.phone.call.side_effect = outcome if isinstance(outcome, Exception) else None
                    if not isinstance(outcome, Exception):
                        self.phone.call.return_value = {"expires": 120} if outcome == "changed" else outcome
                    if outcome == "changed":
                        self.phone.call.side_effect = lambda *a, **k: (setattr(self.phone, "session", 2), {"expires": 120})[1]
                    self.C.seen(str(i))
                    self.C.turn()
                    self.assertEqual((self.C.sent, self.C.until), (sent, until))
                    self.assertEqual(self.pub.call_count, 1 if i == len(failures) - 1 else 0)
        self.assertEqual(err.getvalue(), "[nixi] code pause: NotSent\n")
        self.assertNotIn("private row", err.getvalue())

    def test_session_change_keeps_old_hold_open(self):
        with mock.patch.object(self.S.time, "time", return_value=0):
            self.C.seen("a")
            self.C.turn()
        with mock.patch.object(self.S.time, "time", return_value=119):
            self.phone.call.side_effect = lambda *a, **k: (setattr(self.phone, "session", 2), {"expires": 240})[1]
            self.C.seen("b")
            self.C.turn()
        self.assertEqual(self.C.until, 239)
        with mock.patch.object(self.S.time, "time", return_value=130):
            self.C.seen("c")
            self.C.turn()
        self.assertEqual(self.C.sent, 3)

    def test_ineligible_gives_request_back_without_call(self):
        with mock.patch.object(self.S.time, "time", return_value=0):
            for i, (phone_on, connected, snap) in enumerate(((False, True, {"clipboardPauses": []}),
                                                              (True, False, {"clipboardPauses": []}), (True, True, {}))):
                with self.subTest(phone_on=phone_on, connected=connected, snap=snap):
                    self.S.CFG["phone_on"] = phone_on
                    self.phone.connected, self.phone.snap = connected, snap
                    self.C.seen(str(i))
                    self.C.turn()
                    self.assertEqual(self.C.sent, 0)
                    self.phone.call.assert_not_called()
            self.S.CFG["phone_on"] = True
            self.phone.connected, self.phone.snap = True, {"clipboardPauses": []}
            self.C.seen("eligible")
            self.C.turn()
        self.phone.call.assert_called_once()

    def test_confirmed_hold_takes_flux_expiry(self):
        self.phone.call.return_value = {"expires": 150}         # (earlier or later than start + 120: Flux's value wins)
        self.C.seen("a")
        with mock.patch.object(self.S.time, "time", return_value=0):
            self.C.turn()
        self.assertEqual(self.C.until, 150)

    def test_each_confirmed_renewal_toasts(self):
        with mock.patch.object(self.S.time, "time", return_value=0):
            for key in ("a", "b"):
                self.C.seen(key)
                self.C.turn()
        self.assertEqual(self.pub.call_args_list, [mock.call(t="toast", text=self.S.lang.t("phone.clip_paused"))] * 2)

    def test_inbox_start_starts_code_worker_once(self):
        with mock.patch.object(self.S.Inbox, "thread", None), mock.patch.object(self.C, "thread", None), \
             mock.patch.object(self.S.threading, "Thread") as thread:
            self.S.Inbox.start()
            self.S.Inbox.start()
        self.assertEqual(thread.call_count, 2)


if __name__ == "__main__":
    unittest.main()
