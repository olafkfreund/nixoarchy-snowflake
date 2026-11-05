import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import nixi_env

REPO_ROOT = Path(__file__).resolve().parent.parent


class LocationApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_env = os.environ.copy()
        cls.tmp = tempfile.mkdtemp(prefix="nixi-locapi-test-")
        for k, d in (("HOME", ""), ("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
            os.environ[k] = os.path.join(cls.tmp, d)
            os.makedirs(os.environ[k], exist_ok=True)
        cls.dir = Path(cls.tmp, ".local/state/omarchy/settings")
        sys.path.insert(0, str(REPO_ROOT / "app"))
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": nixi_env.run_dir()}):
            import server
        cls.s = server

    @classmethod
    def tearDownClass(cls):
        os.environ.clear()
        os.environ.update(cls._orig_env)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True)

    def run_ok(self, rc=0, err=""):
        return mock.Mock(return_value=mock.Mock(returncode=rc, stdout="", stderr=err))

    # ---- validation: a bad request builds no argv and runs nothing
    def test_bad_requests_run_nothing(self):
        bad = [{"act": "set", "place": "mars", "name": "x"}, {"act": "set", "place": "home", "name": ""},
               {"act": "set", "place": "home", "name": "a\nb"}, {"act": "set", "place": "home", "name": "x" * 121},
               {"act": "set", "place": "home", "name": "x", "latitude": 91, "longitude": 0},
               {"act": "set", "place": "home", "name": "x", "latitude": "1", "longitude": 2},
               {"act": "set", "place": "home", "name": "x", "latitude": 1},
               {"act": "set", "place": "home", "name": "x", "latitude": True, "longitude": 2},
               {"act": "now", "value": "away"}, {"act": "link", "place": "x"}, {"act": "unlink", "network": ""},
               {"act": "unlink", "network": "a\x00b"}, {"act": "rm"}, {}, [], "set"]
        for b in bad:
            run = self.run_ok()
            got = self.s.location_act(b, run)
            self.assertFalse(got["ok"], b)
            run.assert_not_called()

    def test_good_requests_are_argv_for_the_command(self):
        cases = [({"act": "set", "place": "home", "name": " Oxford ", "latitude": 51.752, "longitude": -1.2577},
                  ["set", "home", "Oxford", "51.752000,-1.257700"]),
                 ({"act": "set", "place": "work", "name": "Porto"}, ["set", "work", "Porto"]),
                 ({"act": "now", "value": "auto"}, ["now", "auto"]),
                 ({"act": "link", "place": "work"}, ["wifi", "link", "work"]),
                 ({"act": "unlink", "network": "Cafe: Main"}, ["wifi", "unlink", "Cafe: Main"]),
                 ({"act": "set", "place": "home", "name": "--json"}, ["set", "home", "--json"])]
        for b, argv in cases:
            run = self.run_ok()
            with mock.patch.object(self.s, "wifi_now", return_value=(False, None)), mock.patch.object(self.s, "location", return_value={"now": None, "chosen": False}):
                got = self.s.location_act(b, run)
            self.assertTrue(got["ok"], got)
            self.assertEqual(run.call_args[0][0], ["nixarchy-location", *argv])
            self.assertNotIn("shell", run.call_args[1])

    def test_writes_clear_the_cache(self):
        self.s.LOC_CACHE.update(at=self.s.time.monotonic(), v={"stale": 1})
        with mock.patch.object(self.s, "wifi_now", return_value=(False, None)), mock.patch.object(self.s, "location", return_value={}):
            self.s.location_act({"act": "now", "value": "auto"}, self.run_ok())
        self.assertIsNone(self.s.LOC_CACHE["v"])

    def test_missing_command_says_what_to_update(self):
        got = self.s.location_act({"act": "now", "value": "auto"}, mock.Mock(side_effect=FileNotFoundError()))
        self.assertEqual(got, {"ok": False, "error": "needs nixarchy-location (update nixarchy)"})
        self.assertEqual(list(self.dir.iterdir()), [])                 # (and nothing was written behind its back)

    def test_command_refusal_is_shown(self):
        got = self.s.location_act({"act": "now", "value": "home"}, self.run_ok(1, "nixarchy-location: home is not set\n"))
        self.assertEqual(got, {"ok": False, "error": "home is not set"})

    def test_timeout_is_an_error_not_a_crash(self):
        got = self.s.location_act({"act": "now", "value": "auto"}, mock.Mock(side_effect=subprocess.TimeoutExpired("x", 5)))
        self.assertFalse(got["ok"])

    # ---- the read side
    def test_wifi_parsing(self):
        out = "ethernet:connected:Wired\nwifi:connected:Cafe\\: Main\n"
        with mock.patch.object(self.s.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=out)):
            self.assertEqual(self.s.wifi_now(), (True, "Cafe: Main"))
        with mock.patch.object(self.s.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="wifi:connected:A\\\\B\\:C\n")):
            self.assertEqual(self.s.wifi_now(), (True, "A\\B:C"))
        with mock.patch.object(self.s.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="ethernet:connected:Wired\n")):
            self.assertEqual(self.s.wifi_now(), (False, None))
        with mock.patch.object(self.s.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="wifi:disconnected:\n")):
            self.assertEqual(self.s.wifi_now(), (True, None))
        with mock.patch.object(self.s.subprocess, "run", side_effect=FileNotFoundError()):
            self.assertEqual(self.s.wifi_now(), (False, None))

    def test_links_come_from_places_json_and_only_with_a_wifi_device(self):
        (self.dir / "places.json").write_text(json.dumps({"wifi": {"Net": "home", "Bad": "x"}}))
        self.assertEqual(self.s.location_links(), {"Net": "home"})
        with mock.patch.object(self.s, "wifi_now", return_value=(False, None)), mock.patch.object(self.s, "location", return_value={}):
            self.assertEqual(self.s.location_api()["wifi"], {"device": False, "network": None, "links": {}})
        with mock.patch.object(self.s, "wifi_now", return_value=(True, "Net")), mock.patch.object(self.s, "location", return_value={}):
            self.assertEqual(self.s.location_api()["wifi"]["links"], {"Net": "home"})

    # ---- suggestions
    def fake(self, body):
        seen = []

        def opener(url, timeout=None):
            seen.append((url, timeout))
            return io.BytesIO(body if isinstance(body, bytes) else json.dumps(body).encode())
        return opener, seen

    def test_suggest_shapes_five_places(self):
        body = {"results": [{"name": "Oxford", "admin1": "England", "country": "United Kingdom", "latitude": 51.75, "longitude": -1.26, "id": 1},
                            {"name": "bad\n", "latitude": 1, "longitude": 2}, {"name": "NoCoords"}, "junk"]}
        op, seen = self.fake(body)
        got = self.s.location_suggest("oxf", op)
        self.assertEqual(got, [{"name": "Oxford", "admin": "England", "country": "United Kingdom", "latitude": 51.75, "longitude": -1.26}])
        self.assertIn("count=5", seen[0][0])
        self.assertIn("language=en", seen[0][0])
        self.assertEqual(seen[0][1], 4)

    def test_suggest_refuses_odd_queries_without_a_request(self):
        op, seen = self.fake({"results": []})
        for q in ("", "a", "x" * 81, "a\nb", None, 5):
            self.assertEqual(self.s.location_suggest(q, op), [])
        self.assertEqual(seen, [])

    def test_suggest_failure_is_none(self):
        self.assertIsNone(self.s.location_suggest("oxford", mock.Mock(side_effect=OSError())))
        self.assertIsNone(self.s.location_suggest("oxford", self.fake(b"not json")[0]))


if __name__ == "__main__":
    unittest.main()
