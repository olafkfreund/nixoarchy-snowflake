import datetime
import os
import unittest
from pathlib import Path
from unittest import mock

from test_speakable import _ServerEnv


class SituationTest(_ServerEnv):
    """#133: Meeting Mode's flag and a calendar item a minute away put him in a meeting; a meeting pauses the wake word."""

    def setUp(self):
        S = self.server
        saved = dict(S.CFG)
        self.addCleanup(lambda: (S.CFG.clear(), S.CFG.update(saved)))
        S.CFG.update(ambient_calendar=False, look_music=False)
        env = mock.patch.dict(os.environ, {"XDG_STATE_HOME": os.path.join(self.tmp, "sit-state")})
        env.start()
        self.addCleanup(env.stop)
        ev = mock.patch.object(S.Ambient, "events", [])
        ev.start()
        self.addCleanup(ev.stop)
        S.Ambient.meeting = S.Ambient.music = False
        self.addCleanup(lambda: setattr(S.Ambient, "meeting", False))

    def flag(self, on):
        f = Path(os.environ["XDG_STATE_HOME"]) / "meeting-mode" / "active"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.unlink(missing_ok=True)
        if on:
            f.touch()

    def test_flag_file_means_meeting(self):
        A = self.server.Ambient
        self.flag(False)
        A.sense()
        self.assertFalse(A.meeting)
        self.flag(True)
        A.sense()
        self.assertTrue(A.meeting)
        self.flag(False)
        A.sense()
        self.assertFalse(A.meeting)

    def test_calendar_item_a_minute_away(self):
        S = self.server
        now = datetime.datetime.now().astimezone()
        self.flag(False)
        with mock.patch.object(S.Ambient, "events", [(now + datetime.timedelta(seconds=45), "standup", "e1")]):
            S.Ambient.sense(now)
            self.assertFalse(S.Ambient.meeting)           # calendar cues are off
            S.CFG["ambient_calendar"] = True
            S.Ambient.sense(now)
            self.assertTrue(S.Ambient.meeting)
        with mock.patch.object(S.Ambient, "events", [(now + datetime.timedelta(minutes=5), "later", "e2")]):
            S.Ambient.sense(now)
            self.assertFalse(S.Ambient.meeting)

    def test_wake_word_pauses_in_a_meeting(self):
        S = self.server
        S.CFG["wake_word"] = True
        with mock.patch.object(S.Wake, "asleep", False), mock.patch.object(S.Wake, "speaking", return_value=False):
            S.Ambient.meeting = False
            self.assertTrue(S.Wake.should_run())
            S.Ambient.meeting = True
            self.assertFalse(S.Wake.should_run())


if __name__ == "__main__":
    unittest.main()
