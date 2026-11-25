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
        self.hfp.gateways = {}
        self.pbap = mock.Mock()                          # (never the real obexd)
        self.pbap.name_for.return_value = None
        self.pbap.state.return_value = "ready"
        self.hfp.audio_here.return_value = False
        self.hfp.calls_on.side_effect = lambda ag: [c for c in self.hfp.calls.values() if c["ag"] == ag and c["state"] != "disconnected"]
        self.pub = mock.Mock()
        self.ring = mock.Mock()
        for obj, name, value in ((s, "Phone", self.phone), (s, "Hfp", self.hfp), (s.BUS, "pub", self.pub),
                                 (s, "Pbap", self.pbap), (s, "HFP_SEEN", {}),
                                 (s.Desk, "locked", lambda: False), (s.peers, "current", lambda: []),
                                 (s.Ring, "follow", self.ring),   # (never a real ring from a test)
                                 (s.Ambient, "phone_call", False)):   # (phone_tick sets it from the mock phone; a truthy leftover silenced later suites)
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
        self.pbap.drop.assert_called_once_with()
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
        for state, phase in (("held", "active"), ("dialing", "dialing"), ("alerting", "dialing"), ("active", "active")):
            s.Call.clear()
            self.ring.reset_mock()
            self.host(state=state)
            s.Call.sync()
            self.assertEqual(s.Call.row["phase"], phase, state)
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


class AgyFixes(Calls):
    """agy review on #116."""

    def test_one_missed_card_when_hfp_reports_first(self):
        s = self.s
        with mock.patch.object(s, "phone_tick"):
            s.PHONE_MISSED.clear()
            s.call_missed("c1", "Ada", None, None)
            self.assertIn(("hfp", "c1"), s.PHONE_MISSED)
            self.phone.devices.return_value = [{"id": "pixel", "name": "Pixel", "can": set()}]
            s.phone_on_missed(("missed", "pixel", 5), {"caller": "Ada"})
            self.assertEqual([k[0] for k in s.PHONE_MISSED], ["missed"])
            s.PHONE_MISSED.clear()

    def test_failure_note_survives_an_unrelated_sync(self):
        s = self.s
        self.host(state="incoming")
        s.Call.sync()
        self.hfp.answer.return_value = {"ok": False, "error": "Failed"}
        s.Call.act(s.Call.row["id"], s.Call.row["gen"], "answer")
        s.Call.sync()
        self.assertEqual(s.Call.row["note"], s.lang.t("call.failed"))
        self.assertEqual(s.Call.row["keys"], ["answer", "reject"])   # (it can be tried again)

    def test_watchdog_starts_only_after_a_sent_action(self):
        s = self.s
        self.host(state="incoming")
        s.Call.sync()
        seen = []
        self.hfp.answer.side_effect = lambda path: (seen.append(s.Call.watchdog), {"ok": True})[1]
        s.Call.act(s.Call.row["id"], s.Call.row["gen"], "answer")
        self.assertEqual(seen, [None])
        self.assertIsNotNone(s.Call.watchdog)
        s.Call.clear()

    def test_a_new_call_does_not_inherit_the_old_ones_fields(self):
        s = self.s
        self.host(state="active")
        self.hfp.audio_here.return_value = True
        s.Call.sync()
        s.Call.row["muted"] = True
        self.hfp.calls = {"/ag1/call9": {"path": "/ag1/call9", "ag": "/ag1", "state": "incoming",
                                           "number": "777", "name": None}}
        s.Call.clear()
        s.Call.sync()
        self.assertFalse(s.Call.row["muted"])

    def test_lastcall_without_id_never_matches_an_hfp_only_call(self):
        s = self.s
        self.host(state="active")
        s.Call.sync()
        self.phone.devices.return_value = [{"id": "pixel", "name": "Pixel", "can": set(),
                                            "lastCall": {"end": "lost", "at": 1}}]
        s.Call.sync()
        self.assertTrue(s.Call.visible())


class GithubCodexFixes(Calls):
    """Codex on GitHub, #116: unlock brings the handset back, Meeting Mode silences the ring, proactive off."""

    def test_unlock_brings_back_a_ringing_call_with_proactive_off(self):
        s = self.s
        s.CFG["proactive"] = False
        self.flux()
        self.phone.call_active = True
        self.hfp.any_call = lambda: False
        with mock.patch.object(s.Desk, "locked", lambda: True), mock.patch.object(s.Ambient, "locked", False):
            s.Ambient.sense()
        self.assertFalse(s.Call.visible())
        with mock.patch.object(s.Ambient, "locked", False):
            s.Ambient.sense()                              # (Desk.locked() is False again)
        self.assertTrue(s.Call.visible())

    def test_meeting_mode_silences_the_ring_even_with_proactive_off(self):
        s = self.s
        with mock.patch.object(s, "audio_player_cmd", return_value=["paplay"]), \
                mock.patch.object(s.Wake, "asleep", False), mock.patch.object(s.Ambient, "meeting", False), \
                mock.patch.object(s.Ambient, "dnd", False):
            with mock.patch.object(s, "phone_meeting_now", return_value=False):
                self.assertTrue(s.Ring.allowed())
            with mock.patch.object(s, "phone_meeting_now", return_value=True):
                self.assertFalse(s.Ring.allowed())


class Outgoing(Calls):
    """Calls we place (#121): the dialing phase, its keys and its end."""

    def test_dialing_to_active_to_ended(self):
        s = self.s
        missed = s.Call.on_missed = mock.Mock()
        for state in ("dialing", "alerting"):
            self.host(state=state)
            s.Call.sync()
            row = s.Call.row
            self.assertEqual((row["phase"], row["path"], row["keys"], row["answered_at"]),
                             ("dialing", "host", ["hangup"], None), state)
            self.assertTrue(row["hfp_outgoing"])
            self.assertFalse(row["hfp_incoming"])
        self.ring.assert_called_with("dialing")
        self.hfp.audio_here.return_value = True
        self.host(state="active")
        s.Call.sync()
        self.assertEqual(s.Call.row["phase"], "active")
        self.assertEqual(s.Call.row["keys"], ["hangup", "mute", "vol_up", "vol_down"])
        self.assertIsNotNone(s.Call.row["answered_at"])
        self.assertTrue(s.Call.row["hfp_outgoing"])
        self.host(state="disconnected")
        s.Call.sync()
        self.assertEqual((s.Call.row["phase"], s.Call.row["note"]), ("ended", "Call ended"))
        missed.assert_not_called()

    def test_cancel_before_answer(self):
        s = self.s
        missed = s.Call.on_missed = mock.Mock()
        self.host(state="alerting")
        s.Call.sync()
        self.host(state="disconnected")
        s.Call.sync()
        self.assertEqual((s.Call.row["phase"], s.Call.row["note"], s.Call.row["keys"]), ("ended", "Call ended", []))
        self.assertEqual(s.Call.end_timer.interval, 2)
        missed.assert_not_called()

    def test_second_call_while_dialing_has_no_keys(self):
        self.host(state="dialing")
        self.hfp.calls["/ag1/call2"] = {"path": "/ag1/call2", "ag": "/ag1", "state": "waiting",
                                        "number": "5551234", "name": None}
        self.s.Call.sync()
        self.assertEqual((self.s.Call.row["phase"], self.s.Call.row["keys"]), ("dialing", []))

    def test_flux_only_talking_and_incoming_with_flux_are_unchanged(self):
        s = self.s
        self.flux(state="talking")
        s.Call.sync()
        self.assertEqual((s.Call.row["phase"], s.Call.row["path"], s.Call.row["keys"]), ("active", "phone", []))
        s.Call.clear()
        self.flux()
        self.host()
        s.Call.sync()
        self.assertEqual((s.Call.row["phase"], s.Call.row["path"], s.Call.row["keys"], s.Call.row["who"]),
                         ("ringing", "host", ["answer", "reject"], "Ada"))
        self.assertFalse(s.Call.row["hfp_outgoing"])


class Names(Calls):
    """Contact names on the handset (#121): shown, never spoken."""

    def setUp(self):
        super().setUp()
        self.hfp.gateways = {"/ag1": {"path": "/ag1", "address": "AA:BB"}}

    def test_warm_cache_names_a_number_only_call(self):
        s = self.s
        self.pbap.name_for.return_value = ("Anna Test", "mobile")
        for sent in (None, "+47 (912) 34\u2013567.8"):
            s.Call.clear()
            self.host(name=sent)
            s.Call.sync()
            self.assertEqual((s.Call.row["who"], s.Call.row["label"], s.Call.row["number"], s.Call.row["phone_who"]),
                             ("Anna Test", "mobile", None, sent))
        self.pbap.name_for.assert_called_with("AA:BB", "12345678")
        self.pbap.ensure.assert_not_called()
        self.assertEqual(s.Call.current_event()["label"], "mobile")
        self.assertEqual(self.pub.call_args.kwargs["label"], "mobile")
        self.assertNotIn("phone_who", s.Call.current_event())
        self.assertNotIn("phone_who", self.pub.call_args.kwargs)

    def test_cold_cache_shows_the_number_then_the_name_after_one_load(self):
        s = self.s
        self.pbap.state.return_value = "cold"
        self.host()
        s.Call.sync()
        self.assertEqual((s.Call.row["who"], s.Call.row["number"]), (None, "12345678"))
        self.pbap.ensure.assert_called_once()
        address, cb = self.pbap.ensure.call_args.args
        self.assertEqual(address, "AA:BB")
        self.pbap.state.return_value = "ready"
        self.pbap.name_for.return_value = ("Anna Test", "home")
        cb("ready")
        self.assertEqual((s.Call.row["who"], s.Call.row["label"]), ("Anna Test", "home"))
        self.pbap.ensure.assert_called_once()

    def test_sharing_off_does_not_loop(self):
        s = self.s
        self.pbap.state.return_value = "cold"
        self.host()
        s.Call.sync()
        cb = self.pbap.ensure.call_args.args[1]
        self.pbap.state.return_value = "sharing"
        with mock.patch.object(s.Call, "sync") as sync:
            cb("sharing")
        sync.assert_not_called()
        s.Call.sync()
        self.pbap.ensure.assert_called_once()
        self.assertEqual(s.Call.row["number"], "12345678")

    def test_withheld_hfp_number_ignores_the_flux_number(self):
        s = self.s
        self.pbap.name_for.return_value = ("Anna Test", "mobile")
        self.flux(caller="Unknown caller")
        self.host(number=None)
        s.Call.sync()
        self.assertEqual((s.Call.row["who"], s.Call.row["label"]), (None, None))
        self.pbap.name_for.assert_not_called()

    def test_a_real_phone_name_is_kept_and_missed_gets_only_it(self):
        s = self.s
        missed = s.Call.on_missed = mock.Mock()
        self.pbap.name_for.return_value = ("Anna Test", "work")
        for sent in ("Phone Ada", None):
            s.Call.clear()
            s.Call.missed.clear()
            missed.reset_mock()
            self.host(name=sent)
            s.Call.sync()
            self.assertEqual((s.Call.row["who"], s.Call.row["label"]), (sent or "Anna Test", "work"))
            self.host(state="disconnected", name=sent)
            s.Call.sync()
            self.assertEqual(missed.call_args.args[1], sent)

    def test_a_gateway_gone_mid_call_means_no_lookup(self):
        self.hfp.gateways = {}
        self.host()
        self.s.Call.sync()
        self.assertEqual(self.s.Call.row["number"], "12345678")
        self.pbap.name_for.assert_not_called()
        self.pbap.ensure.assert_not_called()

    def test_gateway_loss_and_lock_drop_the_phonebook(self):
        s = self.s
        self.phone.call_active = False
        self.hfp.any_call = lambda: False
        with mock.patch.object(s, "phone_call_gateway_lost") as lost:
            s.hfp_changed()
            self.pbap.drop.assert_not_called()
            self.hfp.gateways = {}
            s.hfp_changed()
        self.pbap.drop.assert_called_once_with("AA:BB")
        lost.assert_called_once_with("/ag1")
        self.pbap.drop.reset_mock()
        with mock.patch.object(s.Desk, "locked", lambda: True), mock.patch.object(s.Ambient, "locked", False), \
                mock.patch.dict(s.CFG, {"proactive": True}):
            s.Ambient.sense()
        self.pbap.drop.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
