"""Generation metadata and rate caching for system status."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import plugins  # noqa: E402


class SystemStatus(unittest.TestCase):
    def setUp(self):
        plugins._last.clear()
        plugins._generation_details.clear()

    def test_stale_reading_takes_two_fresh_samples(self):
        plugins._last.update(cpu=(1, 2), net=(1, 1), t=69)
        with mock.patch.object(plugins.time, "monotonic", return_value=100), \
             mock.patch.object(plugins.time, "sleep") as sleep, \
             mock.patch.object(plugins, "_cpu", side_effect=[(10, 20), (20, 40)]) as cpu, \
             mock.patch.object(plugins, "_net", side_effect=[(100, 200), (200, 400)]):
            self.assertEqual(plugins._rates()[0], 50.0)
        sleep.assert_called_once_with(0.25)
        self.assertEqual(cpu.call_count, 2)

    def test_recent_calls_share_computed_rates(self):
        plugins._last.update(cpu=(10, 20), net=(100, 200), t=100)
        with mock.patch.object(plugins.time, "monotonic", side_effect=[101, 101, 101.5]), \
             mock.patch.object(plugins, "_cpu", return_value=(20, 40)) as cpu, \
             mock.patch.object(plugins, "_net", return_value=(200, 400)) as net:
            first = plugins._rates()
            self.assertEqual(plugins._rates(), first)
        cpu.assert_called_once()
        net.assert_called_once()

    def test_user_false_skips_user_systemctl(self):
        calls = []

        def run(cmd, **kwargs):
            calls.append(cmd)
            return mock.Mock(returncode=0, stdout="")

        with mock.patch.object(plugins.os, "readlink", return_value="/nix/store/generation"), \
             mock.patch.object(plugins.subprocess, "run", side_effect=run), \
             mock.patch.object(plugins, "_rates", return_value=(None, None, None)):
            result = plugins.system_status(user=False)
        self.assertIsNone(result["failed"])
        self.assertEqual([cmd for cmd in calls if cmd[0] == "systemctl"],
                         [["systemctl", "--failed", "--plain", "--no-legend"]])

    def test_revision_and_build_cached_per_target(self):
        targets = iter(["/nix/store/one", "/nix/store/one", "/nix/store/two"])
        stat = mock.Mock(st_mtime=1793790740)      # the generation link's own time, not its store target's (mtime 1)

        def readlink(path):
            return "system-7-link" if path == "/nix/var/nix/profiles/system" else next(targets)
        with mock.patch.object(plugins.os, "readlink", side_effect=readlink), \
             mock.patch.object(plugins.os, "lstat", return_value=stat) as get_stat, \
             mock.patch.object(plugins.subprocess, "run", return_value=mock.Mock(
                 returncode=0, stdout='{"configurationRevision":"abc"}')) as run, \
             mock.patch.object(plugins, "_rates", return_value=(None, None, None)):
            results = [plugins.system_status(user=False) for _ in range(3)]
        self.assertEqual([r["rev"] for r in results], ["abc"] * 3)
        self.assertEqual([r["built"] for r in results], ["2026-11-04T11:12:20+00:00"] * 3)
        get_stat.assert_called_with("/nix/var/nix/profiles/system-7-link")
        self.assertEqual(run.call_count, 5)  # two revision reads and three systemctl calls
        self.assertEqual(get_stat.call_count, 2)
        self.assertEqual(run.call_args_list[0].kwargs["timeout"], 1)

    def test_missing_revision_is_null(self):
        with mock.patch.object(plugins.subprocess, "run", side_effect=FileNotFoundError):
            self.assertEqual(plugins._rev_built("/nix/store/missing")[0], None)


if __name__ == "__main__":
    unittest.main()
