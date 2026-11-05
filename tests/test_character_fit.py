"""Characters (#178): the Snowflake page is pixel-identical to origin/main, and each character holds to its registry contract (tests/character_fit.mjs).

Starts the server in a throwaway home and a headless Chromium with the GPU switched off (software rendering only: an
animated page on a GPU-forced Chrome hung an AMD GPU twice, #138). The pixel case builds origin/main in a temporary git
worktree (CHARACTER_BASE overrides the ref). Skipped without node and chromium. A character that is not in CHARACTERS
yet (step 3 artwork) skips its own case; nothing else is skipped."""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
import nixi_env
from _browser import start_browser

REPO = Path(__file__).resolve().parent.parent
BROWSER = shutil.which("chromium") or shutil.which("chromium-browser")
BASE_REF = os.environ.get("CHARACTER_BASE", "origin/main")
MISSING = 77                                                  # the .mjs says: this id is not in CHARACTERS


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(url, secs=20):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        try:
            urllib.request.urlopen(url, timeout=1).read()
            return True
        except OSError:
            time.sleep(0.3)
    return False


@unittest.skipUnless(shutil.which("node") and BROWSER, "needs node and chromium")
class CharacterFit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.procs, cls.dirs = [], []
        cls.cdp = _free_port()
        home = Path(tempfile.mkdtemp(prefix="nixi-charfit-"))
        cls.dirs.append(home)
        cls.procs.append(start_browser(BROWSER, cls.cdp, home / "chromium"))
        cls.url = cls._serve(REPO)
        assert _wait(f"http://127.0.0.1:{cls.cdp}/json/version"), "chromium did not start"

    @classmethod
    def _serve(cls, tree):
        """A server for `tree` in a throwaway home; returns the page URL with its token."""
        home = Path(tempfile.mkdtemp(prefix="nixi-charfit-"))
        cls.dirs.append(home)
        env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
                   XDG_DATA_HOME=str(home / "data"), XDG_STATE_HOME=str(home / "state"))
        for d in (".config/nixi-companion", "data", "state"):
            (home / d).mkdir(parents=True, exist_ok=True)
        port = _free_port()
        (home / ".config/nixi-companion/config.json").write_text(json.dumps({"port": port}))
        cls.procs.append(subprocess.Popen([sys.executable, str(tree / "app/server.py")], env=nixi_env.server_env(env, home),
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        assert _wait(f"http://127.0.0.1:{port}/"), "server did not start"
        rt = home / "data/nixi-companion/runtime.json"
        for _ in range(40):                                  # runtime.json carries the page's token
            if rt.exists():
                break
            time.sleep(0.25)
        return f"http://127.0.0.1:{port}/#t={json.loads(rt.read_text())['token']}"

    @classmethod
    def tearDownClass(cls):
        for p in cls.procs:
            p.terminate()
        for p in cls.procs:
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
        for d in cls.dirs:
            shutil.rmtree(d, ignore_errors=True)

    def node(self, *args):
        return subprocess.run(["node", str(REPO / "tests/character_fit.mjs"), str(self.cdp), self.url, *args],
                              capture_output=True, text=True, timeout=900)

    def test_snowflake_pixels_match_origin_main(self):
        if subprocess.run(["git", "rev-parse", "--verify", "-q", BASE_REF], cwd=REPO, capture_output=True).returncode:
            self.skipTest(f"no {BASE_REF} to compare with")
        wt = Path(tempfile.mkdtemp(prefix="nixi-charbase-")) / "base"
        subprocess.run(["git", "worktree", "add", "--detach", str(wt), BASE_REF], cwd=REPO, check=True, capture_output=True)
        try:
            base_url = self._serve(wt)
            r = self.node("pixels", base_url)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=REPO, capture_output=True)
            shutil.rmtree(wt.parent, ignore_errors=True)

    def _char(self, cid):
        r = self.node("char", cid)
        if r.returncode == MISSING and cid != "snowflake":
            self.skipTest("needs step 3 artwork")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_snowflake(self):
        self._char("snowflake")

    def test_terminal(self):
        self._char("terminal")

    def test_robot(self):
        self._char("robot")

    def test_devil(self):
        self._char("devil")


if __name__ == "__main__":
    unittest.main()
