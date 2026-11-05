import os
import tempfile
import unittest
from pathlib import Path

import nixi_env


class NixiEnvTest(unittest.TestCase):
    def test_server_env(self):
        with tempfile.TemporaryDirectory() as home:
            env = {"XDG_RUNTIME_DIR": "original", "OTHER": "value"}
            server = nixi_env.server_env(env, home)
            run = Path(home) / "run"
            self.assertEqual(server, {"XDG_RUNTIME_DIR": str(run), "OTHER": "value"})
            self.assertEqual(env["XDG_RUNTIME_DIR"], "original")
            self.assertTrue(run.is_dir())
            self.assertEqual(run.stat().st_mode & 0o777, 0o700)

    def test_run_dir_is_reused(self):
        self.assertEqual(nixi_env.run_dir(), nixi_env.run_dir())
        self.assertTrue(Path(nixi_env.run_dir()).is_dir())

    def test_check_floor_path(self):
        with tempfile.TemporaryDirectory() as home:
            nixi_env.check_floor_path(Path(home) / "nixarchy-voice-floor.lock")
        live = f"/run/user/{os.getuid()}/x"
        with self.assertRaisesRegex(RuntimeError, live):
            nixi_env.check_floor_path(live)


if __name__ == "__main__":
    unittest.main()
