"""Runs each tests/test_*.py in its own process with a deadline, a fresh HOME and an explicit skip allow-list (#63).
    python3 -B .github/ci/run_tests.py [--deadline S] [--allow FILE] [--exclude NAME]... [--tests DIR] [PATTERN...]
A file fails on a non-zero exit, a timeout, a missing report, no tests run, or a skip not in the allow-list."""
import argparse
import ctypes
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def allowed(path):
    """Lines: `<file>::<id without module>  # reason`. A missing reason is an error: every skip says why."""
    out = set()
    for n, ln in enumerate(Path(path).read_text().splitlines(), 1):
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        key, sep, why = ln.partition("#")
        if not sep or not why.strip():
            sys.exit(f"{path}:{n}: an allow-list entry needs a reason")
        out.add(key.strip())
    return out


def child(tests, name, report):
    """In the test's own process: run one file, then write {"run": n, "skipped": [[id, reason]...]}."""
    suite = unittest.defaultTestLoader.discover(tests, pattern=name, top_level_dir=tests)
    r = unittest.TextTestRunner(verbosity=2).run(suite)
    Path(report).write_text(json.dumps({"run": r.testsRun, "skipped": [[t.id(), why] for t, why in r.skipped]}))
    sys.exit(0 if r.wasSuccessful() else 1)


def subreaper():
    """Orphans of a test (a server started in its own session) are re-parented to us, so we can kill them."""
    try:
        ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0)   # PR_SET_CHILD_SUBREAPER
    except (OSError, AttributeError):
        pass


def reap_orphans():
    """Kill every process still parented to us, until none is left: a test file must leave nothing running."""
    me = str(os.getpid())
    for _ in range(50):
        kids = []
        for d in Path("/proc").iterdir():
            try:
                if d.name.isdigit() and (d / "stat").read_text().rsplit(")", 1)[1].split()[1] == me:
                    kids.append(int(d.name))
            except (OSError, IndexError):
                continue
        if not kids:
            return
        for pid in kids:
            try:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            except (ProcessLookupError, ChildProcessError, PermissionError):
                pass
        time.sleep(0.1)


def run(tests, f, deadline):
    t = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="nixi-ci-") as tmp:
        home, rt, report, log = (Path(tmp) / n for n in ("home", "run", "report.json", "out.txt"))
        home.mkdir(mode=0o700)
        rt.mkdir(mode=0o700)
        env = {**os.environ, "HOME": str(home), "XDG_RUNTIME_DIR": str(rt)}   # never the runner's own HOME
        with open(log, "w") as out:   # a file, not a pipe: a leftover child holding it can't stall us
            p = subprocess.Popen([sys.executable, "-B", __file__, "--child", tests, f.name, str(report)],
                                 cwd=REPO, env=env, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                p.wait(timeout=deadline)
                timed_out = False
            except subprocess.TimeoutExpired:
                timed_out = True
            try:
                os.killpg(p.pid, signal.SIGKILL)   # leftovers in the file's own group
            except (ProcessLookupError, PermissionError):
                pass
            p.wait()
            reap_orphans()
        text = log.read_text(errors="replace")
        try:
            rep = json.loads(report.read_text())
            run_n, skips = int(rep["run"]), [(str(i), str(w)) for i, w in rep["skipped"]]
        except (OSError, ValueError, KeyError, TypeError):
            run_n, skips = None, []
    return p.returncode, timed_out, text, run_n, skips, time.monotonic() - t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", nargs=3, help=argparse.SUPPRESS)
    ap.add_argument("--deadline", type=int, default=300)
    ap.add_argument("--allow", default=str(REPO / ".github/ci/skips.txt"))
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--tests", default=str(REPO / "tests"))
    ap.add_argument("patterns", nargs="*")
    a = ap.parse_args()
    if a.child:
        child(*a.child)
    tests = str(Path(a.tests).resolve())
    ok_skips = allowed(a.allow)
    files = set()
    for pat in a.patterns or ["test_*.py"]:
        hit = set(Path(tests).glob(pat))
        if not hit:
            sys.exit(f"no test file matches {pat}")
        files |= hit
    files = sorted(f for f in files if f.name not in a.exclude)
    subreaper()
    bad = []
    for f in files:
        rc, to, out, run_n, raw, dt = run(tests, f, a.deadline)
        skips = [(f"{f.name}::{tid.removeprefix(f.stem + '.')}", why) for tid, why in raw]
        stray = [s for s in skips if s[0] not in ok_skips]
        state = ("TIMEOUT" if to else "FAIL" if rc else "NOREPORT" if run_n is None
                 else "EMPTY" if not run_n and not skips else "SKIP?" if stray else "ok")
        print(f"{state:8} {dt:7.1f}s  run={run_n if run_n is not None else '-':<4} skips={len(skips):<3} {f.name}",
              flush=True)
        for k, why in skips:
            print(f"           {'allowed' if k in ok_skips else 'NOT ALLOWED'}: {k}  ({why})")
        if state != "ok":
            bad.append(f.name)
            print(f"::group::{f.name} output\n{out}\n::endgroup::", flush=True)
    print(f"\n{len(files) - len(bad)}/{len(files)} files passed" + (f"; failed: {' '.join(bad)}" if bad else ""))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
