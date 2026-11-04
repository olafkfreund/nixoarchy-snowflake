"""Headless-Chromium check for Settings → Voice (#176) and the page playback path."""
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

REPO = Path(__file__).resolve().parent.parent
BROWSER = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome-stable")
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

RUNNER = """
import email.message, io, json, os, runpy, sys, wave
sys.path.insert(0, os.path.join(os.getcwd(), "app"))
import eleven

buf = io.BytesIO()
with wave.open(buf, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(22050)
    w.writeframes(b"\\x00\\x00" * 2205)
WAV = buf.getvalue()

VOICES = json.dumps({
    "voices": [
        {
            "voice_id": "21m00Tcm4TlvDq8ikWAM",
            "name": "Rachel",
            "category": "premade",
            "description": "Calm narrator",
            "labels": {"accent": "american"},
            "verified_languages": [{"language": "en"}],
            "preview_url": "https://storage.googleapis.com/eleven-public-prod/rachel.wav",
        },
        {
            "voice_id": "AZnzlk1XvdvUeBnXmlld",
            "name": "<img src=x onerror=alert(1)>",
            "category": "cloned",
            "description": "<script>window.__pwn=1</script>",
            "labels": {"accent": "british"},
            "verified_languages": [{"language": "en"}],
            "preview_url": "https://storage.googleapis.com/eleven-public-prod/evil.wav",
        },
    ]
}).encode()

class _Resp:
    def __init__(self, body, ctype="application/json"):
        self.body = body
        self.headers = email.message.Message()
        self.headers["Content-Type"] = ctype
    def getcode(self):
        return 200
    def read(self, n=None):
        chunk = self.body[:n] if n else self.body
        self.body = self.body[n:] if n else b""
        return chunk
    def __enter__(self):
        return self
    def __exit__(self, *a):
        pass

def _fake_open(req, timeout=None):
    u = req.full_url
    if "/v1/voices" in u:
        return _Resp(VOICES, "application/json")
    if "/v1/text-to-speech/" in u:
        return _Resp(b"\\x00\\x00" * 2205, "application/octet-stream")
    if u.startswith("https://storage.googleapis.com"):
        return _Resp(WAV, "audio/wav")
    raise OSError("unexpected url: " + u)

eleven.urlopen = _fake_open
runpy.run_path(os.path.join(os.getcwd(), "app/server.py"), run_name="__main__")
"""


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(url, secs=20):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                r.read()
            return True
        except OSError:
            time.sleep(0.3)
    return False


@unittest.skipUnless(shutil.which("node") and BROWSER, "needs node and chromium")
class VoiceFit(unittest.TestCase):
    def test_voice_settings_and_playback_path(self):
        home = Path(tempfile.mkdtemp(prefix="nixi-voicefit-"))
        creds = home / "creds"
        creds.mkdir(mode=0o700, parents=True, exist_ok=True)
        key_file = creds / "api-elevenlabs"
        key_file.write_text("xi-test-key-0123456789\n")   # (a token: _key refuses anything else, #176 review)
        os.chmod(key_file, 0o600)
        env = dict(
            os.environ,
            HOME=str(home),
            XDG_CONFIG_HOME=str(home / ".config"),
            XDG_DATA_HOME=str(home / "data"),
            XDG_STATE_HOME=str(home / "state"),
            CREDENTIALS_DIRECTORY=str(creds),
        )
        for d in (".config/nixi-companion", "data", "state"):
            (home / d).mkdir(parents=True, exist_ok=True)
        port, cdp = _free_port(), _free_port()
        (home / ".config/nixi-companion/config.json").write_text(
            json.dumps({"port": port, "eleven_key_file": str(key_file)})
        )
        procs = []
        try:
            procs.append(
                subprocess.Popen(
                    [sys.executable, "-c", RUNNER],
                    cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            )
            procs.append(
                subprocess.Popen(
                    [
                        BROWSER, "--headless=new", "--disable-gpu", "--no-sandbox",
                        "--no-proxy-server", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                        "--disable-gpu-compositing", "--autoplay-policy=no-user-gesture-required",
                        f"--user-data-dir={home / 'chromium'}",
                        f"--remote-debugging-port={cdp}",
                        "--no-first-run", "about:blank",
                    ],
                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            )
            self.assertTrue(_wait(f"http://127.0.0.1:{port}/"), "server did not start")
            self.assertTrue(_wait(f"http://127.0.0.1:{cdp}/json/version"), "chromium did not start")
            for _ in range(40):
                rt = home / "data/nixi-companion/runtime.json"
                if rt.exists():
                    break
                time.sleep(0.25)
            token = json.loads(rt.read_text())["token"]
            r = subprocess.run(
                ["node", str(REPO / "tests/voice_fit.mjs"), str(cdp), f"http://127.0.0.1:{port}/#t={token}"],
                cwd=REPO, capture_output=True, text=True, timeout=120,
            )
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
