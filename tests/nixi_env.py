"""Runtime folders for tests that import or start the Nixi server."""

import atexit
import functools
import shutil
import tempfile
from pathlib import Path


@functools.cache
def run_dir():
    """One throwaway runtime folder per test process, removed at exit."""
    run = tempfile.mkdtemp(prefix="nixi-test-run-")
    atexit.register(shutil.rmtree, run, ignore_errors=True)
    return run


def server_env(env, home):
    """Copy a server environment with a runtime folder inside its throwaway home."""
    run = Path(home) / "run"
    run.mkdir(mode=0o700, exist_ok=True)
    return dict(env, XDG_RUNTIME_DIR=str(run))


def check_floor_path(path):
    if not Path(path).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise RuntimeError(f"voice floor is outside a throwaway runtime folder: {path}")
