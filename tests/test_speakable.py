import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent


class _ServerEnv(unittest.TestCase):
    """Imports server.py under a throwaway HOME."""

    @classmethod
    def setUpClass(cls):
        cls._orig_env = os.environ.copy()
        cls.tmp = tempfile.mkdtemp(prefix="nixi-speak-test-")
        for k, d in (("HOME", ""), ("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
            os.environ[k] = os.path.join(cls.tmp, d)
            os.makedirs(os.environ[k], exist_ok=True)
        sys.path.insert(0, str(REPO_ROOT / "app"))
        import server
        cls.server = server

    @classmethod
    def tearDownClass(cls):
        os.environ.clear()
        os.environ.update(cls._orig_env)
        shutil.rmtree(cls.tmp, ignore_errors=True)


class SpeakableTest(_ServerEnv):
    """S24 + #144: a command is pointed at only while a board shows it, else it is read out; single words always are."""

    def test_inline_command_is_pointed_at_on_a_board(self):
        said = self.server.speakable("Run `nixarchy pkg add firefox` then `nixarchy apply`.", board=True)
        self.assertIn("the command on the board", said)
        self.assertNotIn("pkg add", said)
        self.assertNotIn("apply", said)

    def test_inline_command_is_read_out_without_a_board(self):
        for said in (self.server.speakable("Run `nixarchy pkg add firefox`."), self.server.speakable("Run `nixarchy pkg add firefox`.", board=False)):
            self.assertEqual(said, "Run nixarchy pkg add firefox.")

    def test_board_up_follows_the_store(self):
        s = self.server
        s.STAGES.close()
        self.assertFalse(s.board_up())
        s.STAGES.put({"v": 1, "kind": "facts", "title": "t", "points": ["p"]})
        self.assertFalse(s.board_up())
        s.STAGES.put({"v": 1, "kind": "commands", "items": [{"label": "a", "cmd": "ls -l"}]})
        self.assertTrue(s.board_up())
        s.STAGES.close()

    def test_single_word_is_still_spoken(self):
        self.assertEqual(self.server.speakable("`btop` is already installed."), "btop is already installed.")

    def test_key_combo_is_still_spoken(self):
        self.assertEqual(self.server.speakable("Press `Super + Space` to open the launcher."), "Press Super + Space to open the launcher.")

    def test_fenced_block_unchanged(self):
        said = self.server.speakable("Like this:\n```\nnixarchy pkg add firefox\n```")
        self.assertIn("I put some code on screen", said)
        self.assertNotIn("pkg add", said)


class ThemeTreeTest(_ServerEnv):
    """S25: the theme hook's omarchy tree finds a theme the server's own (older) tree lacks."""

    def test_hook_tree_is_used(self):
        tree = Path(self.tmp) / "tree"
        (tree / "themes" / "test-jade").mkdir(parents=True)
        keys = self.server.THEME_KEYS
        (tree / "themes" / "test-jade" / "colors.toml").write_text("".join(f'{k} = "#509475"\n' for k in keys))

        def run(cmd, **kw):   # the server's own (old) tree lacks the theme
            return mock.Mock(stdout="Test Jade\n" if cmd[2] == "current" else "/old-tree/themes/test-jade\n")

        with mock.patch.object(self.server.subprocess, "run", side_effect=run):
            self.assertIsNone(self.server.theme_colors())
            self.assertIsNone(self.server.theme_colors("/no/such/tree"))
            self.assertEqual(self.server.theme_colors(str(tree))["accent"], "#509475")




class BridgeQuestionTest(_ServerEnv):
    """S26: nixi mode asks with the tool's own description, else the title."""

    def test_summary_is_the_question(self):
        q = self.server.bridge_question("seq 1 12; sleep 1", "Print twelve numbered test lines, one per second")
        self.assertEqual(q, "Can I print twelve numbered test lines, one per second?")

    def test_title_when_no_summary(self):
        for s in (None, "", "  "):
            self.assertEqual(self.server.bridge_question("ls -la", s), "ls -la")


if __name__ == "__main__":
    unittest.main()
