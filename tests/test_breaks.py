"""#209 part 3, step 1: workout and water settings."""

import json
from unittest import mock

from test_speakable import _ServerEnv


class BreakSettingsTest(_ServerEnv):
    def setUp(self):
        s = self.server
        saved = dict(s.CFG)
        self.addCleanup(lambda: (s.CFG.clear(), s.CFG.update(saved)))
        for patch in (mock.patch.object(s.quick, "projects", return_value={}),
                      mock.patch.object(s.subprocess, "run", side_effect=FileNotFoundError),
                      mock.patch.object(s, "_run", side_effect=AssertionError("unexpected shell IPC")),
                      mock.patch.object(s, "_gog", side_effect=AssertionError("unexpected gog")),
                      mock.patch.object(s.Wake, "ensure")):
            patch.start()
            self.addCleanup(patch.stop)

    def post(self, body):
        s = self.server
        handler = s.Handler.__new__(s.Handler)
        handler.path = "/api/settings"
        handler.headers = {"Host": "localhost", "X-Nixi-Token": s.TOKEN}
        with mock.patch.object(handler, "_body", return_value=json.dumps(body).encode()), \
             mock.patch.object(handler, "_json", side_effect=lambda obj, code=200: obj):
            return handler.do_POST()

    def test_defaults_and_info(self):
        s = self.server
        self.assertEqual(s.DEFAULTS["workout"], [])
        self.assertEqual(s.DEFAULTS["water_every"], 0)
        info = self.post({})
        self.assertEqual(info["workout"], s.CFG.get("workout") or [])
        self.assertEqual(info["water_every"], s.CFG.get("water_every") or 0)

    def test_valid_values_save_and_sort_days(self):
        s = self.server
        workout = [{"days": [6, 0, 2], "at": "23:30"}, {"days": [1], "at": "00:00"}]
        info = self.post({"workout": workout, "water_every": 45})
        expected = [{"days": [0, 2, 6], "at": "23:30"}, {"days": [1], "at": "00:00"}]
        self.assertEqual(info["workout"], expected)
        self.assertEqual(info["water_every"], 45)
        self.assertEqual(s.CFG["workout"], expected)
        self.assertEqual(json.loads(s.CONF_PATH.read_text())["workout"], expected)
        for minutes in (0, 60, 90):
            self.assertEqual(self.post({"water_every": minutes})["water_every"], minutes)
        self.assertEqual(self.post({"workout": []})["workout"], [])

    def test_invalid_values_leave_saved_values_untouched(self):
        s = self.server
        baseline = [{"days": [0, 4], "at": "09:30"}]
        self.post({"workout": baseline, "water_every": 60})
        bad_workouts = [
            baseline * 8,
            [{"days": [0], "at": "24:00"}],
            [{"days": [7], "at": "09:30"}],
            [{"days": [0], "at": "09:30", "extra": True}],
            [{"days": [0, 0], "at": "09:30"}],
            [{"days": [True], "at": "09:30"}],
            [{"days": [], "at": "09:30"}],
        ]
        for value in bad_workouts:
            with self.subTest(workout=value):
                info = self.post({"workout": value})
                self.assertEqual(info["workout"], baseline)
                self.assertEqual(s.CFG["workout"], baseline)
                self.assertEqual(json.loads(s.CONF_PATH.read_text())["workout"], baseline)
        for value in (True, 30):
            with self.subTest(water_every=value):
                info = self.post({"water_every": value})
                self.assertEqual(info["water_every"], 60)
                self.assertEqual(s.CFG["water_every"], 60)
                self.assertEqual(json.loads(s.CONF_PATH.read_text())["water_every"], 60)
