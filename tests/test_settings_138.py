import unittest

from test_speakable import _ServerEnv


class NewSettingsTest(_ServerEnv):
    """#138 B1: look_beat and notify_speak_subject are settings (NOTIFY_FLAGS feeds both the allow-list and state_info), off by default."""

    def test_flags_are_allowed_and_default_off(self):
        for k in ("look_beat", "notify_speak_subject"):
            self.assertIn(k, self.server.NOTIFY_FLAGS)
            self.assertIs(self.server.CFG[k], False)


if __name__ == "__main__":
    unittest.main()
