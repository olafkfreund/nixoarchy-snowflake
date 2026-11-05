"""Start the local-only headless test browser. The sandbox goes off only where it can't start (#184)."""
import functools
import subprocess
import sys

# Runs in a fresh child: a raw clone from a process with other threads could deadlock its clone child on the GIL.
# 0 = allowed, 1 = denied, 2 = inconclusive. An exception must not exit 1, the code for a real denial.
_CHILD = """
import os
try:
    import ctypes
    nr = {"x86_64": 56, "aarch64": 220}.get(os.uname().machine)  # SYS_clone; flake.nix builds these two
    if nr is None:
        os._exit(0)
    libc = ctypes.CDLL(None)
    libc.syscall.argtypes = [ctypes.c_long] * 6                  # syscall is variadic
    libc.syscall.restype = ctypes.c_long
    r = libc.syscall(nr, 0x10000000 | 17, 0, 0, 0, 0)            # CLONE_NEWUSER | SIGCHLD
    if r == 0:
        os._exit(0)
    if r < 0:
        os._exit(1)
    os._exit(0 if os.waitpid(r, 0)[1] == 0 else 2)
except Exception:
    os._exit(2)
"""


def _probe():
    """The child's exit code, or None if it couldn't run or timed out."""
    # shortcut: the probe only checks clone, upgrade it if a host with that restriction runs the suite.
    try:
        return subprocess.run([sys.executable, "-c", _CHILD], timeout=10,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    except (OSError, subprocess.SubprocessError):
        return None


_probed = functools.cache(_probe)


def _flags(code):
    """Only a real denial turns the sandbox off, and then only local names resolve."""
    return ["--no-sandbox", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"] if code == 1 else []


def start_browser(browser, cdp_port, data_dir, *extra, env=None):
    """Returns the Popen. The GPU flags must not change: a GPU-forced Chrome hung an AMD GPU twice (#138)."""
    return subprocess.Popen([browser, "--headless=new", "--disable-gpu", "--use-angle=swiftshader",
                             "--enable-unsafe-swiftshader", "--disable-gpu-compositing", *_flags(_probed()), *extra,
                             f"--user-data-dir={data_dir}", f"--remote-debugging-port={cdp_port}",
                             "--no-first-run", "about:blank"],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
