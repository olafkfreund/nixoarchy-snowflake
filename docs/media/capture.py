"""Make the README pictures (#133) in a throwaway home with a headless, GPU-off Chromium.

    nix develop -c python3 docs/media/capture.py

Never the live desktop or the real config: the server gets its own HOME and runtime folder, like the tests."""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

# the live session: the server must not reach the desktop, its bus or the shell
LIVE = {"WAYLAND_DISPLAY", "DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "HYPRLAND_INSTANCE_SIGNATURE"}
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))
import nixi_env  # noqa: E402
from _browser import start_browser  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait(url, secs=30):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        try:
            urllib.request.urlopen(url, timeout=1).read()
            return True
        except OSError:
            time.sleep(0.3)
    return False


def main():
    browser = shutil.which("chromium") or shutil.which("chromium-browser")
    if not browser or not shutil.which("node"):
        sys.exit("needs chromium and node (run inside nix develop)")
    home = Path(tempfile.mkdtemp(prefix="nixi-capture-"))
    procs = []
    try:
        cdp, port = free_port(), free_port()
        env = {k: v for k, v in os.environ.items() if k not in LIVE}
        env.update({"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
               "XDG_DATA_HOME": str(home / "data"), "XDG_STATE_HOME": str(home / "state"), "XDG_CACHE_HOME": str(home / "cache")})
        for d in (".config/nixi-companion", "data", "state", "cache"):
            (home / d).mkdir(parents=True, exist_ok=True)
        (home / ".config/nixi-companion/config.json").write_text(json.dumps({"port": port, "update_check": False}))
        env = nixi_env.server_env(env, home)                 # adds a throwaway XDG_RUNTIME_DIR
        procs.append(start_browser(browser, cdp, home / "chromium", env=env))
        procs.append(subprocess.Popen([sys.executable, str(REPO / "app/server.py")], env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        if not (wait(f"http://127.0.0.1:{cdp}/json/version") and wait(f"http://127.0.0.1:{port}/")):
            sys.exit("chromium or the server did not start")
        rt = home / "data/nixi-companion/runtime.json"
        for _ in range(40):                                  # runtime.json carries the page's token
            if rt.exists():
                break
            time.sleep(0.25)
        url = f"http://127.0.0.1:{port}/#t={json.loads(rt.read_text())['token']}"
        subprocess.run(["node", str(Path(__file__).with_name("capture.mjs")), str(cdp), url, str(Path(__file__).parent)], check=True)
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
    main()
