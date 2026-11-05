from unittest import mock

from test_speakable import _ServerEnv


class LookCharacterTest(_ServerEnv):
    """#178: look() keeps one of the four character ids, defaults to snowflake and drops anything else."""

    def character(self, **look):
        with mock.patch.dict(self.server.CFG, {"look": look}):
            return self.server.look()["character"]

    def test_each_value_kept(self):
        for c in ("snowflake", "terminal", "robot", "devil"):
            self.assertEqual(self.character(character=c), c)

    def test_unknown_dropped(self):
        self.assertEqual(self.character(character="plug:x"), "snowflake")

    def test_non_string_dropped(self):
        for v in (None, 1, ["robot"], {"a": 1}, True):
            self.assertEqual(self.character(character=v), "snowflake")

    def test_default(self):
        self.assertEqual(self.character(), "snowflake")


if __name__ == "__main__":
    import unittest
    unittest.main()
