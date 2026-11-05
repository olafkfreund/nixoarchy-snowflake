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
HOME = {"name": "Lisbon", "latitude": 38.72, "longitude": -9.14}


class LocationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_env = os.environ.copy()
        cls.tmp = tempfile.mkdtemp(prefix="nixi-location-test-")
        for k, d in (("HOME", ""), ("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
            os.environ[k] = os.path.join(cls.tmp, d)
            os.makedirs(os.environ[k], exist_ok=True)
        cls.dir = Path(cls.tmp, ".local/state/omarchy/settings")
        sys.path.insert(0, str(REPO_ROOT / "app"))
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": nixi_env.run_dir()}):
            import server
        cls.server = server

    @classmethod
    def tearDownClass(cls):
        os.environ.clear()
        os.environ.update(cls._orig_env)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True)
        self.server.LOC_CACHE.update(at=-1e9, v=None)

    def write(self, name, obj):
        (self.dir / name).write_text(json.dumps(obj))

    def no_command(self):
        return mock.patch.object(self.server.subprocess, "run", side_effect=FileNotFoundError("nixarchy-location"))

    def command(self, out, rc=0):
        return mock.patch.object(self.server.subprocess, "run", return_value=mock.Mock(stdout=json.dumps(out) if not isinstance(out, str) else out, returncode=rc))

    # ---- the command
    def test_command_is_run_as_argv_with_a_timeout(self):
        with self.command({"now": HOME, "chosen": True, "how": "picked", "home": HOME, "work": None}) as run:
            v = self.server.location()
        self.assertEqual(run.call_args[0][0], ["nixarchy-location", "--json"])
        self.assertEqual(run.call_args[1]["timeout"], 2)
        self.assertEqual(v, {"now": HOME, "chosen": True, "how": "picked", "home": HOME, "work": None})

    def test_cached_for_a_minute(self):
        with self.command({"now": None, "chosen": False, "how": "auto", "home": None, "work": None}) as run:
            self.server.location()
            self.server.location()
            self.assertEqual(run.call_count, 1)
            self.server.LOC_CACHE["at"] -= 61
            self.server.location()
            self.assertEqual(run.call_count, 2)

    def test_output_is_cleaned(self):
        bad = {"now": {"name": "a\nb"}, "chosen": True, "how": "x", "home": {"name": "x" * 121}, "work": {"name": "Ok", "latitude": 1}}
        with self.command(bad):
            v = self.server.location()
        self.assertEqual(v, {"now": None, "chosen": False, "how": "auto", "home": None, "work": {"name": "Ok"}})

    # ---- the fallback: the two files
    def test_missing_command_reads_the_files(self):
        self.write("weather.json", {**HOME, "source": "wifi"})
        self.write("places.json", {"home": HOME, "work": {"name": "Porto"}, "wifi": {"Net": "home"}})
        with self.no_command():
            v = self.server.location()
        self.assertEqual(v, {"now": HOME, "chosen": True, "how": "wifi", "home": HOME, "work": {"name": "Porto"}})
        self.assertNotIn("Net", json.dumps(v))

    def test_command_failing_reads_the_files_too(self):
        self.write("weather.json", {"name": "Oslo"})
        with self.command("", rc=1):
            v = self.server.location()
        self.assertEqual((v["chosen"], v["how"], v["now"]), (True, "picked", {"name": "Oslo"}))
        self.assertEqual(v["home"], {"name": "Oslo"})          # (a picked file is Home until places.json exists)

    def test_a_picked_work_is_not_home_once_places_exist(self):
        self.write("weather.json", {"name": "Porto"})
        self.write("places.json", {"work": {"name": "Porto"}})
        with self.no_command():
            v = self.server.location()
        self.assertEqual((v["chosen"], v["home"], v["work"]), (True, None, {"name": "Porto"}))

    def test_no_files_is_not_chosen(self):
        with self.no_command():
            v = self.server.location()
        self.assertEqual(v, {"now": None, "chosen": False, "how": "auto", "home": None, "work": None})

    def test_a_wifi_place_is_not_a_home(self):
        self.write("weather.json", {"name": "Cafe", "source": "wifi"})
        with self.no_command():
            self.assertIsNone(self.server.location()["home"])

    def test_broken_files_are_no_location(self):
        (self.dir / "weather.json").write_text("not json")
        (self.dir / "places.json").write_text("[1]")
        with self.no_command():
            self.assertFalse(self.server.location()["chosen"])

    # ---- the agent note
    def note(self):
        sent = []
        p = mock.Mock(stdout=iter([json.dumps({"type": "done"}) + "\n"]))
        with mock.patch.object(self.server.BRIDGE, "start", return_value=p), mock.patch.object(self.server.BRIDGE, "send", lambda m: sent.append(m)), \
                mock.patch.object(self.server.BRIDGE, "close"):
            self.server.run_bridge("directions to Oxford station", lambda **kw: None)
        return sent[0]["text"]

    def test_note_names_the_place_only_when_chosen(self):
        self.write("weather.json", HOME)
        with self.no_command():
            text = self.note()
        self.assertIn("The user is in Lisbon.", text)
        self.assertNotIn("38.72", text)
        self.assertIn('"@home"', text)
        os.remove(self.dir / "weather.json")
        self.server.LOC_CACHE.update(at=-1e9, v=None)
        with self.no_command():
            self.assertNotIn("The user is in", self.note())

    def test_note_has_no_home_address(self):
        self.write("places.json", {"home": {"name": "12 Secret Lane"}})
        with self.no_command():
            self.assertNotIn("Secret Lane", self.note())

    def test_note_survives_a_command_that_hangs(self):
        with mock.patch.object(self.server.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 2)):
            self.assertNotIn("The user is in", self.note())


if __name__ == "__main__":
    unittest.main()
