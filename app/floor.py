"""The shared voice floor for hands-free listeners and speakers."""

import ctypes
import fcntl
import os
import threading
import time


def pdeathsig_preexec():
    if ctypes.CDLL(None, use_errno=True).prctl(1, 9):  # PR_SET_PDEATHSIG, SIGKILL
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_PDEATHSIG)")


class Floor:
    def __init__(self, path=None, clock=time.monotonic):
        self.path = path or os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}",
                                         "nixarchy-voice-floor.lock")
        self.clock = clock
        self._lock = threading.Lock()
        self._keys = set()
        self._fd = None
        self._taken = None
        self._timer = None

    def _open(self):
        return os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)

    @staticmethod
    def _write(fd, line):
        os.ftruncate(fd, 0)
        os.pwrite(fd, line.encode(), 0)

    def hold(self, key, cancelled=None):
        # Polls outside self._lock, so a listener or drop() is never stuck behind a waiting speaker.
        fd = None
        try:
            while True:
                with self._lock:
                    if key in self._keys:
                        return True
                    if cancelled and cancelled():
                        return False
                    if self._fd is not None:
                        if self._timer:
                            self._timer.cancel()
                            self._timer = None
                        self._keys.add(key)
                        return True
                    if fd is None:
                        fd = self._open()
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        pass
                    else:
                        self._taken = self.clock()
                        self._write(fd, f"{os.getpid()} {self._taken}\n")
                        self._fd, fd = fd, None
                        self._keys.add(key)
                        return True
                time.sleep(0.05)
        finally:
            if fd is not None:
                os.close(fd)

    def _finish(self):
        if self._fd is not None:
            fd, self._fd = self._fd, None
            try:
                self._write(fd, f"{os.getpid()} {self._taken} {self.clock()}\n")
            finally:
                os.close(fd)

    def release(self, key, tail=0):
        with self._lock:
            self._keys.discard(key)
            if self._keys or self._fd is None or self._timer:
                return
            if tail <= 0:
                self._finish()
            else:
                timer = threading.Timer(tail, lambda: self._expire(timer))
                timer.daemon = True
                self._timer = timer
                timer.start()

    def _expire(self, timer):
        with self._lock:
            if self._timer is not timer:
                return
            self._timer = None
            if not self._keys:
                self._finish()

    def drop(self):
        with self._lock:
            self._keys.clear()
            if self._timer:
                self._timer.cancel()
                self._timer = None
            self._finish()

    def floor_overlaps(self, capture_start):
        with self._lock:
            if self._fd is not None:
                return False
            fd = self._open()
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
                line = os.pread(fd, 256, 0).decode(errors="replace")
                if not line.endswith("\n"):
                    return False
                fields = line.split()
                if len(fields) not in (2, 3) or not fields[0].isdigit() or int(fields[0]) == os.getpid():
                    return False
                try:
                    if len(fields) == 3:
                        return float(fields[2]) >= capture_start
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
                except ValueError:
                    return False
                # Complete a crashed holder's record so later captures can pass.
                if os.pread(fd, 256, 0).decode(errors="replace") == line:
                    self._write(fd, f"{fields[0]} {fields[1]} {self.clock()}\n")
                return True
            finally:
                os.close(fd)


FLOOR = Floor()


def floor_overlaps(capture_start):
    return FLOOR.floor_overlaps(capture_start)
