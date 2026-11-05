import fcntl
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import nixi_env

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": nixi_env.run_dir()}):
    from floor import Floor


CHILD = """import sys
from floor import Floor
floor = Floor()
floor.hold('other')
print('ready', flush=True)
sys.stdin.readline()
floor.release('other', 0)
"""


class FloorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "nixarchy-voice-floor.lock")
        self.floor = Floor(self.path)
        self.addCleanup(self.floor.drop)
        self.env = {**os.environ, "XDG_RUNTIME_DIR": self.tmp.name,
                    "PYTHONPATH": str(Path(__file__).resolve().parent.parent / "app")}

    def child(self):
        child = subprocess.Popen([sys.executable, "-u", "-c", CHILD], env=self.env,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.addCleanup(self.stop_child, child)
        self.assertEqual(child.stdout.readline().strip(), "ready")
        return child

    @staticmethod
    def stop_child(child):
        if child.poll() is None:
            child.kill()
        child.communicate()

    def probe_free(self):
        fd = os.open(self.path, os.O_RDWR)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except BlockingIOError:
                return False
        finally:
            os.close(fd)

    def test_waits_for_child_to_release(self):
        child = self.child()
        done = threading.Event()
        waiter = threading.Thread(target=lambda: (self.floor.hold("speaker"), done.set()))
        waiter.start()
        self.addCleanup(waiter.join, 2)
        self.assertFalse(done.wait(0.12))
        child.communicate("\n", timeout=2)
        self.assertTrue(done.wait(2))
        self.assertFalse(self.probe_free())

    def test_capture_spanning_child_hold_is_rejected(self):
        start = time.monotonic()
        child = self.child()
        self.assertTrue(self.floor.floor_overlaps(start))
        child.communicate("\n", timeout=2)
        self.assertTrue(self.floor.floor_overlaps(start))

    def test_capture_after_release_is_accepted(self):
        child = self.child()
        child.communicate("\n", timeout=2)
        released = float(Path(self.path).read_text().split()[2])
        self.assertFalse(self.floor.floor_overlaps(released + 0.001))

    def test_crash_record_completed_and_later_capture_accepted(self):
        start = time.monotonic()
        child = self.child()
        child.send_signal(signal.SIGKILL)
        child.communicate(timeout=2)
        self.assertTrue(self.probe_free())
        self.assertTrue(self.floor.floor_overlaps(start))
        fields = Path(self.path).read_text().split()
        self.assertEqual(len(fields), 3)
        self.assertFalse(self.floor.floor_overlaps(float(fields[2]) + 0.001))

    def test_overlap_survives_us_taking_the_floor_afterwards(self):
        start = time.monotonic()
        child = self.child()
        child.communicate("\n", timeout=2)
        self.assertTrue(self.floor.hold("a"))
        self.assertTrue(self.floor.floor_overlaps(start))
        self.floor.release("a", 0)
        self.assertTrue(self.floor.floor_overlaps(start))
        self.assertFalse(self.floor.floor_overlaps(time.monotonic()))

    def test_tail_reacquire_keeps_same_lock(self):
        self.assertTrue(self.floor.hold("speaker"))
        taken = Path(self.path).read_text()
        self.floor.release("speaker", 0.15)
        self.assertTrue(self.floor.hold("speaker"))
        time.sleep(0.2)
        self.assertFalse(self.probe_free())
        self.assertEqual(Path(self.path).read_text(), taken)
        self.floor.release("speaker", 0)
        self.assertTrue(self.probe_free())

    def test_repeated_key_needs_one_release(self):
        for _ in range(3):
            self.assertTrue(self.floor.hold("a"))
        self.floor.release("a", 0)
        self.assertTrue(self.probe_free())

    def test_wait_can_be_cancelled(self):
        child = self.child()
        cancelled = threading.Event()
        done = threading.Event()
        result = []
        waiter = threading.Thread(target=lambda: (result.append(self.floor.hold("a", cancelled.is_set)), done.set()))
        waiter.start()
        self.addCleanup(waiter.join, 2)
        self.assertFalse(done.wait(0.12))
        cancelled.set()
        self.assertTrue(done.wait(2))
        self.assertEqual(result, [False])
        child.communicate("\n", timeout=2)
        self.assertTrue(self.probe_free())

    def test_waiting_speaker_does_not_block_listener(self):
        self.child()
        stop = threading.Event()
        waiter = threading.Thread(target=self.floor.hold, args=("a", stop.is_set))
        waiter.start()
        self.addCleanup(lambda: (stop.set(), waiter.join(2)))
        time.sleep(0.12)
        started = time.monotonic()
        self.assertTrue(self.floor.floor_overlaps(0.0))
        self.assertLess(time.monotonic() - started, 0.5)

    def test_cancelled_hold_keeps_pending_release(self):
        self.floor.hold("a")
        self.floor.release("a", 0.05)
        self.assertFalse(self.floor.hold("b", cancelled=lambda: True))
        time.sleep(0.1)
        self.assertTrue(self.probe_free())

    def test_new_hold_truncates_old_release_line(self):
        self.floor.hold("a")
        self.floor.release("a", 0)
        self.assertEqual(len(Path(self.path).read_text().split()), 3)
        self.floor.hold("a")
        line = Path(self.path).read_text()
        self.assertTrue(line.endswith("\n"))
        self.assertEqual(len(line.split()), 2)

    def test_descriptor_is_not_inherited(self):
        self.floor.hold("a")
        child = subprocess.run([sys.executable, "-c",
                                "import os; print('\\n'.join(os.readlink('/proc/self/fd/'+f) for f in os.listdir('/proc/self/fd') if os.path.exists('/proc/self/fd/'+f)))"],
                               capture_output=True, text=True, check=True)
        self.assertNotIn(self.path, child.stdout)


if __name__ == "__main__":
    unittest.main()
