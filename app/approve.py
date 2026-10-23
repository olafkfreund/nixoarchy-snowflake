#!/usr/bin/env python3
"""Claude Code PreToolUse hook used by Nixi's "Ask me first" mode.

Claude Code runs this before a command / web request. It asks the Nixi server, which shows the request under Nixi
(and asks out loud); you say or click yes/no. Prints the hook decision JSON. If Nixi isn't running, it stays out of the
way (exit 0, no decision → Claude Code's normal rules apply).
"""
import json
import os
import sys
import urllib.request


def main():
    try:
        d = json.load(sys.stdin)
    except ValueError:
        d = {}
    port, tok = os.environ.get("NIXI_COMPANION_PORT"), os.environ.get("NIXI_COMPANION_TOKEN")
    if not port or not tok:
        return 0
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/approve",
        data=json.dumps({"tool": d.get("tool_name") or "?", "input": d.get("tool_input") or {}}).encode(),
        headers={"Content-Type": "application/json", "X-Nixi-Token": tok})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=900))
    except Exception as e:  # noqa: BLE001
        r = {"ok": False, "why": f"couldn't reach Nixi to ask the user ({e})"}
    ok = bool(r.get("ok"))
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow" if ok else "deny",
        "permissionDecisionReason": r.get("why") or ("the user approved it" if ok else
                                                       "the user said no — ask what they'd like instead"),
    }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
