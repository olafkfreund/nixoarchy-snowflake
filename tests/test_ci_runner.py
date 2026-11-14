"""The CI runner (#63): every way a test file can look green without being green must fail."""
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1] / ".github/ci/run_tests.py"

FILES = {
    "test_pass.py": "import unittest\nclass T(unittest.TestCase):\n    def test_a(self): pass\n",
    "test_fail.py": "import unittest\nclass T(unittest.TestCase):\n    def test_a(self): self.fail('no')\n",
    "test_skip_stray.py": "import unittest\nclass T(unittest.TestCase):\n    def test_a(self): self.skipTest('why')\n",
    "test_skip_ok.py": "import unittest\nclass T(unittest.TestCase):\n    def test_a(self): self.skipTest('why')\n",
    "test_skip_class.py": textwrap.dedent("""\
        import unittest
        class T(unittest.TestCase):
            @classmethod
            def setUpClass(cls): raise unittest.SkipTest('whole class')
            def test_a(self): pass
        """),
    "test_empty.py": "import unittest\n",
    "test_exit0.py": "import os\nos._exit(0)\n",
    "test_hang.py": textwrap.dedent("""\
        import os, subprocess, sys, time, unittest
        class T(unittest.TestCase):
            def test_a(self):
                # an orphan in its own session, holding nothing: it must not outlive the file
                p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"], start_new_session=True)
                open(os.environ["ORPHAN_PID"], "w").write(str(p.pid))
                time.sleep(600)
        """),
    "test_home.py": textwrap.dedent("""\
        import os, unittest
        class T(unittest.TestCase):
            def test_a(self):
                assert os.environ["HOME"] != os.environ["REAL_HOME"], "the runner must give each file its own HOME"
                assert os.path.isdir(os.environ["XDG_RUNTIME_DIR"])
        """),
}


class RunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        (d / "tests").mkdir()
        for name, body in FILES.items():
            (d / "tests" / name).write_text(body)
        (d / "skips.txt").write_text("test_skip_ok.py::T.test_a  # allowed on purpose\n"
                                     "test_skip_class.py::setUpClass (test_skip_class.T)  # a whole class, allowed\n")
        (d / "noreason.txt").write_text("test_skip_ok.py::T.test_a\n")
        cls.pidfile = d / "orphan.pid"
        cls.r = cls.go("--deadline", "4")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def go(cls, *args, allow="skips.txt"):
        d = Path(cls.tmp.name)
        env = {**os.environ, "ORPHAN_PID": str(cls.pidfile), "REAL_HOME": os.environ.get("HOME", "")}
        return subprocess.run([sys.executable, "-B", str(RUNNER), "--tests", str(d / "tests"), "--allow",
                               str(d / allow), *args], capture_output=True, text=True, timeout=120, env=env)

    def state(self, name):
        m = re.search(rf"^(\S+) +[\d.]+s .*\s{re.escape(name)}$", self.r.stdout, re.M)
        return m and m.group(1)

    def test_states(self):
        want = {"test_pass.py": "ok", "test_fail.py": "FAIL", "test_skip_stray.py": "SKIP?",
                "test_skip_ok.py": "ok", "test_skip_class.py": "ok", "test_empty.py": "EMPTY",
                "test_exit0.py": "NOREPORT", "test_hang.py": "TIMEOUT", "test_home.py": "ok"}
        self.assertEqual({n: self.state(n) for n in want}, want, self.r.stdout)
        self.assertEqual(self.r.returncode, 1)

    def test_a_timed_out_files_orphan_is_killed(self):
        pid = int(self.pidfile.read_text())
        for _ in range(20):
            if not Path(f"/proc/{pid}").exists():
                break
            time.sleep(0.1)
        self.assertFalse(Path(f"/proc/{pid}").exists(), f"orphan {pid} still running")

    def test_only_passing_files_exit_0(self):
        r = self.go("test_pass.py", "test_skip_ok.py")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_exclude_and_unmatched_pattern(self):
        r = self.go("--exclude", "test_fail.py", "test_pass.py", "test_fail.py")
        self.assertEqual(r.returncode, 0, r.stdout)
        r = self.go("test_pass.py", "test_nope.py")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("test_nope.py", r.stderr)

    def test_an_entry_without_a_reason_is_refused(self):
        r = self.go("test_pass.py", allow="noreason.txt")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("needs a reason", r.stderr)


if __name__ == "__main__":
    unittest.main()
