"""Mic selection and silence notices, without accessing the host audio stack."""

import itertools
import json
import struct
from unittest import mock

from test_speakable import _ServerEnv


class MicChoiceTest(_ServerEnv):
    def setUp(self):
        s = self.server
        self.events = []
        for target, name, value in (
            (s.BUS, "pub", lambda **event: self.events.append(event)),
            (s.shutil, "which", lambda name: name if name in {"pactl", "parecord", "pw-record", "arecord"} else None),
            (s.subprocess, "run", self.pactl),
        ):
            patch = mock.patch.object(target, name, side_effect=value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(s.subprocess, "Popen", side_effect=AssertionError("real recorder attempted"))
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(s.CFG.__setitem__, "mic_device", s.CFG.get("mic_device"))
        self.addCleanup(s.CFG.__setitem__, "mic_cmd", s.CFG.get("mic_cmd"))
        for name in ("MIC_TARGET", "_MIC_NOTE_LAST", "_MIC_NOTE_CHOICE"):
            self.addCleanup(setattr, s, name, getattr(s, name))
        s.CFG["mic_device"], s.CFG["mic_cmd"] = "chosen", ""
        s.MIC_TARGET, s._MIC_NOTE_LAST, s._MIC_NOTE_CHOICE = "", None, None
        self.mics = [{"name": "other", "description": "Other mic"}]

    def pactl(self, cmd, **kwargs):
        self.assertEqual(cmd, ["pactl", "-f", "json", "list", "sources"])
        return mock.Mock(stdout=json.dumps(self.mics))

    def notes(self):
        return [e["text"] for e in self.events if e.get("t") == "note"]

    def test_missing_device_uses_default_on_all_recorders_and_notes_once(self):
        s = self.server
        for _ in range(2):
            cmds = s.mic_cmds()
            self.assertEqual([c[0] for c in cmds], ["parecord", "pw-record", "arecord"])
            self.assertFalse(any("chosen" in arg for cmd in cmds for arg in cmd))
            self.assertEqual(s.MIC_TARGET, "")
        self.assertEqual(self.notes(), ["The mic you chose (chosen) is gone. I'm using the default mic, so I may hear your speakers."])

    def test_present_device_is_kept_and_resets_missing_notice(self):
        s = self.server
        s.mic_cmds()
        self.mics.append({"name": "chosen"})
        cmds = s.mic_cmds()
        self.assertIn("--device=chosen", cmds[0])
        self.assertEqual(cmds[1][-3:-1], ["--target", "chosen"])
        self.assertEqual(cmds[2][-2:], ["-D", "chosen"])
        self.assertEqual(s.MIC_TARGET, "chosen")
        self.mics.pop()
        s.mic_cmds()
        self.assertEqual(len(self.notes()), 2)

    def test_silent_note_is_not_repeated_by_each_new_session(self):
        s = self.server
        self.mics.append({"name": "chosen"})
        for _ in range(2):
            s.mic_cmds()
            s._mic_note("The mic you chose (chosen) sends no sound.")
        self.assertEqual(self.notes(), ["The mic you chose (chosen) sends no sound."])

    def test_empty_list_keeps_device_and_change_resets_notice(self):
        s = self.server
        s.mic_cmds()
        self.mics.clear()
        self.assertIn("--device=chosen", s.mic_cmds()[0])
        self.assertEqual(s.MIC_TARGET, "chosen")
        s.CFG["mic_device"] = "new"
        self.mics.append({"name": "other"})
        s.mic_cmds()
        self.assertIn("(new)", self.notes()[-1])

    def test_no_pactl_keeps_device(self):
        s = self.server
        with mock.patch.object(s.shutil, "which", side_effect=lambda name: None if name == "pactl" else name):
            cmds = s.mic_cmds()
        self.assertIn("--device=chosen", cmds[0])
        self.assertEqual(s.MIC_TARGET, "chosen")
        self.assertEqual(self.notes(), [])

    def run_frames(self, frames):
        s = self.server
        mic = mock.Mock()
        mic.read.return_value = b""
        with mock.patch.object(s, "open_mic", return_value=(mic, "fake", frames)), \
             mock.patch.object(s.Wake, "should_run", side_effect=itertools.chain([True], itertools.repeat(False))), \
             mock.patch.object(s.Wake, "speaking", return_value=False), \
             mock.patch.object(s.Wake, "window_open", return_value=False):
            s.Wake.session()
        mic.close.assert_called_once()

    def test_default_fallback_zero_frames_do_not_blame_chosen_mic(self):
        s = self.server
        s.mic_cmds()
        self.run_frames(bytes(s.FRAME * (10 * s.RATE * 2 // s.FRAME + 1)))
        self.assertFalse(any("sends no sound" in note for note in self.notes()))

    def test_zero_frames_note_once_at_ten_seconds_but_near_silence_does_not(self):
        s = self.server
        self.mics.append({"name": "chosen"})
        s.mic_cmds()
        limit = 10 * s.RATE * 2 // s.FRAME
        self.run_frames(bytes(s.FRAME * (limit - 1)))
        self.assertEqual(self.notes(), [])
        self.run_frames(bytes(s.FRAME * (limit + 3)))
        self.assertEqual(self.notes(), ["The mic you chose (chosen) sends no sound."])
        self.events.clear()
        self.run_frames(struct.pack("h", 1) * (s.FRAME // 2) * limit)
        self.run_frames(struct.pack("h", -1) * (s.FRAME // 2) * limit)
        self.assertEqual(self.notes(), [])

    def test_custom_command_skips_zero_check(self):
        s = self.server
        self.mics.append({"name": "chosen"})
        s.CFG["mic_cmd"] = "custom-recorder"
        s.mic_cmds()
        self.run_frames(bytes(s.FRAME * (10 * s.RATE * 2 // s.FRAME)))
        self.assertEqual(self.notes(), [])

    def test_loop_notes_each_new_open_error_once(self):
        s = self.server
        with mock.patch.object(s.Wake, "wanted", side_effect=[True, True, True, False]), \
             mock.patch.object(s.Wake, "should_run", return_value=True), \
             mock.patch.object(s.Wake, "session", side_effect=[RuntimeError("first"), RuntimeError("first"), RuntimeError("second")]), \
             mock.patch.object(s.time, "sleep"):
            s.Wake.loop()
        self.assertEqual(self.notes(), ["I can't open the mic: first", "I can't open the mic: second"])

    def test_state_and_doctor_skip_the_check(self):
        s = self.server
        with mock.patch.object(s.subprocess, "run", side_effect=AssertionError("pactl run for state")):
            cmds = s.mic_cmds(check=False)
        self.assertIn("--device=chosen", cmds[0])
        self.assertEqual((s.MIC_TARGET, self.notes()), ("", []))

    def test_alsa_name_is_not_checked_against_pulse(self):
        s = self.server
        s.CFG["mic_device"] = "hw:1,0"
        cmds = s.mic_cmds()
        self.assertEqual(cmds[2][-2:], ["-D", "hw:1,0"])
        self.assertEqual(s.MIC_TARGET, "hw:1,0")
        self.assertEqual(self.notes(), [])

    def test_list_mics_times_out_to_empty(self):
        s = self.server
        with mock.patch.object(s.subprocess, "run", side_effect=s.subprocess.TimeoutExpired("pactl", 3)):
            self.assertEqual(s.list_mics(), [])
