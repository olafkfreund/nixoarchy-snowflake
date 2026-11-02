import json
import unittest
from unittest import mock

from test_speakable import REPO_ROOT, _ServerEnv

FIX = REPO_ROOT / "tests" / "fixtures" / "hooks"


def fx(name):
    return json.loads((FIX / f"{name}.json").read_text())


class AttentionTest(_ServerEnv):
    """#138 A2: what an agent's hook payload becomes (kind, project, reason) and how it is rate-limited."""

    def setUp(self):
        self.server._ATTN_LAST.clear()

    def parse(self, frm, hook):
        return self.server.attention_parse(frm, hook)

    def accept(self, frm, hook=None, text="", now=0):
        with mock.patch.object(self.server.BUS, "pub") as pub:
            shown = self.server.attention_accept(frm, text, now=now, hook=hook)
        return shown, (pub.call_args.kwargs if pub.called else None)

    def test_fixtures(self):
        self.assertEqual(self.parse("claude", fx("claude-permission")), ("ask", "snowflake", "Claude needs your permission to use Bash"))
        self.assertEqual(self.parse("claude", fx("claude-idle")), ("done", "snowflake", ""))
        self.assertEqual(self.parse("codex", fx("codex"))[:2], ("done", "snowflake"))
        self.assertEqual(self.parse("agy", fx("agy")), ("done", "", ""))      # no cwd until the launcher maps workspacePaths

    def test_claude_rows(self):
        for nt in ("permission_prompt", "elicitation_dialog"):
            self.assertEqual(self.parse("claude", {"notification_type": nt, "message": "m"}), ("ask", "", "m"))
        self.assertEqual(self.parse("claude", {"notification_type": "idle_prompt", "message": "m"}), ("done", "", ""))
        self.assertIsNone(self.parse("claude", {"notification_type": "auth_success"}))
        self.assertEqual(self.parse("claude", {"notification_type": "other", "message": "m"})[0], "done")
        self.assertEqual(self.parse("claude", {"message": "Claude needs your permission"})[0], "ask")
        self.assertEqual(self.parse("claude", {"message": "Claude is waiting for your input"}), ("done", "", ""))

    def test_codex_rows(self):
        self.assertEqual(self.parse("codex", {"type": "agent-turn-complete", "last-assistant-message": "ok"}), ("done", "", "ok"))
        self.assertEqual(self.parse("codex", {"type": "exec-approval-request", "title": "t", "message": "m"}), ("ask", "", "t"))
        self.assertEqual(self.parse("codex", {"type": "apply-patch-approval", "message": "m"}), ("ask", "", "m"))
        self.assertIsNone(self.parse("codex", {"type": "something-else"}))

    def test_agy_rows(self):
        self.assertEqual(self.parse("agy", {"hook_event_name": "Notification", "message": "m", "cwd": "/x/y"}), ("ask", "y", "m"))
        self.assertIsNone(self.parse("agy", {"fullyIdle": False}))
        self.assertEqual(self.parse("agy", {"fullyIdle": True, "error": "boom"}), ("done", "", "boom"))
        self.assertEqual(self.parse("agy", {}), ("done", "", ""))

    def test_project_is_sanitised(self):
        self.assertEqual(self.parse("claude", {"notification_type": "idle_prompt", "cwd": "/a/b c;rm"})[1], "")
        self.assertEqual(self.parse("claude", {"notification_type": "idle_prompt", "cwd": "/a/b.c/"})[1], "b.c")
        self.assertEqual(self.parse("claude", {"notification_type": "idle_prompt", "cwd": "/a/" + "x" * 41})[1], "")
        self.assertEqual(self.parse("claude", {"notification_type": "idle_prompt", "cwd": 5})[1], "")

    def test_reason_first_line_only_and_capped(self):
        _, kw = self.accept("codex", fx("codex"))
        self.assertEqual(kw["text"], "All 42 tests pass.")
        _, kw = self.accept("claude", {"notification_type": "permission_prompt", "message": "\n\n  a   b \nc"}, now=100)
        self.assertEqual(kw["text"], "a b")
        _, kw = self.accept("claude", {"notification_type": "permission_prompt", "message": "word " * 40}, now=200)
        self.assertEqual(len(kw["text"]), 90)

    def test_secret_reason_is_cleared(self):
        shown, kw = self.accept("claude", {"notification_type": "permission_prompt", "message": "set password=hunter2"})
        self.assertTrue(shown)
        self.assertEqual(kw["text"], "")

    def test_secret_straddling_the_cut_is_scrubbed(self):
        msg = "note " * 14 + "ghp_" + "a1B2" * 9                    # the token starts at 70 and ends past 90
        _, kw = self.accept("claude", {"notification_type": "permission_prompt", "message": msg})
        self.assertEqual(kw["text"], "")

    def test_other_agents(self):
        self.assertEqual(self.parse("newagent", {"message": "m", "cwd": "/x/y"}), ("ask", "y", "m"))
        self.assertEqual(self.parse("newagent", {"title": "t"}), ("ask", "", "t"))
        self.assertIsNone(self.parse("newagent", {"cwd": "/x/y"}))

    def test_published_fields(self):
        _, kw = self.accept("claude", fx("claude-permission"))
        self.assertEqual((kw["t"], kw["from"], kw["name"], kw["kind"], kw["project"]), ("attention", "claude", "Claude", "ask", "snowflake"))

    def test_rate_limit_is_per_kind(self):
        self.assertTrue(self.accept("claude", fx("claude-idle"), now=0)[0])
        self.assertTrue(self.accept("claude", fx("claude-permission"), now=5)[0])     # ask after done is shown
        self.assertFalse(self.accept("claude", fx("claude-idle"), now=10)[0])         # a second done is not
        self.assertFalse(self.accept("claude", fx("claude-permission"), now=20)[0])
        self.assertTrue(self.accept("claude", fx("claude-idle"), now=31)[0])
        self.assertTrue(self.accept("codex", fx("codex"), now=32)[0])                 # another agent has its own slot

    def test_quiet_events_publish_nothing(self):
        shown, kw = self.accept("claude", {"notification_type": "auth_success"})
        self.assertFalse(shown)
        self.assertIsNone(kw)

    def test_malformed_hook_takes_the_legacy_path(self):
        for bad in ([1, 2], None, "x"):
            self.setUp()
            shown, kw = self.accept("claude", bad, text="build  failed")
            self.assertTrue(shown)
            self.assertEqual((kw["kind"], kw["project"], kw["text"]), ("ask", "", "build failed"))

    def test_legacy_default_words_are_blank(self):
        _, kw = self.accept("claude", None, text="is waiting for you")
        self.assertEqual((kw["kind"], kw["text"]), ("ask", ""))


if __name__ == "__main__":
    unittest.main()
