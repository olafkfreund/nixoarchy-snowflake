"""Runs each tests/test_*.py in its own process group with a deadline (#63).
    python3 -B .github/ci/run_tests.py [--deadline S] [--allow FILE] [PATTERN...]
Fails on a non-zero exit, a timeout, or a skip whose test id isn't in the allow-list."""
import argparse
import json
import os
import tempfile
import unittest
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SLOW = {"test_character_fit.py": 1800, "test_accessories_fit.py": 1800}   # measured on p620 (#63)


def allowed(path):
    """Lines: `<file>::<Class>.<test>  # reason`. A missing reason is an error: every skip says why."""
    out = set()
    for n, ln in enumerate(Path(path).read_text().splitlines(), 1):
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        key, sep, why = ln.partition("#")
        if not sep or not why.strip():
            sys.exit(f"{path}:{n}: an allow-list entry needs a reason")
        out.add(key.strip())
    return out


def child(name, report):
    """In the test's own process: run one file, write its skips as JSON. Exit 0 only on success with tests run."""
    suite = unittest.defaultTestLoader.discover(str(REPO / "tests"), pattern=name, top_level_dir=str(REPO / "tests"))
    r = unittest.TextTestRunner(verbosity=2).run(suite)
    Path(report).write_text(json.dumps([[t.id(), why] for t, why in r.skipped]))
    sys.exit(0 if r.wasSuccessful() and r.testsRun else 1)


def run(f, deadline):
    t = time.monotonic()
    report = tempfile.mktemp(prefix="nixi-skips-", suffix=".json")
    p = subprocess.Popen([sys.executable, "-B", __file__, "--child", f.name, report],
                         cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         start_new_session=True)
    try:
        out, _ = p.communicate(timeout=deadline)
        timed_out = False
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        try:
            os.killpg(p.pid, signal.SIGKILL)   # children (servers, browsers) die with the file
        except ProcessLookupError:
            pass
    if timed_out:
        out, _ = p.communicate()
    try:
        skips = json.loads(Path(report).read_text())
        os.unlink(report)
    except (OSError, ValueError):
        skips = []
    return p.returncode, timed_out, out, skips, time.monotonic() - t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deadline", type=int, default=600)
    ap.add_argument("--child", nargs=2, help=argparse.SUPPRESS)
    ap.add_argument("--allow", default=str(REPO / ".github/ci/skips.txt"))
    ap.add_argument("patterns", nargs="*", default=["test_*.py"])
    a = ap.parse_args()
    if a.child:
        child(*a.child)
    ok_skips = allowed(a.allow) if Path(a.allow).exists() else set()
    files = sorted({f for pat in a.patterns for f in (REPO / "tests").glob(pat)})
    if not files:
        sys.exit("no test files matched")
    bad = []
    for f in files:
        rc, to, out, raw, dt = run(f, SLOW.get(f.name, a.deadline))
        skips = [(f"{f.name}::{'.'.join(tid.split('.')[-2:])}", why) for tid, why in raw]
        stray = [s for s in skips if s[0] not in ok_skips]
        state = "TIMEOUT" if to else ("FAIL" if rc else ("SKIP?" if stray else "ok"))
        print(f"{state:8} {dt:7.1f}s  skips={len(skips):<3} {f.name}", flush=True)
        for k, why in skips:
            print(f"           {'allowed' if k in ok_skips else 'NOT ALLOWED'}: {k}  ({why})")
        if state != "ok":
            bad.append(f.name)
            print(f"::group::{f.name} output\n{out[-20000:]}\n::endgroup::", flush=True)
    print(f"\n{len(files) - len(bad)}/{len(files)} files passed" + (f"; failed: {' '.join(bad)}" if bad else ""))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
