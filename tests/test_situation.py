import datetime
import json
import os
import queue
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_speakable import _ServerEnv


class SituationTest(_ServerEnv):
    """#133: Meeting Mode's flag and a calendar item a minute away put him in a meeting; a meeting pauses the wake word."""

    def setUp(self):
        S = self.server
        saved = dict(S.CFG)
        self.addCleanup(lambda: (S.CFG.clear(), S.CFG.update(saved)))
        S.CFG.update(proactive=True, ambient_calendar=False, look_music=False)
        env = mock.patch.dict(os.environ, {"XDG_STATE_HOME": os.path.join(self.tmp, "sit-state")})
        env.start()
        self.addCleanup(env.stop)
        ev = mock.patch.object(S.Ambient, "events", [])
        ev.start()
        self.addCleanup(ev.stop)
        lk = mock.patch.object(S.Desk, "locked", return_value=False)
        self.lock = lk.start()
        self.addCleanup(lk.stop)
        S.Ambient.meeting = S.Ambient.music = False
        self.addCleanup(lambda: setattr(S.Ambient, "meeting", False))
        self.addCleanup(lambda: S.Ambient.__dict__ and [setattr(S.Ambient, k, False) for k in ("cpu_hot", "ram_low", "fullscreen", "locked")])
        S.Ambient.hot_since, S.Ambient.lock_since = None, 0.0
        S.Desk.fullscreen = False
        self.addCleanup(setattr, S.Desk, "fullscreen", False)
        S.Ambient.sky, S.Ambient.birthdays = None, set()
        for k in ("look_weather", "look_night", "look_party", "look_coding", "ambient_weather"):
            S.CFG[k] = False

    def flag(self, on):
        f = Path(os.environ["XDG_STATE_HOME"]) / "meeting-mode" / "active"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.unlink(missing_ok=True)
        if on:
            f.touch()

    def test_flag_file_means_meeting(self):
        A = self.server.Ambient
        self.flag(False)
        A.sense()
        self.assertFalse(A.meeting)
        self.flag(True)
        A.sense()
        self.assertTrue(A.meeting)
        self.flag(False)
        A.sense()
        self.assertFalse(A.meeting)

    def test_no_meeting_unless_opted_in(self):
        A = self.server.Ambient
        self.server.CFG["proactive"] = False
        self.flag(True)
        A.sense()
        self.assertFalse(A.meeting)

    def test_calendar_item_a_minute_away(self):
        S = self.server
        now = datetime.datetime.now().astimezone()
        self.flag(False)
        with mock.patch.object(S.Ambient, "events", [(now + datetime.timedelta(seconds=45), "standup", "e1")]):
            S.Ambient.sense(now)
            self.assertFalse(S.Ambient.meeting)           # calendar cues are off
            S.CFG["ambient_calendar"] = True
            S.Ambient.sense(now)
            self.assertTrue(S.Ambient.meeting)
        with mock.patch.object(S.Ambient, "events", [(now + datetime.timedelta(minutes=5), "later", "e2")]):
            S.Ambient.sense(now)
            self.assertFalse(S.Ambient.meeting)

    def test_wake_word_pauses_in_a_meeting(self):
        S = self.server
        S.CFG["wake_word"] = True
        with mock.patch.object(S.Wake, "asleep", False), mock.patch.object(S.Wake, "speaking", return_value=False):
            S.Ambient.meeting = False
            self.assertTrue(S.Wake.should_run())
            S.Ambient.meeting = True
            self.assertFalse(S.Wake.should_run())

    def proc(self, load, avail, total=1000):
        d = Path(tempfile.mkdtemp(dir=self.tmp))
        (d / "loadavg").write_text(f"{load} 1.0 1.0 1/100 123\n")
        (d / "meminfo").write_text(f"MemTotal:       {total} kB\nMemFree: 1 kB\nMemAvailable:   {avail} kB\n")
        return str(d)

    def test_cpu_needs_30s_and_clears_at_70_percent(self):
        S = self.server
        S.CFG["react_load"] = True
        cores = os.cpu_count() or 1
        A = S.Ambient
        hot, mid, cool = self.proc(cores + 1, 900), self.proc(cores * .8, 900), self.proc(cores * .5, 900)
        A.sense(proc=hot, mono=100)
        A.sense(proc=hot, mono=125)
        self.assertFalse(A.cpu_hot)
        A.sense(proc=hot, mono=131)
        self.assertTrue(A.cpu_hot)
        A.sense(proc=mid, mono=140)                       # between 0.7 and 1.0 x cores: stays hot
        self.assertTrue(A.cpu_hot)
        A.sense(proc=cool, mono=150)
        self.assertFalse(A.cpu_hot)
        A.sense(proc=hot, mono=160)                       # a dip restarts the 30 s
        A.sense(proc=hot, mono=185)
        self.assertFalse(A.cpu_hot)

    def test_ram_hysteresis(self):
        S = self.server
        S.CFG["react_load"] = True
        A = S.Ambient
        A.sense(proc=self.proc(1, 90))
        self.assertTrue(A.ram_low)
        A.sense(proc=self.proc(1, 200))                   # 20%: still low (re-arms above 25%)
        self.assertTrue(A.ram_low)
        A.sense(proc=self.proc(1, 300))
        self.assertFalse(A.ram_low)

    def test_load_and_ram_need_both_switches(self):
        A = self.server.Ambient
        cores = os.cpu_count() or 1
        for cfg in ({"react_load": False}, {"react_load": True, "proactive": False}):
            self.server.CFG.update(cfg)
            A.sense(proc=self.proc(cores + 5, 10), mono=1)
            A.sense(proc=self.proc(cores + 5, 10), mono=100)
            self.assertFalse(A.cpu_hot or A.ram_low, cfg)

    def test_lock_edges_and_publishing(self):
        S = self.server
        A = S.Ambient
        q = S.BUS.sub()
        self.addCleanup(S.BUS.unsub, q)
        self.lock.return_value = True
        A.sense(mono=1000)
        self.assertEqual((A.locked, A.lock_since), (True, 1000))
        self.assertEqual(q.get_nowait()["locked"], True)
        A.sense(mono=1100)                                # no change, nothing published
        self.assertTrue(q.empty())
        self.lock.return_value = False
        A.sense(mono=1400)
        self.assertEqual((A.locked, A.lock_since, A.unlocked_at, A.last_lock_len), (False, 0.0, 1400, 400))
        self.assertEqual(q.get_nowait()["locked"], False)

    def at(self, y, mo, d, h=12, mi=0):
        return datetime.datetime(y, mo, d, h, mi).astimezone()

    def test_sky_glyphs(self):
        A = self.server.Ambient
        self.assertEqual(A.sky_of("\ue318\n"), "rain")
        self.assertEqual(A.sky_of("\ue3ad"), "rain")
        self.assertEqual(A.sky_of("\ue327 "), "snow")
        self.assertIsNone(A.sky_of("\ue30d"))             # sun
        self.assertIsNone(A.sky_of(""))
        self.assertIsNone(A.sky_of(None))                  # offline: exit 1

    def test_the_look_keys_gate_weather_night_party(self):
        S = self.server
        A = S.Ambient
        night = self.at(2026, 10, 30, 23, 30)
        A.sky = "snow"
        A.sense(night)
        self.assertEqual((A.weather, A.night, A.party), (None, False, False))     # all off by default
        S.CFG.update(look_weather=True, look_night=True, look_party=True, ambient_weather=True)
        A.sense(self.at(2026, 12, 25, 23, 30))
        self.assertEqual((A.weather, A.night, A.party), ("snow", True, True))
        S.CFG["ambient_weather"] = False                   # the weather look needs the weather source
        A.sense(night)
        self.assertIsNone(A.weather)
        S.CFG["proactive"] = False
        A.sense(night)
        self.assertEqual((A.weather, A.night, A.party), (None, False, False))
        A.sky = None

    def test_night_window_edges(self):
        S = self.server
        S.CFG.update(look_night=True)
        A = S.Ambient
        for (h, mi), want in {(22, 59): False, (23, 0): True, (4, 59): True, (5, 0): False}.items():
            A.sense(self.at(2026, 10, 30, h, mi))
            self.assertEqual(A.night, want, (h, mi))

    def test_party_dates(self):
        S = self.server
        S.CFG.update(look_party=True)
        A = S.Ambient
        for (mo, d), want in {(1, 1): True, (12, 24): True, (12, 25): True, (12, 31): True, (12, 26): False, (6, 15): False}.items():
            A.sense(self.at(2026, mo, d))
            self.assertEqual(A.party, want, (mo, d))

    def test_a_birthday_in_the_calendar_keeps_no_title(self):
        S = self.server
        A = S.Ambient
        S.CFG.update(look_party=True)
        conf = S.NIXI_CONF.parent / "calendars.json"
        conf.parent.mkdir(parents=True, exist_ok=True)
        conf.write_text(json.dumps([{"enabled": True, "googleCalendarId": "cal"}]))
        self.addCleanup(conf.unlink)
        out = json.dumps({"events": [
            {"id": "a", "summary": "Anna's birthday", "start": {"date": "2026-10-30"}},            # all-day
            {"id": "b", "summary": "Standup", "start": {"dateTime": "2026-10-30T09:00:00+00:00"}},
            {"id": "c", "summary": "Pappas BURSDAG", "start": {"dateTime": "2026-10-31T18:00:00+00:00"}}]})
        with mock.patch.object(S.Ambient, "run", return_value=out):
            A.fetch("cal")
        self.addCleanup(setattr, A, "birthdays", set())
        self.assertEqual(A.birthdays, {"2026-10-30", "2026-10-31"})
        self.assertNotIn("Anna", repr(vars(A)))
        self.assertNotIn("Anna", repr(A.events))
        self.assertEqual([e[1] for e in A.events], ["Standup", "Pappas BURSDAG"])      # (timed items keep their cue, as before)
        A.sense(self.at(2026, 10, 30))
        self.assertTrue(A.party)
        A.sense(self.at(2026, 10, 29))
        self.assertFalse(A.party)

    def test_a_failed_lock_query_is_not_an_unlock(self):
        A = self.server.Ambient
        self.lock.return_value = True
        A.sense(mono=1000)
        self.lock.return_value = None
        A.sense(mono=1100)
        self.assertEqual((A.locked, A.lock_since, A.unlocked_at), (True, 1000, 0.0))

    def test_fullscreen_stops_the_lease(self):
        S = self.server
        with mock.patch.object(S.BUS, "subs", [queue.Queue()]), mock.patch.object(S.Wake, "asleep", False):
            S.CFG.update(notifications_takeover=True)
            self.assertTrue(S.Inbox.want())
            S.Desk.fullscreen = True
            self.assertFalse(S.Inbox.want())
            S.Ambient.sense()
            self.assertTrue(S.Ambient.fullscreen)
            S.CFG["proactive"] = False
            S.Ambient.sense()
            self.assertFalse(S.Ambient.fullscreen)


if __name__ == "__main__":
    unittest.main()
