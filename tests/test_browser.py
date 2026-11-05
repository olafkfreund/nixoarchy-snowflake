"""Test browsers start through _browser.py, and the sandbox goes off only on a real denial (#184)."""
import unittest
from pathlib import Path

from _browser import _flags, _probe

HERE = Path(__file__).resolve()
TESTS = HERE.parent
ROOT = TESTS.parent


def _harnesses():
    return [f for f in sorted(TESTS.glob("test_*.py")) if f != HERE]


class GuardTest(unittest.TestCase):
    def test_harnesses_use_the_helper(self):
        hits = [f.name for f in _harnesses() if "--headless" in f.read_text() or "--no-sandbox" in f.read_text()]
        self.assertEqual(hits, [], "start the browser with _browser.start_browser")

    def test_never_in_the_app(self):
        hits = [str(f.relative_to(ROOT)) for base in ("app", "bin") for f in sorted((ROOT / base).rglob("*"))
                if f.is_file() and b"--no-sandbox" in f.read_bytes()]
        self.assertEqual(hits, [])

    def test_the_scans_see_what_they_should(self):   # guards against a scan that silently matches nothing
        self.assertIn("test_token_fit.py", [f.name for f in _harnesses()])
        self.assertIn("--headless", (TESTS / "_browser.py").read_text())


class FlagTest(unittest.TestCase):
    def test_only_a_denial_turns_the_sandbox_off(self):
        for code in (0, 2, -31, None):               # allowed, inconclusive, killed by a signal, timed out
            self.assertEqual(_flags(code), [])
        self.assertEqual(_flags(1), ["--no-sandbox", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"])

    def test_the_real_probe_gives_an_answer(self):
        self.assertIn(_probe(), (0, 1))


if __name__ == "__main__":
    unittest.main()
