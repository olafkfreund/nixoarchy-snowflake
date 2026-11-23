"""The handset's state, privacy gate and guarded actions."""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import nixi_env


class Calls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_env = os.environ.copy()
        cls.home = tempfile.mkdtemp(prefix="nixi-call-")
        for key, part in (("HOME", ""), ("XDG_CONFIG_HOME", "config"),
                          ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
            os.environ[key] = str(Path(cls.home) / part)
            Path(os.environ[key]).mkdir(exist_ok=True)
        os.environ["XDG_RUNTIME_DIR"] = nixi_env.run_dir()
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
        import server
        cls.s = server
        if not str(server.CONF_PATH).startswith(tempfile.gettempdir()):
            raise RuntimeError("server imported under real HOME")
        nixi_env.check_floor_path(server.FLOOR.path)

    @classmethod
    def tearDownClass(cls):
        os.environ.clear()
        os.environ.update(cls.old_env)
        shutil.rmtree(cls.home, ignore_errors=True)

    def setUp(self):
        s = self.s
        self.cfg = dict(s.CFG)
        s.CFG["phone_on"] = True
        self.addCleanup(lambda: (s.CFG.clear(), s.CFG.update(self.cfg)))
        s.Call.clear()
        self.addCleanup(s.Call.clear)
        s.Call.missed.clear()
        s.Call.on_missed = s.Call.on_answered = None
        self.phone = mock.Mock(connected=True)
        self.phone.devices.return_value = []
        self.hfp = mock.Mock()
        self.hfp.lock = threading.RLock()
        self.hfp.calls = {}
        self.hfp.audio_here.return_value = False
        self.hfp.calls_on.side_effect = lambda ag: [c for c in self.hfp.calls.values() if c["ag"] == ag and c["state"] != "disconnected"]
        self.pub = mock.Mock()
        self.ring = mock.Mock()
        for obj, name, value in ((s, "Phone", self.phone), (s, "Hfp", self.hfp), (s.BUS, "pub", self.pub),
                                 (s.Desk, "locked", lambda: False), (s.peers, "current", lambda: []),
                                 (s.Ring, "follow", self.ring)):   # (never a real ring from a test)
            patch = mock.patch.object(obj, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def flux(self, state="ringing", number="12345678", caller="Ada", hands=None, waiting=False):
        self.phone.devices.return_value = [{"id": "pixel", "name": "Pixel", "can": {"answer"},
                                            "call": {"id": "flux-1", "state": state, "number": number,
                                                     "caller": caller, "handsFree": hands or [], "waiting": waiting,
                                                     "since": 1}}]

    def host(self, state="incoming", number="12345678", name=None):
        self.hfp.calls = {"/ag1/call1": {"path": "/ag1/call1", "ag": "/ag1", "state": state,
                                           "number": number, "name": name}}

    def test_correlation_both_orders_and_path_generation(self):
        for first in ("flux", "host"):
            self.phone.devices.return_value = []
            self.hfp.calls = {}
            self.s.Call.clear()
            getattr(self, first)()
            self.s.Call.sync()
            ident, gen = self.s.Call.row["id"], self.s.Call.row["gen"]
            getattr(self, "host" if first == "flux" else "flux")()
            self.s.Call.sync()
            self.assertEqual(self.s.Call.row["id"], ident)
            self.assertGreaterEqual(self.s.Call.row["gen"], gen)
            self.assertEqual(self.s.Call.row["path"], "host")

    def test_paths_names_privacy_and_answer_time(self):
        self.flux(caller="Unknown caller")
        self.s.Call.sync()
        self.assertEqual(self.s.Call.current_event()["number"], "12345678")
        self.assertIsNone(self.s.Call.row["who"])
        self.assertEqual(self.s.Call.row["path"], "phone")
        self.host(name="HFP Ada")
        self.s.Call.sync()
        self.assertEqual(self.s.Call.row["who"], "HFP Ada")
        self.assertIsNone(self.s.Call.current_event()["number"])
        self.assertNotIn("flux_id", self.s.Call.current_event())
        self.flux(state="talking", caller="Ada")
        self.hfp.calls.clear()
        self.s.Call.sync()
        self.assertEqual(self.s.Call.row["path"], "phone")
        self.assertGreater(self.s.Call.row["answered_at"], 1)
        self.assertEqual(self.s.Call.row["note"], "On phone")
        self.s.peers.current = lambda: [{"name": "razer"}]
        self.flux(hands=["razer"])
        self.s.Call.sync()
        self.assertEqual((self.s.Call.row["path"], self.s.Call.row["keys"]), ("watch", []))
        with mock.patch.object(self.s.Desk, "locked", return_value=None):
            self.assertIsNone(self.s.Call.current_event())
            self.s.Call.sync()
        self.assertFalse(self.s.Call.visible())

    def test_second_call_missed_and_end(self):
        missed = mock.Mock()
        self.s.Call.on_missed = missed
        self.host()
        self.flux(waiting=True)
        self.s.Call.sync()
        self.assertEqual(self.s.Call.row["keys"], [])
        self.assertEqual(self.s.Call.row["note"], "Second call: use your phone")
        self.phone.devices.return_value = []
        self.hfp.calls["/ag1/call1"]["state"] = "disconnected"
        self.s.Call.sync()
        missed.assert_called_once()
        self.s.Call.sync()
        missed.assert_called_once()
        self.s.Call.clear()
        self.host()
        self.s.Call.sync()
        self.hfp.calls["/ag1/call1"]["state"] = "active"
        self.hfp.audio_here.return_value = True
        self.s.Call.sync()
        self.assertEqual(self.s.Call.row["phase"], "active")
        self.hfp.calls["/ag1/call1"]["state"] = "disconnected"
        self.s.Call.sync()
        self.assertEqual(self.s.Call.row["phase"], "ended")
        self.s.Call.clear()
        self.assertFalse(self.s.Call.visible())

    def test_flux_end_reasons_and_answered_edge(self):
        answered = mock.Mock()
        missed = mock.Mock()
        self.s.Call.on_answered = answered
        self.s.Call.on_missed = missed
        self.flux()
        self.s.Call.sync()
        ident = self.s.Call.row["id"]
        self.flux(state="talking")
        self.s.Call.sync()
        self.s.Call.sync()
        answered.assert_called_once()
        self.phone.devices.return_value = [{"id": "pixel", "lastCall": {"id": "flux-1", "end": "hangup"}}]
        self.s.Call.sync()
        self.assertEqual(self.s.Call.row["phase"], "ended")
        self.s.Call.clear()
        self.flux()
        self.s.Call.sync()
        self.phone.devices.return_value = [{"id": "pixel", "missedCall": {"id": "flux-1"}}]
        self.s.Call.sync()
        missed.assert_called_once()
        self.assertFalse(self.s.Call.visible())
        self.flux()
        self.s.Call.sync()
        self.phone.devices.return_value = [{"id": "pixel", "lastCall": {"id": "flux-1", "end": "lost"}}]
        self.s.Call.sync()
        self.assertFalse(self.s.Call.visible())
        self.assertNotEqual(ident, self.s.Call.row["id"] if self.s.Call.row else None)

    def test_sse_current_is_gated(self):
        self.flux()
        self.s.Call.sync()
        sent, alive = [], [True]
        def emit(**event):
            sent.append(event)
            if event.get("t") == "call":
                alive[0] = False
        handler = object.__new__(self.s.Handler)
        handler._sse = lambda: (emit, alive)
        with mock.patch.object(self.s.Ambient, "situation", return_value={}), mock.patch.object(self.s.Mirror, "snapshot", return_value={}):
            handler.events()
        self.assertEqual([e["t"] for e in sent], ["hello", "situation", "mirror", "call"])
        self.assertNotIn("flux_id", sent[-1])
        with mock.patch.object(self.s.Desk, "locked", return_value=None):
            self.assertIsNone(self.s.Call.current_event())

    def test_action_busy_watchdog_and_http_click(self):
        self.host()
        self.s.Call.sync()
        row = self.s.Call.row.copy()
        entered, release = threading.Event(), threading.Event()
        self.hfp.answer.side_effect = lambda path: (entered.set(), release.wait(2), {"ok": True})[-1]
        result = []
        thread = threading.Thread(target=lambda: result.append(self.s.Call.act(row["id"], row["gen"], "answer")))
        thread.start()
        self.assertTrue(entered.wait(2))
        self.assertEqual(self.s.Call.act(row["id"], row["gen"], "answer"), {"ok": False, "busy": True})
        release.set()
        thread.join(2)
        self.assertEqual(result, [{"ok": True}])
        self.assertEqual(self.s.Call.act(row["id"], row["gen"] + 1, "answer"), {"ok": False, "stale": True})
        with mock.patch.object(self.s.lang, "t", return_value="Didn't work. Use your phone"):
            self.s.Call._watch(row["id"], row["gen"], "ringing")
        self.assertEqual(self.s.Call.row["keys"], [])
        server = self.s.ThreadingHTTPServer(("127.0.0.1", 0), self.s.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/api/call",
                                     data=json.dumps({"id": row["id"], "gen": row["gen"], "act": "answer"}).encode(),
                                     headers={"X-Nixi-Token": self.s.TOKEN, "Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(req)
        self.assertEqual(error.exception.code, 403)


class Wiring(Calls):
    """Plan step 8: the ring, the quiet, the lock edge, Phone off and HFP-only misses."""

    def test_ring_pcm_is_quiet_raw_mono(self):
        pcm = self.s.ring_pcm()
        rate = self.s.RING_RATE
        self.assertEqual(len(pcm), 2 * (2 * int(rate * .32) + int(rate * .12)))
        samples = __import__("array").array("h", pcm)
        self.assertLessEqual(max(abs(x) for x in samples), int(32767 * .2) + 1)
        self.assertGreater(max(samples), 1000)

    def test_ring_follows_phase_and_ignores_proactive(self):
        self.s.CFG["proactive"] = False
        self.ring.reset_mock()
        self.flux()
        self.s.Call.sync()
        self.ring.assert_called_with("ringing")
        self.flux(state="talking")
        self.s.Call.sync()
        self.ring.assert_called_with("active")
        self.s.CFG["proactive"] = True

    def test_ring_waits_for_speech_then_plays(self):
        s = self.s
        played = threading.Event()
        proc = mock.Mock()
        proc.poll.return_value = 0
        proc.stdin.write.side_effect = lambda b: played.set()
        idle = iter([False, False, True, True, True, True])
        with mock.patch.object(s, "make_player", return_value=proc) as mk, \
                mock.patch.object(s.Speaker, "idle", side_effect=lambda: next(idle, True)), \
                mock.patch.object(s.Ring, "allowed", return_value=True):
            ev = threading.Event()
            t = threading.Thread(target=s.Ring._loop, args=(ev,), daemon=True)
            t.start()
            self.assertTrue(played.wait(3))
            ev.set()
            t.join(5)
        mk.assert_called_with(s.RING_RATE)
        proc.stdin.write.assert_called_with(s.ring_pcm())

    def test_ring_gate(self):
        s = self.s
        with mock.patch.object(s, "audio_player_cmd", return_value=["paplay"]), \
                mock.patch.object(s.Wake, "asleep", False), mock.patch.object(s.Ambient, "meeting", False), \
                mock.patch.object(s.Ambient, "dnd", False):
            self.assertTrue(s.Ring.allowed())
            with mock.patch.object(s.Ambient, "dnd", True):
                self.assertFalse(s.Ring.allowed())
            with mock.patch.object(s.Desk, "locked", lambda: None):
                self.assertFalse(s.Ring.allowed())

    def test_lock_clears_handset_and_ring_without_a_telephony_event(self):
        s = self.s
        self.flux()
        s.Call.sync()
        self.assertTrue(s.Call.visible())
        self.assertTrue(s.phone_on_screen())
        s.CFG["proactive"] = False                      # (sense reads no lock state then: the handset still clears)
        with mock.patch.object(s.Desk, "locked", lambda: True), mock.patch.object(s.Ambient, "locked", False):
            s.Ambient.sense()
        self.assertFalse(s.Call.visible())
        self.ring.assert_called_with("gone")
        self.pub.assert_called_with(t="call", phase="gone")

    def test_phone_off_stops_hfp_and_clears(self):
        s = self.s
        self.flux()
        s.Call.sync()
        self.phone.devices.return_value = []
        self.phone.outgoing = set()
        s.phone_reset()
        self.hfp.stop.assert_called_once()
        self.assertFalse(s.Call.visible())

    def test_hfp_only_call_quiets_him(self):
        s = self.s
        self.phone.call_active = False
        self.hfp.any_call = lambda: True               # (mock reserves the name any_call)
        with mock.patch.object(s.Ambient, "phone_call", False), mock.patch.object(s.Speaker, "stop") as stop, \
                mock.patch.object(s.Wake, "end_follow"):
            s.phone_call_sync()
            self.assertTrue(s.Ambient.phone_call)
            stop.assert_called_once()

    def test_answered_edge_stops_speech(self):
        s = self.s
        with mock.patch.object(s.Speaker, "stop") as stop, mock.patch.object(s.Wake, "end_follow") as follow:
            s.call_answered()
        stop.assert_called_once()
        follow.assert_called_once_with("cancel")

    def test_hfp_only_miss_makes_one_card_flux_miss_none(self):
        s = self.s
        with mock.patch.object(s, "phone_tick"):
            s.PHONE_MISSED.clear()
            s.call_missed("c1", None, "5551234", None)
            self.assertIn(("hfp", "c1"), s.PHONE_MISSED)
            self.assertIsNone(s.PHONE_MISSED[("hfp", "c1")]["number"])
            s.call_missed("c2", "Ada", None, "pixel")
            self.assertNotIn(("hfp", "c2"), s.PHONE_MISSED)
            s.PHONE_MISSED.clear()


class ReviewFixes(Calls):
    """Codex review on #116: lost Flux with live HFP, held/outgoing calls, a waiting Flux call, failed actions."""

    def test_flux_lost_keeps_a_live_hfp_call(self):
        s = self.s
        self.flux(state="talking")
        self.host(state="active")
        s.Call.sync()
        self.assertEqual(s.Call.row["phase"], "active")
        self.phone.devices.return_value = [{"id": "pixel", "name": "Pixel", "can": {"answer"},
                                            "lastCall": {"id": "flux-1", "end": "lost", "at": 1}}]
        s.Call.sync()
        self.assertTrue(s.Call.visible())
        self.hfp.calls = {}
        s.Call.sync()
        self.assertFalse(s.Call.visible())

    def test_held_and_outgoing_never_ring(self):
        s = self.s
        for state in ("held", "dialing", "alerting", "active"):
            s.Call.clear()
            self.ring.reset_mock()
            self.host(state=state)
            s.Call.sync()
            self.assertEqual(s.Call.row["phase"], "active", state)
            self.assertNotIn(mock.call("ringing"), self.ring.call_args_list, state)
        s.Call.clear()
        self.host(state="incoming")
        s.Call.sync()
        self.assertEqual(s.Call.row["phase"], "ringing")

    def test_waiting_flux_call_keeps_the_first_and_says_second(self):
        s = self.s
        self.flux(state="talking")
        s.Call.sync()
        first = s.Call.row["id"]
        self.phone.devices.return_value = [{"id": "pixel", "name": "Pixel", "can": {"answer"},
                                            "call": {"id": "flux-2", "state": "ringing", "number": "999",
                                                     "caller": "Bob", "handsFree": [], "waiting": True, "since": 2}}]
        s.Call.sync()
        self.assertTrue(s.Call.visible())
        self.assertEqual(s.Call.row["id"], first)
        self.assertEqual(s.Call.row["phase"], "active")
        self.assertEqual(s.Call.row["keys"], [])
        self.assertEqual(s.Call.row["note"], s.lang.t("call.second"))

    def test_a_failed_action_says_so_at_once(self):
        s = self.s
        self.host(state="incoming")
        s.Call.sync()
        row = s.Call.row
        self.hfp.answer.return_value = {"ok": False, "error": "Failed"}
        self.assertEqual(s.Call.act(row["id"], row["gen"], "answer"), {"ok": False})
        self.assertEqual(s.Call.row["note"], s.lang.t("call.failed"))
        self.assertIsNone(s.Call.watchdog)
        self.hfp.answer.side_effect = OSError
        ident, gen = s.Call.row["id"], s.Call.row["gen"]
        self.assertEqual(s.Call.act(ident, gen, "answer"), {"ok": False})
        self.assertEqual(s.Call.row["gen"], gen + 1)


if __name__ == "__main__":
    unittest.main()
