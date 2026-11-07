import json
import unittest
from unittest import mock

from test_speakable import _ServerEnv


def inp(sink=1, corked=False, mute=False, app="firefox"):
    return {"sink": sink, "corked": corked, "mute": mute, "properties": {"application.name": app}}


SINKS = json.dumps([{"index": 1, "mute": False}, {"index": 2, "mute": True}])


class MediaPlayingTest(_ServerEnv):
    """#216: media_playing() from stubbed pactl output; never runs the real one."""

    def play(self, inputs, sinks=SINKS, which="/usr/bin/pactl"):
        S = self.server
        outs = [inputs if isinstance(inputs, str) or inputs is None else json.dumps(inputs), sinks]
        with mock.patch.object(S.shutil, "which", return_value=which), mock.patch.object(S.Ambient, "run", side_effect=outs) as run:
            self.result = S.media_playing()
            self.calls = run.call_args_list
        return self.result

    def test_none_playing_is_one_call(self):
        self.assertIs(self.play([]), False)
        self.assertEqual(len(self.calls), 1)

    def test_corked_muted_and_nixi_are_false(self):
        for i in (inp(corked=True), inp(mute=True), inp(app="Nixi")):
            self.assertIs(self.play([i]), False)
            self.assertEqual(len(self.calls), 1)

    def test_muted_sink_is_false(self):
        self.assertIs(self.play([inp(sink=2)]), False)

    def test_browser_is_true_even_beside_nixi(self):
        self.assertIs(self.play([inp(app="Nixi"), inp()]), True)

    def test_bad_json_is_unknown(self):
        self.assertIsNone(self.play("{nope"))
        self.assertIsNone(self.play(None))

    def test_sinks_call_failing_or_bad_is_unknown(self):
        self.assertIsNone(self.play([inp()], sinks=None))
        self.assertIsNone(self.play([inp()], sinks="{nope"))

    def test_no_pactl_is_unknown(self):
        self.assertIsNone(self.play([inp()], which=None))
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
