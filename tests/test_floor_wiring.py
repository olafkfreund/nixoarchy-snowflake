"""#1568 step 5: the shared voice floor is wired into Speaker, Wake, /api/tts + /api/floor and the page."""
import fcntl
import io
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import wave
from pathlib import Path
from unittest import mock

from test_speakable import _ServerEnv

APP = Path(__file__).resolve().parent.parent / "app"
CHILD = """import sys
from floor import Floor
floor = Floor()
floor.hold('other')
print('ready', flush=True)
sys.stdin.readline()
floor.release('other', 0)
"""


class FakePlayer:
    def __init__(self, fail=False):
        self.stdin = mock.Mock()
        if fail:
            self.stdin.write.side_effect = BrokenPipeError
        self.stdin.flush = mock.Mock()

    def poll(self):
        return None

    def kill(self):
        pass


class SpyFloor:
    """Wraps a Floor and records what hold() returned."""
    def __init__(self, floor):
        self.floor, self.holds = floor, []

    def hold(self, key, cancelled=None):
        r = self.floor.hold(key, cancelled)
        self.holds.append(r)
        return r

    def __getattr__(self, name):
        return getattr(self.floor, name)


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


class _Base(_ServerEnv):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.loop = threading.Thread(target=cls.server.Speaker._player_loop, daemon=True)   # one loop for the class

    def setUp(self):
        s = self.server
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = str(Path(self.dir.name) / "nixarchy-voice-floor.lock")
        from floor import Floor
        self.real = Floor(self.path)
        self.spy = SpyFloor(self.real)
        p = mock.patch.object(s, "FLOOR", self.spy)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.real.drop)
        self.env = {**os.environ, "XDG_RUNTIME_DIR": self.dir.name, "PYTHONPATH": str(APP)}
        self.events = []
        p = mock.patch.object(s.BUS, "pub", side_effect=lambda **kw: self.events.append(kw))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.server.CFG.__setitem__, "follow_up", self.server.CFG.get("follow_up"))
        s.CFG["follow_up"] = 0

    def probe_free(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except BlockingIOError:
                return False
        finally:
            os.close(fd)

    def child(self):
        child = subprocess.Popen([sys.executable, "-u", "-c", CHILD], env=self.env, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: (child.kill() if child.poll() is None else None, child.communicate()))
        self.assertEqual(child.stdout.readline().strip(), "ready")
        return child


class SpeakerFloorTest(_Base):
    def setUp(self):
        super().setUp()
        S = self.server.Speaker
        S.stop()
        S.proc = None
        S.prate, S.written, S.t0, S.filled = None, 0, 0.0, False
        p = mock.patch.object(self.server, "make_player", lambda rate: FakePlayer())
        p.start()
        self.addCleanup(p.stop)
        if not self.loop.is_alive():
            self.loop.start()
        self.addCleanup(S.stop)

    def push(self, sid, secs=0.1, text="Hello there."):
        S = self.server.Speaker
        with S.cv:
            S.ready.append((S.gen, sid, text, b"\0\0" * int(22050 * secs), 22050, None, [], 1.0, True))
            S.cv.notify_all()

    def test_cut_off_while_waiting_leaves_floor_free(self):
        child = self.child()
        self.push(1)
        self.assertTrue(wait_for(lambda: not self.server.Speaker.ready))      # the loop took it and is waiting
        self.server.Speaker.stop()
        self.assertTrue(wait_for(lambda: self.spy.holds == [False], 1.0), "the wait was not cancelled")
        child.communicate("\n", timeout=2)
        self.assertTrue(wait_for(self.probe_free, 1.0))
        self.assertNotIn(str(os.getpid()), Path(self.path).read_text())

    def test_cut_off_while_playing_frees_floor(self):
        self.push(1, secs=5)                                  # long enough to still be streaming
        self.assertTrue(wait_for(lambda: not self.probe_free()))
        self.server.Speaker.stop()
        self.assertTrue(self.probe_free())

    def test_failed_write_frees_floor(self):
        with mock.patch.object(self.server, "make_player", lambda rate: FakePlayer(fail=True)):
            self.push(1)
            self.assertTrue(wait_for(lambda: self.spy.holds == [True]))
            self.assertTrue(wait_for(self.probe_free, 1.0), "floor kept after the write failed")

    def test_player_exception_frees_floor(self):
        def boom(rate):
            raise OSError("no player")
        with mock.patch.object(self.server, "make_player", boom):
            self.push(1)
            self.assertTrue(wait_for(lambda: any(e.get("t") == "spk_skip" for e in self.events)))
            self.assertTrue(wait_for(self.probe_free, 1.0), "floor kept after the player failed")

    def test_reply_with_underrun_holds_once(self):
        self.server.CFG["follow_up"] = 4
        self.push(1)
        self.assertTrue(wait_for(lambda: any(e.get("t") == "spk_done" for e in self.events)))
        first = Path(self.path).read_text()
        self.events.clear()
        self.push(2)                                           # the next sentence arrives after the speakers ran dry
        self.assertTrue(wait_for(lambda: any(e.get("t") == "spk_done" for e in self.events)))
        self.assertFalse(self.probe_free())
        self.assertEqual(Path(self.path).read_text(), first)   # same hold: the lock was never dropped
        self.assertEqual(self.spy.holds, [True, True])


class WakeFloorTest(_Base):
    def setUp(self):
        super().setUp()
        s = self.server
        s.Speaker.stop()
        s.Wake.hush()
        for obj, name, val in ((s.CFG, "wake_word", True),):
            old = obj.get(name)
            self.addCleanup(obj.__setitem__, name, old)
            obj[name] = val
        self.addCleanup(setattr, s.Wake, "asleep", s.Wake.asleep)
        s.Wake.asleep = False

    def test_capture_spanning_other_hold_is_dropped_before_learning(self):
        s = self.server
        started = time.monotonic()
        child = self.child()
        with mock.patch.object(s.MicAuto, "learn") as learn, mock.patch.object(s, "speech_seconds", return_value=0):
            s.Wake.check(b"\0" * 64000, started)
            learn.assert_not_called()
        child.communicate("\n", timeout=2)

    def test_should_not_run_while_other_holds_floor(self):
        s = self.server
        self.assertTrue(s.Wake.should_run())
        child = self.child()
        self.assertFalse(s.Wake.should_run())
        child.communicate("\n", timeout=2)


class PageFloorTest(_Base):
    def make(self, t):
        pf = self.server.PageFloor(floor=self.real, clock=lambda: t[0], tail=lambda: 4)
        self.addCleanup(pf.release, 0)
        return pf

    def test_vanished_page_releases_at_clips_plus_tail_including_prefetched(self):
        t = [100.0]
        pf = self.make(t)
        pf.served(5.0)                      # prefetched before the page's first hold
        pf.hold()
        pf.served(3.0)
        t[0] = 111.9                        # 100 + 5 + 3 + 4 = 112
        pf.check()
        self.assertFalse(self.probe_free())
        t[0] = 112.0
        pf.check()
        self.assertTrue(self.probe_free())

    def test_the_fallback_clock_starts_once_the_floor_is_ours(self):
        # Waiting for the other voice must not spend the page's deadline (#1568, review).
        t = [100.0]
        pf = self.make(t)
        real_hold = pf.floor.hold if pf.floor else None

        def slow_hold(key, cancelled=None):
            t[0] += 30.0                    # the other voice spoke for 30 s
            return real_hold(key, cancelled)
        pf.floor.hold = slow_hold
        pf.served(2.0)
        pf.hold()
        self.assertEqual(pf.first, 130.0)
        t[0] = 135.9                        # 130 + 2 + 4 = 136
        pf.check()
        self.assertFalse(self.probe_free())

    def test_a_clip_served_while_waiting_does_not_cancel_the_wait(self):
        # #25 review: served() during the wait armed a 50 ms deadline that cancelled it.
        t = [100.0]
        pf = self.make(t)
        real_hold = pf.floor.hold

        def busy_hold(key, cancelled=None):
            pf.served(2.0)                  # /api/tts finished while Oma still spoke
            time.sleep(0.15)                # longer than the 50 ms the old code armed
            t[0] += 10.0
            return real_hold(key, cancelled)
        pf.floor.hold = busy_hold
        pf.hold()
        self.assertTrue(pf.acquired)
        self.assertFalse(self.probe_free())

    def test_no_clip_yet_keeps_the_floor_through_synthesis(self):
        # #25 review: with no clip served, the deadline was first + 0 + tail.
        t = [100.0]
        pf = self.make(t)
        pf.hold()
        t[0] = 110.0                        # past first + tail, synthesis still running
        pf.check()
        self.assertFalse(self.probe_free())
        pf.served(2.0)                      # the clip arrives at 110 and plays to 112
        t[0] = 115.9                        # max(100+2, 112) + 4 = 116
        pf.check()
        self.assertFalse(self.probe_free())
        t[0] = 116.0
        pf.check()
        self.assertTrue(self.probe_free())

    def test_page_release_uses_the_tail(self):
        pf = self.make([0.0])
        pf.hold()
        pf.release()
        self.assertFalse(self.probe_free())  # held for the tail
        self.real.drop()

    def test_http_route_holds_and_releases_and_tts_counts_clips(self):
        s = self.server
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(22050)
            w.writeframes(b"\0\0" * 22050)                  # 1 s
        pf = s.PageFloor(floor=self.real, clock=time.monotonic, tail=lambda: 0)
        self.addCleanup(pf.release, 0)
        srv = s.ThreadingHTTPServer(("127.0.0.1", 0), s.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)

        def post(path, body):
            req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}{path}", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json", "X-Nixi-Token": s.TOKEN})
            return urllib.request.urlopen(req, timeout=5).read()
        with mock.patch.object(s, "PAGE_FLOOR", pf), mock.patch.object(s, "tts_engine", return_value="x"), \
                mock.patch.object(s, "synth", return_value=(buf.getvalue(), 2.0)), \
                mock.patch.object(s, "tidy_and_time", return_value=(buf.getvalue(), None)):
            post("/api/tts", {"text": "Hello there."})
            self.assertAlmostEqual(pf.clips, 1 / 2.0 + 0.3, places=2)     # duration / playback rate + pause
            post("/api/floor", {"hold": True})
            self.assertTrue(wait_for(lambda: not self.probe_free()))
            post("/api/floor", {"hold": False})
            self.assertTrue(self.probe_free())


class PageSourceTest(unittest.TestCase):
    """A source check, NOT a behaviour test: the repo runs no browser. Real behaviour: plan step 9, voice_out=page."""

    def test_pump_and_drain_post_the_floor(self):
        html = (APP / "static" / "index.html").read_text()
        self.assertRegex(html, r"post\('/api/floor',\{hold:on\}\)")
        pump = html[html.index("async function pump()"):html.index("function quietNative")]
        self.assertIn("await floorPage(true)", pump)
        self.assertIn("floorPage(false)", html[html.index("function quietCheck"):html.index("// shush")])
        self.assertIn("floorPage(false)", html[html.index("function shush"):html.index("const untilQuiet")])


class PlayerDeathTest(_Base):
    def test_player_dies_with_its_parent(self):
        script = (
            "import sys, os, threading, time\n"
            f"sys.path.insert(0, {str(APP)!r})\n"
            "import server\n"
            "server.audio_player_cmd = lambda rate: ['sleep', '30']\n"
            # Spawned from a thread that stays alive, like _player_loop: pdeathsig fires when the
            # spawning THREAD exits, so a thread that returned would kill the player on its own.
            "def worker():\n"
            "    print(server.make_player(22050).pid, flush=True)\n"
            "    time.sleep(60)\n"
            "threading.Thread(target=worker, daemon=True).start()\n"
            "time.sleep(60)\n")
        env = {**self.env, "HOME": self.dir.name, "XDG_CONFIG_HOME": self.dir.name, "XDG_DATA_HOME": self.dir.name,
               "XDG_STATE_HOME": self.dir.name}
        parent = subprocess.Popen([sys.executable, "-c", script], env=env, stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: (parent.kill() if parent.poll() is None else None, parent.communicate()))
        pid = int(parent.stdout.readline())
        time.sleep(0.3)
        self.assertTrue(Path(f"/proc/{pid}").exists(), "the player died before its parent did")
        parent.send_signal(signal.SIGKILL)
        parent.wait()
        self.assertTrue(wait_for(lambda: not Path(f"/proc/{pid}").exists() or
                                 Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z", 3.0), "the player outlived its parent")


if __name__ == "__main__":
    unittest.main()
