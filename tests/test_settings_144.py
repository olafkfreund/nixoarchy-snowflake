import unittest
from unittest import mock

from test_speakable import _ServerEnv


class AnswerStagesSettingTest(_ServerEnv):
    """#144: Answer stages is a setting, on by default, and it reaches the page's state."""

    def setUp(self):
        p = mock.patch.object(self.server.quick, "projects", return_value={})     # (state_info reads the quick config)
        p.start()
        self.addCleanup(p.stop)

    def test_default_on_and_in_state(self):
        s = self.server
        self.assertIs(s.DEFAULTS["answer_stages"], True)
        self.assertIs(s.state_info()["answer_stages"], True)

    def test_off_reaches_state_and_page_has_the_toggle(self):
        s = self.server
        s.CFG["answer_stages"] = False
        try:
            self.assertIs(s.state_info()["answer_stages"], False)
        finally:
            s.CFG["answer_stages"] = True
        html = (s.Path(s.__file__).parent / "static" / "index.html").read_text()
        for needle in ('id="stagesSw"', "stagesSw:info.answer_stages!==false", "setSetting({answer_stages:on})"):
            self.assertIn(needle, html)


if __name__ == "__main__":
    unittest.main()
