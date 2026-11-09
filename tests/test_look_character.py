import shutil
from unittest import mock

from test_plugin_character import CharEnv


class LookCharacterTest(CharEnv):
    """#178: look() keeps one of the four character ids, defaults to snowflake and drops anything else."""

    def character(self, **look):
        with mock.patch.dict(self.server.CFG, {"look": look}):
            return self.server.look()["character"]

    def test_each_value_kept(self):
        for c in ("snowflake", "terminal", "robot", "devil"):
            self.assertEqual(self.character(character=c), c)

    def test_unknown_dropped(self):
        self.assertEqual(self.character(character="plug:x"), "snowflake")

    def test_plugin_character_kept_while_loaded(self):
        d = self.make()
        self.assertEqual(self.character(character="plug:dots"), "plug:dots")
        self.state.set("dots", False)                      # off
        self.server.Plug.reload()
        self.assertEqual(self.character(character="plug:dots"), "snowflake")
        self.state.set("dots", True)
        (d / "front.svg").write_text("<svg><script/></svg>")   # art breaks
        self.server.Plug.reload()
        self.assertEqual(self.character(character="plug:dots"), "snowflake")
        shutil.rmtree(d)                                   # deleted
        self.server.Plug.reload()
        self.assertEqual(self.character(character="plug:dots"), "snowflake")

    def test_non_string_dropped(self):
        for v in (None, 1, ["robot"], {"a": 1}, True):
            self.assertEqual(self.character(character=v), "snowflake")

    def test_default(self):
        self.assertEqual(self.character(), "snowflake")


if __name__ == "__main__":
    import unittest
    unittest.main()
