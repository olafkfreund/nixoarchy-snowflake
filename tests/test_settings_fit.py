"""The Settings panel's size owner, default cap, CSS clamp, transitions and click region (tests/settings_fit.mjs, #175).

Starts the server in a throwaway home and a headless Chromium with the GPU switched off (software rendering only:
an animated page on a GPU-forced Chrome hung an AMD GPU twice, #138), then runs the check. Skipped without node and
chromium."""
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
from _browser import start_browser

REPO = Path(__file__).resolve().parent.parent
BROWSER = shutil.which("chromium") or shutil.which("chromium-browser")


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
class SettingsFit(unittest.TestCase):
    def test_settings_size_and_transitions(self):
        home = Path(tempfile.mkdtemp(prefix="nixi-setfit-"))
        env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
                   XDG_DATA_HOME=str(home / "data"), XDG_STATE_HOME=str(home / "state"))
        for d in (".config/nixi-companion", "data", "state"):
            (home / d).mkdir(parents=True, exist_ok=True)
        port, cdp = _free_port(), _free_port()
        (home / ".config/nixi-companion/config.json").write_text(json.dumps({"port": port}))
        procs = []
        try:
            procs.append(subprocess.Popen([sys.executable, str(REPO / "app/server.py")], env=env,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            procs.append(start_browser(BROWSER, cdp, home / "chromium"))
            self.assertTrue(_wait(f"http://127.0.0.1:{port}/"), "server did not start")
            self.assertTrue(_wait(f"http://127.0.0.1:{cdp}/json/version"), "chromium did not start")
            for _ in range(40):                              # runtime.json carries the page's token
                rt = home / "data/nixi-companion/runtime.json"
                if rt.exists():
                    break
                time.sleep(0.25)
            token = json.loads(rt.read_text())["token"]
            r = subprocess.run(["node", str(REPO / "tests/settings_fit.mjs"), str(cdp),
                                f"http://127.0.0.1:{port}/?native=1#t={token}"], capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        finally:
            for p in procs:
                p.terminate()
            for p in procs:
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
