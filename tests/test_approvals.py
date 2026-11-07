"""Click-only commands (herdr writes, gog sends): the card, "always", Trust/Root, sends.log and the Bash-only hook."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import nixi_env

REPO_ROOT = Path(__file__).resolve().parent.parent

COUNT = ["gog send x", "gog gmail send-later x", "gog --gmail-no-send gmail list", "gog gmail send --to a@b", "gog mail send", "gog gmail reply 123", "gog gmail reply-all 1",
         "gog gmail replyall 1", "gog gmail forward 1", "gog gmail fwd 1", "gog gmail autoreply", "gog gmail drafts send 9",
         "gog gmail drafts post 9", "gog chat messages send s", "gog chat messages create s", "gog chat messages post s",
         "gog api POST /x", 'g""og gmail send', "g\\og gmail send", "gog gmail drafts create x; gog gmail send y",
         "gog gmail \\\nsend --to a@b", "herdr agent prompt 1-1 hi", 'her""dr agent prompt 1 x',
         ["gog", "gmail", "send"], ["gog", "api", "x"]]
NOT = ["gog gmail list", "gog gmail search x", "gog chat spaces list", "gog gmail drafts create", "gog gmail drafts reply",
       "gog gmail drafts forward", "gog gmail drafts update", "blog send", "echo gogs", "ls -la", ["gog", "gmail", "list"]]
SEND = "gog gmail send --to me@example.com --subject topsecret-subject --body topsecret-body"


class ApprovalsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_env = os.environ.copy()
        cls.tmp = tempfile.mkdtemp(prefix="nixi-approvals-test-")
        for k, d in (("HOME", ""), ("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
            os.environ[k] = os.path.join(cls.tmp, d)
            os.makedirs(os.environ[k], exist_ok=True)
        sys.path.insert(0, str(REPO_ROOT / "app"))
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": nixi_env.run_dir()}):
            import server
        cls.s = server

    @classmethod
    def tearDownClass(cls):
        os.environ.clear()
        os.environ.update(cls._orig_env)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        s = self.s
        self.data = Path(tempfile.mkdtemp(dir=self.tmp))
        for patch in (mock.patch.object(s, "DATA_DIR", self.data), mock.patch.object(s, "SEND_HOOKS_PATH", self.data / "h.json"),
                      mock.patch.object(s, "HOOKS_PATH", self.data / "a.json"),
                      mock.patch.object(s, "_SENDS_LOG_FIXED", False)):
            patch.start()
            self.addCleanup(patch.stop)
        self.events = []
        self.answer = "yes"
        self.ap = s.Approvals()

        def pub(**kw):
            self.events.append(kw)
            if kw.get("t") == "approve" and self.answer is not None:
                self.ap.answer(kw["id"], self.answer)
        p = mock.patch.object(s.BUS, "pub", side_effect=pub)
        p.start()
        self.addCleanup(p.stop)
        self.mode("ask")

    def mode(self, m):
        p = mock.patch.object(self.s, "trust", return_value=m)
        p.start()
        self.addCleanup(p.stop)

    def asks(self):
        return [e for e in self.events if e.get("t") == "approve"]

    def log(self):
        f = self.data / "sends.log"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def test_click_only_table(self):
        for c in COUNT:
            self.assertTrue(self.s.click_only(c), c)
        for c in NOT:
            self.assertFalse(self.s.click_only(c), c)

    def test_detail_never_keeps_flag_looking_text(self):
        for cmd in ('gog gmail send --to a@b --body "--bcc=private body"', 'gog gmail send --to a@b --body "--to=confidential"',
                    "gog gmail send --to a@b --subject --cc secret", 'gog gmail send "--to=private words here"'):
            self.assertNotRegex(json.dumps(self.s.send_detail(cmd)), "private|confidential|secret", cmd)

    def test_global_flags_and_new_forms(self):
        d = self.s.send_detail
        self.assertEqual(d('gog -a "me@x.y" --no-input gmail send --to a@b --body hi'),
                         {"kind": "gog", "command": "gmail send", "to": "a@b"})
        self.assertEqual(d("gog --account=me@x.y -j chat dm send a@b --text hi"),
                         {"kind": "gog", "command": "chat dm send", "to": "a@b"})
        for cmd in ("g$'o'g gmail send x", "g${X}og gmail send x", "gog calendar respond c e", "gog calendar rsvp c e"):
            self.assertTrue(self.s.click_only(cmd), cmd)

    def test_expansion_and_word_boundaries(self):
        self.assertTrue(self.s.click_only('echo "${UNSET:-$(gog gmail send --to a@b --body hello)}"'))
        self.assertTrue(self.s.click_only('gog gmail "${UNSET:-se}nd" --to a@b --body hello'))
        self.assertTrue(self.s.click_only("gog gmail `echo send` --to a@b"))
        self.assertTrue(self.s.click_only("g${UNSET:-o}g gmail send --to a@b --body hello"))
        self.assertEqual(self.s.send_detail("gog gmail send --to actual@example.com --body-file <(printf %s --bcc=secret@example.com)")["to"], "")
        for cmd in ("gog gmail s{e..e}nd --to a@b", "gog gmail {se,x}nd --to a@b", "gog gmail s?nd --to a@b", "gog gmail s[e]nd --to a@b"):
            self.assertTrue(self.s.click_only(cmd), cmd)
        self.assertEqual(self.s.send_detail("gog gmail send --to actual@example.com --body=$(printf %s --bcc=secret@example.com)")["to"], "")
        self.assertEqual(self.s.send_detail("gog gmail send --to actual@example.com --body-file - <<'EOF'\n--bcc=secret@example.com\nEOF")["to"], "")
        d = self.s.send_detail('gog gmail send --to actual@example.com --body="private "--bcc=secret@example.com')
        self.assertNotIn("secret", json.dumps(d))

    def test_detail(self):
        d = self.s.send_detail
        self.assertEqual(d("gog gmail send --to=a@b --cc c@d"), {"kind": "gog", "command": "gmail send", "to": "a@b,c@d"})
        self.assertEqual(d("gog gmail reply 123 --body hi")["to"], "123")
        self.assertEqual(d("gog gmail reply --body hi")["to"], "")
        self.assertEqual(d("herdr --session s agent prompt 1-2 secret"), {"kind": "herdr", "pane": "1-2"})
        self.assertEqual(d("gog frob send")["command"], "unknown")
        for c in ("--body topsecret", "--body=topsecret", "--body-html topsecret", "--body-file topsecret",
                  "--raw-file topsecret", "--subject topsecret", "--body 'a send reply topsecret'"):
            self.assertNotIn("topsecret", json.dumps(d(f"gog gmail send --to a@b {c}")), c)

    def test_ask_click_only(self):
        self.answer = "always"
        self.ap.always.add("Bash:" + SEND)                      # a stored entry must not match
        self.assertEqual(self.ap.ask("Bash", {"command": SEND}), {"ok": True})
        a = self.asks()[0]
        self.assertEqual(a["confirm"], "click")
        self.assertFalse(a["always"])
        self.assertEqual(self.ap.always, {"Bash:" + SEND})      # nothing added; "always" counted once
        self.ap.ask("Bash", {"command": SEND})
        self.assertEqual(len(self.asks()), 2)

    def test_plain_command_unchanged(self):
        self.answer = "always"
        self.ap.ask("Bash", {"command": "ls"})
        self.assertIsNone(self.asks()[0]["confirm"])
        self.assertTrue(self.asks()[0]["always"])
        self.assertIn("Bash:ls", self.ap.always)
        self.ap.ask("Bash", {"command": "ls"})
        self.assertEqual(len(self.asks()), 1)
        self.assertEqual(self.log(), [])

    def test_trust_and_root(self):
        for m in ("trust", "root"):
            self.mode(m)
            self.events.clear()
            self.assertEqual(self.ap.ask("Bash", {"command": "ls"}), {"ok": True})
            self.assertEqual(self.ap.ask("WebFetch", {"url": "http://x"}), {"ok": True})
            self.assertEqual(self.asks(), [])
            self.ap.ask("Bash", {"command": SEND})
            self.assertEqual(self.asks()[0]["confirm"], "click")

    def test_sends_log(self):
        for ans in ("yes", "no", None):
            self.answer = ans
            self.ap.ask("Bash", {"command": SEND}, timeout=0.05)
        log = self.log()
        self.assertEqual([x["decision"] for x in log], ["allow", "deny", "timeout"])
        self.assertTrue(all(x["to"] == "me@example.com" and x["command"] == "gmail send" and "ts" in x for x in log))
        raw = (self.data / "sends.log").read_text()
        self.assertNotIn("topsecret", raw)
        self.assertNotIn("--body", raw)
        self.assertEqual((self.data / "sends.log").stat().st_mode & 0o777, 0o600)

    def test_existing_log_is_chmoded(self):
        f = self.data / "sends.log"
        f.write_text("")
        f.chmod(0o644)
        self.ap.ask("Bash", {"command": SEND})
        self.assertEqual(f.stat().st_mode & 0o777, 0o600)

    def test_send_hooks_file_names_bash_only(self):
        d = json.loads(Path(self.s.send_hooks_file()).read_text())
        pre = d["hooks"]["PreToolUse"]
        self.assertEqual([h["matcher"] for h in pre], ["Bash"])
        self.assertIn("approve.py", pre[0]["hooks"][0]["command"])

    def test_build_cmd_adds_settings_in_trust_and_root(self):
        for m, has in (("trust", True), ("root", True), ("ask", False)):
            self.mode(m)
            c = self.s.build_cmd("claude", False)
            self.assertEqual(str(self.data / "h.json") in c, has, m)
            self.assertEqual("bypassPermissions" in c, m != "ask")


if __name__ == "__main__":
    unittest.main()
