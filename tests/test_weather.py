import datetime
import json
import os
import time
import unittest
from unittest import mock

from test_speakable import _ServerEnv

PLACE = {"latitude": 51.5, "longitude": -0.1}


class _Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self.body


class WeatherTest(_ServerEnv):
    """#157: Open-Meteo forecast -> sky kinds, day, cold/windy/lean margins, one precedence rule, pokes. Never the network."""

    def setUp(self):
        S = self.server
        A = self.A = S.Ambient
        saved, saved_attrs = dict(S.CFG), {k: getattr(A, k) for k in ("wx", "omx", "sky", "day", "cold", "windy", "lean", "heavy", "storm", "hot", "wkey", "wsrc", "feel", "wspeed", "weather", "urlopen", "due", "run")}
        def restore():
            S.CFG.clear()
            S.CFG.update(saved)
            for k, v in saved_attrs.items():
                setattr(A, k, v)
        self.addCleanup(restore)
        S.CFG.update(proactive=True, ambient_weather=True, look_weather=True, ambient_calendar=False, look_music=False)
        env = mock.patch.dict(os.environ, {"XDG_STATE_HOME": os.path.join(self.tmp, "wx-state")})
        env.start()
        self.addCleanup(env.stop)
        for p in (mock.patch.object(A, "events", []), mock.patch.object(A, "machine"),
                  mock.patch.object(S.Desk, "locked", return_value=False),
                  mock.patch.object(S, "location", side_effect=lambda: self.places)):
            p.start()
            self.addCleanup(p.stop)
        self.places = {"now": dict(PLACE), "home": None, "work": None}
        A.wx = A.omx = None
        A.storm = A.hot = False
        A.sky = None
        A.wkey = None
        A.due = {k: 0.0 for k in A.due}
        self.calls = []
        self.body = {"current": {}}
        def fake(url, timeout=None):
            self.calls.append(url)
            if isinstance(self.body, Exception):
                raise self.body
            return _Resp(json.dumps(self.body).encode())
        A.urlopen = fake
        self.omarchy = {"status": "5°C Wind 10 km/h", "icon": chr(0xE318)}
        A.run = staticmethod(lambda argv, timeout=3: self.omarchy.get(argv[-1]) if argv[0] == "omarchy" else None)

    def current(self, **kw):
        self.body = {"current": {"weather_code": 0, "apparent_temperature": 10, "temperature_2m": 10, "wind_speed_10m": 5,
                                 "wind_direction_10m": 0, "is_day": 1, **kw}}
        return self.A.forecast(self.A.place_key())

    def hold(self, **kw):
        """Install a good reading as the forecast for the current place."""
        d = {"sky": "clear", "heavy": False, "feel": 10, "temp": 10, "wind": 5, "dir": 0, "day": 1}
        d.update(kw)
        self.A.wx = {"key": self.A.place_key(), "at": self.server.time.monotonic(), **d}

    def tick(self, hour=12):
        self.A.sense(now=datetime.datetime(2026, 6, 1, hour, 0).astimezone())

    # ---- mapping and validation
    def test_code_to_sky(self):
        for code, sky, heavy in ((0, "clear", False), (1, "partly", False), (2, "partly", False), (3, "cloudy", False),
                                 (45, "cloudy", False), (48, "cloudy", False), (61, "rain", False), (65, "rain", True),
                                 (73, "snow", False), (95, "rain", False)):
            r = self.current(weather_code=code)
            self.assertEqual((r["sky"], r["heavy"]), (sky, heavy), code)
        self.assertIsNone(self.current(weather_code=None)["sky"])
        self.assertIsNone(self.current(weather_code="3")["sky"])

    def test_storm_codes_keep_rain_sky(self):
        for code in (95, 96, 99):
            reading = self.current(weather_code=code)
            self.assertEqual((reading["sky"], reading["storm"]), ("rain", True), code)
        self.assertFalse(self.current(weather_code=61)["storm"])

    def test_storm_requires_open_meteo_and_the_weather_gate(self):
        self.hold(sky="rain", storm=True)
        self.tick()
        self.assertTrue(self.A.storm)
        self.assertTrue(self.A.situation()["storm"])
        self.server.CFG["look_weather"] = False
        self.tick()
        self.assertFalse(self.A.storm)
        self.server.CFG["look_weather"] = True
        self.A.wx = None
        self.A.omx = {"sky": "rain", "temp": 29, "wind": 5, "at": time.monotonic()}
        self.tick()
        self.assertEqual(self.A.wsrc, "omarchy")
        self.assertFalse(self.A.storm)
        self.hold(sky="rain")  # older hand-built forecast dictionaries omit storm
        self.tick()
        self.assertFalse(self.A.storm)

    def test_hot_hysteresis_and_boundaries(self):
        for feel, want in ((27.9, False), (28, True), (26.5, True), (25.9, False), (26.5, False)):
            self.hold(feel=feel)
            self.tick()
            self.assertIs(self.A.hot, want, feel)
        self.hold(feel=29, day=0)
        self.tick()
        self.assertFalse(self.A.hot)
        self.hold(feel=29, sky="cloudy")
        self.tick()
        self.assertFalse(self.A.hot)
        self.hold(feel=None)
        self.tick()
        self.assertFalse(self.A.hot)
        self.hold(feel=29, sky="partly")
        self.tick()
        self.assertTrue(self.A.hot)
        self.server.CFG["look_weather"] = False
        self.tick()
        self.assertFalse(self.A.hot)
        self.server.CFG["look_weather"] = True
        self.A.wx = None
        self.A.omx = {"sky": "clear", "temp": 29, "wind": 5, "at": time.monotonic()}
        self.tick()
        self.assertEqual(self.A.wsrc, "omarchy")
        self.assertFalse(self.A.hot)
        self.assertFalse(self.A.situation()["hot"])

    def test_out_of_range_values_are_none(self):
        self.assertIsNone(self.current(apparent_temperature=999)["feel"])
        self.assertIsNone(self.current(wind_speed_10m=-1)["wind"])
        self.assertIsNone(self.current(wind_direction_10m=400)["dir"])
        r = self.current(apparent_temperature="9", wind_speed_10m="9", wind_direction_10m="9")
        self.assertEqual((r["feel"], r["wind"], r["dir"]), (None, None, None))
        self.assertIsNone(self.current(is_day=2)["day"])
        self.assertIsNone(self.current(is_day=True)["day"])
        self.assertEqual((self.current(is_day=0)["day"], self.current(is_day=1)["day"]), (0, 1))

    def test_a_bad_answer_is_none(self):
        self.body = OSError("down")
        self.assertIsNone(self.A.forecast(self.A.place_key()))
        self.body = {"current": 3}
        self.assertIsNone(self.A.forecast(self.A.place_key()))
        self.body = {}
        self.assertIsNone(self.A.forecast(self.A.place_key()))

    def test_omarchy_reading_expires(self):
        A = self.A
        A.omx = {"sky": "rain", "temp": 3.0, "wind": 12.0, "at": time.monotonic() - 7201}   # (Codex, agy, Opus: it never expired)
        self.assertIsNone(A.reading()[0])
        A.run = staticmethod(lambda *a, **k: None)                                            # offline: omarchy answers nothing
        A.fetch("weather")
        self.assertIsNone(A.omx)

    # ---- margins
    def test_cold_margins(self):
        A = self.A
        seq = [(6, 0), (5, 1), (6, 1), (7.5, 0), (-5, 2), (-4, 2), (-2.9, 1), (8, 0)]   # (0 → 2 in one step, plan step 5)
        for feel, want in seq:
            self.hold(feel=feel)
            self.tick()
            self.assertEqual(A.cold, want, feel)
        self.hold(feel=-5)
        self.tick()
        self.assertEqual(A.cold, 2)
        self.hold(feel=8)
        self.tick()
        self.assertEqual(A.cold, 0)

    def test_windy_margins(self):
        A = self.A
        for wind, want in ((26, True), (22, True), (19, False), (22, False), (None, False)):
            self.hold(wind=wind)
            self.tick()
            self.assertIs(A.windy, want, wind)

    def test_lean_follows_the_wind_direction(self):
        for d, want in ((90, 1), (270, -1), (0, 0), (None, 0)):
            self.hold(dir=d)
            self.tick()
            self.assertEqual(self.A.lean, want, d)

    def test_heavy_follows_the_reading(self):
        self.hold(sky="rain", heavy=True)
        self.tick()
        self.assertTrue(self.A.heavy)
        self.assertEqual(self.A.weather, "rain")

    # ---- gates
    def test_no_coordinates_no_call(self):
        self.places = {"now": None, "home": None, "work": None}
        self.A.fetch("weather")
        self.assertEqual(self.calls, [])
        self.assertIsNone(self.A.wx)
        self.tick()
        self.assertEqual((self.A.wsrc, self.A.weather), ("omarchy", "rain"))
        self.assertEqual(self.A.feel, 5.0)

    def test_gates_off_no_call(self):
        S = self.server
        for k in ("look_weather", "ambient_weather", "proactive"):
            S.CFG[k] = False
            self.A.fetch("weather")
            self.assertEqual(self.calls, [], k)
            S.CFG[k] = True

    def test_fetch_stores_the_forecast_when_on(self):
        self.current(weather_code=71)
        self.calls.clear()
        self.A.fetch("weather")
        self.assertEqual(len(self.calls), 1)
        self.assertIn("latitude=51.5", self.calls[0])
        self.assertEqual(self.A.wx["sky"], "snow")

    def test_look_weather_off_leaves_weather_none(self):
        self.server.CFG["look_weather"] = False
        self.hold(sky="rain", feel=-9, wind=30)
        self.tick()
        self.assertEqual((self.A.weather, self.A.cold, self.A.windy, self.A.lean, self.A.heavy), (None, 0, False, 0, False))

    # ---- precedence
    def test_a_failure_keeps_the_good_reading(self):
        self.current(weather_code=61)
        self.A.fetch("weather")
        self.assertEqual(self.A.wx["sky"], "rain")
        self.body = OSError("down")
        self.A.fetch("weather")
        self.assertEqual(self.A.wx["sky"], "rain")
        self.tick()
        self.assertEqual(self.A.wsrc, "open-meteo")

    def test_an_old_reading_falls_back_to_omarchy(self):
        self.hold(sky="snow", feel=-9)
        self.A.wx["at"] -= 7201
        self.A.omx = {"sky": "rain", "temp": 3.0, "wind": 12.0, "at": time.monotonic()}
        self.tick()
        self.assertEqual((self.A.wsrc, self.A.weather, self.A.feel, self.A.wspeed), ("omarchy", "rain", 3.0, 12.0))

    def test_another_place_falls_back_and_resets_margins(self):
        A = self.A
        self.hold(feel=-9)
        self.tick()
        self.tick()
        self.assertEqual(A.cold, 2)
        A.omx = {"sky": None, "temp": 0.0, "wind": 1.0, "at": time.monotonic()}
        self.places = {"now": {"latitude": 40.0, "longitude": 10.0}, "home": None, "work": None}
        self.tick()
        self.assertEqual(A.wsrc, "omarchy")
        self.assertEqual((A.cold, A.windy, A.lean, A.heavy), (1, False, 0, False))   # reset, then omarchy's 0 °C

    def test_the_key_is_rounded_and_prefers_now_over_home(self):
        self.places = {"now": None, "home": {"latitude": 1.234, "longitude": 5.678}, "work": None}
        self.assertEqual(self.A.place_key(), (1.23, 5.68))
        self.places["now"] = {"latitude": True, "longitude": 1}
        self.assertEqual(self.A.place_key(), (1.23, 5.68))
        self.places = {"now": None, "home": None, "work": None}
        self.assertIsNone(self.A.place_key())

    # ---- pokes
    def test_location_act_pokes(self):
        self.A.due = {k: 99.0 for k in self.A.due}
        run = mock.Mock(return_value=mock.Mock(returncode=0, stdout="", stderr=""))
        with mock.patch.object(self.server, "location_api", return_value={}):
            self.server.location_act({"act": "now", "value": "home"}, run)
        self.assertEqual(set(self.A.due.values()), {0.0})

    def test_a_place_change_pokes_with_the_gate_on_only(self):
        A, S = self.A, self.server
        A.due = {k: 99.0 for k in A.due}
        self.tick()
        self.assertEqual(A.wkey, (51.5, -0.1))
        self.assertEqual(set(A.due.values()), {0.0})
        A.due = {k: 99.0 for k in A.due}
        self.tick()
        self.assertEqual(set(A.due.values()), {99.0})           # same place: no poke
        S.CFG["look_weather"] = False
        self.places = {"now": {"latitude": 1.0, "longitude": 2.0}, "home": None, "work": None}
        self.tick()
        self.tick()
        self.assertEqual(set(A.due.values()), {99.0})           # gate off: never pokes
        self.assertEqual(A.wkey, (51.5, -0.1))

    def test_settings_poke_on_look_weather_and_proactive(self):
        src = (self.server.Path(self.server.__file__)).read_text()
        self.assertIn('if any(k.startswith("ambient_") for k in upd) or "proactive" in upd or "look_weather" in upd:\n'
                      "                    Ambient.poke()", src)

    # ---- day
    def test_day_from_is_day_then_the_hour(self):
        A = self.A
        self.hold(day=0)
        self.tick(hour=12)
        self.assertFalse(A.day)
        self.hold(day=1)
        self.tick(hour=2)
        self.assertTrue(A.day)
        self.hold(day=None)
        for hour, want in ((6, False), (7, True), (18, True), (19, False)):
            self.tick(hour=hour)
            self.assertIs(A.day, want, hour)
        A.wx = None
        self.tick(hour=12)
        self.assertTrue(A.day)

    # ---- /api/state
    def test_state_has_the_weather_and_its_source(self):
        S = self.server
        with mock.patch.object(S.quick, "projects", return_value={}):
            self.assertIn("source", S.state_info()["weather"])
            self.hold(sky="snow", feel=-1, wind=30)
            self.tick()
            w = S.state_info()["weather"]
        self.assertEqual((w["source"], w["sky"], w["feel"], w["wind"], w["day"]), ("open-meteo", "snow", -1, 30, True))
        self.assertTrue(set(w) >= {"cold", "windy", "lean", "heavy"})
        self.assertIn("weather", self.A.situation())


class WeatherNudgeTest(_ServerEnv):
    def setUp(self):
        S = self.server
        A, N = S.Ambient, S.Nudge
        cfg = dict(S.CFG)
        a = {k: getattr(A, k) for k in ("storm", "hot", "locked", "dnd", "fullscreen", "meeting", "unlocked_at")}
        n = {k: getattr(N, k) for k in ("pending", "last_visual", "last_speech", "last_kind", "active_since",
                                      "seen_unlock", "was_hot", "was_low", "quipped", "coding_offered")}
        last_event, coding_since = S.Desk.last_event, S.Desk.coding_since
        def restore():
            S.CFG.clear()
            S.CFG.update(cfg)
            for k, v in a.items():
                setattr(A, k, v)
            for k, v in n.items():
                setattr(N, k, v)
            S.Desk.last_event, S.Desk.coding_since = last_event, coding_since
        self.addCleanup(restore)
        S.CFG.update(proactive=True, ambient_weather=True, look_weather=True, react_quips=False,
                     react_load=False, react_break=False, react_welcome=False)
        A.storm = A.hot = A.locked = A.dnd = A.fullscreen = A.meeting = False
        A.unlocked_at = 0.0
        N.pending, N.last_kind, N.quipped = {}, {}, {}
        N.last_visual = N.last_speech = N.active_since = None
        N.seen_unlock = N.coding_offered = 0.0
        N.was_hot = N.was_low = False
        S.Desk.last_event, S.Desk.coding_since = 1.0, 0.0
        self.q = S.BUS.sub()
        self.addCleanup(S.BUS.unsub, self.q)

    def tick(self, t):
        self.server.Nudge.tick(mono=t, wall=10000, hist=os.path.join(self.tmp, "absent-history.json"))
        out = []
        while not self.q.empty():
            event = self.q.get_nowait()
            if event.get("t") == "nudge":
                out.append((event["kind"], event["speak"]))
        return out

    def test_storm_and_hot_offer_once_with_weather_gate_only(self):
        A = self.server.Ambient
        A.storm = True
        self.assertEqual(self.tick(1000), [("storm", False)])
        self.assertEqual(self.tick(1400), [])
        A.storm, A.hot = False, True
        self.assertEqual(self.tick(1800), [("hot", False)])
        self.assertEqual(self.tick(2200), [])
        A.hot = False
        self.tick(2600)
        A.hot = True
        self.assertEqual(self.tick(3000), [])  # a second edge is inside the 20-hour cooldown
        self.assertEqual(self.tick(75001), [("hot", False)])

    def test_weather_gate_rearms_a_storm(self):
        S = self.server
        S.Ambient.storm = True
        self.assertEqual(self.tick(1000), [("storm", False)])
        S.CFG["ambient_weather"] = False
        self.assertEqual(self.tick(1400), [])
        self.assertFalse(S.Nudge.quipped["storm"])
        S.CFG["ambient_weather"] = True
        self.assertEqual(self.tick(1500), [])  # re-armed, but still cooling down
        self.assertEqual(self.tick(73001), [("storm", False)])


if __name__ == "__main__":
    unittest.main()
