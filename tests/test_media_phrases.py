"""#208 step 4: the six media phrases reach the player before his quick memory can answer them."""
import json
import unittest
from unittest import mock

from test_speakable import _ServerEnv

PHRASES = ["pause", "play", "next song", "quieter", "louder", "what's playing"]


class MediaPhrasesTest(_ServerEnv):
    def post(self, text):
        s = self.server
        h = s.Handler.__new__(s.Handler)
        h.path, h.headers = "/api/quick", {"Host": "127.0.0.1", "X-Nixi-Token": s.TOKEN}
        h._body = lambda: json.dumps({"text": text}).encode()
        h._json = mock.Mock()
        h.do_POST()
        return h._json.call_args[0][0]

    def run_post(self, text):
        s = self.server
        with mock.patch.object(s.quick.shutil, "which", return_value="/bin/x"), mock.patch.object(s.quick, "_run", return_value=(True, "Song by Band")) as run, \
                mock.patch.object(s.quick, "_volume_pct", return_value=(50, None)), mock.patch.object(s.recall, "answer", return_value="MEMORY ANSWER"), \
                mock.patch.object(s, "state_info", return_value={}):
            return self.post(text), run

    def test_each_phrase_runs_the_player_not_the_memory(self):
        for phrase in PHRASES + ["  Pause ", "NEXT SONG"]:
            with self.subTest(phrase):
                j, run = self.run_post(phrase)
                self.assertTrue(run.called, "the media command did not run")
                self.assertNotEqual(j.get("say"), "MEMORY ANSWER")
                self.assertTrue(j["handled"])

    def test_other_phrases_still_get_the_memory(self):
        j, run = self.run_post("what time is it")
        self.assertEqual(j["say"], "MEMORY ANSWER")
        self.assertFalse(run.called)

    def test_next_song_is_not_the_stages(self):
        s = self.server
        s.STAGES.put({"v": 1, "kind": "commands", "items": [{"label": "a", "cmd": "ls -l"}, {"label": "b", "cmd": "ls"}]})
        self.addCleanup(s.STAGES.close)
        fp = s.stages.fast_path("next song", s.STAGES.current())
        self.assertFalse(fp and fp[0] in ("close", "back", "show"))


if __name__ == "__main__":
    unittest.main()
