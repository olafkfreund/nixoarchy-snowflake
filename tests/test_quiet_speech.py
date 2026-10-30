import time
import unittest

from test_speakable import _ServerEnv


class QuietSpeechTest(_ServerEnv):
    """#133: speech said unasked must not open the follow-up window."""

    def setUp(self):
        self.addCleanup(self.server.CFG.__setitem__, "follow_up", self.server.CFG.get("follow_up"))
        self.server.CFG["follow_up"] = 4
        self.addCleanup(self.server.Wake.hush)

    def test_unasked_speech_opens_no_window(self):
        W, t = self.server.Wake, time.monotonic() + 5
        W.talking_until(t, follow=False)
        self.assertEqual(W.follow_until, 0)
        self.assertTrue(W.speaking())

    def test_reply_still_opens_the_window(self):
        W, t = self.server.Wake, time.monotonic() + 5
        W.talking_until(t)
        self.assertGreater(W.follow_until, t)


if __name__ == "__main__":
    unittest.main()
