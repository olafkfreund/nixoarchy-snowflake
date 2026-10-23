#!/usr/bin/env python3
"""SUDO_ASKPASS helper for Nixi's root mode.

sudo runs this (via `sudo -A`) when Claude needs root. No window: it asks the Nixi server, which shows a small password
card right next to Nixi. The password is never remembered.
Prints the password to stdout for sudo. Nothing is written to disk. Cancel = sudo fails.
"""
import json
import os
import pwd
import sys
import urllib.request


def where():
    port, tok = os.environ.get("NIXI_COMPANION_PORT"), os.environ.get("NIXI_COMPANION_TOKEN")
    if port and tok:
        return port, tok
    home = os.environ.get("HOME") or pwd.getpwuid(os.getuid()).pw_dir      # sudo may have cleaned the environment
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    try:
        with open(os.path.join(base, "nixi-companion", "runtime.json")) as f:
            r = json.load(f)
        return str(r["port"]), r["tool_token"]          # the limited token: it can't do anything but this card
    except (OSError, ValueError, KeyError):
        return None, None


def main():
    prompt = (sys.argv[1] if len(sys.argv) > 1 else "").strip() or "Password:"
    port, tok = where()
    if not port:
        sys.exit(1)
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/askpass", data=json.dumps({"prompt": prompt}).encode(),
                                 headers={"Content-Type": "application/json", "X-Nixi-Token": tok})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=330))
    except Exception:  # noqa: BLE001
        sys.exit(1)
    if r.get("pw") is None:
        sys.exit(1)
    sys.stdout.write(r["pw"] + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
