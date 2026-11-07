"""#210: hear a summary of an email, and reply to it with a click.

gog's JSON fields, read from real output on p620 (values in fixtures/mail are made up):

- `gog --readonly --json -a <addr> gmail messages search ...`:
  `messages[].{id, threadId, date, internalDateIso, from, subject, labels}`
- `gog --readonly --json -a <addr> gmail get <id>`:
  `headers.{bcc, cc, date, from, in_reply_to, message_id, references, reply_to, subject, to}`, `body` (decoded text),
  `message.{id, threadId, historyId, internalDate, labelIds, snippet, sizeEstimate,
  payload.{mimeType, headers[], parts[].{partId, mimeType, headers[], body.{data, size}}}}`
- `gog auth list --json`: `accounts[].{email, subject, client, auth, scopes, services, created_at}`;
  an account can read mail when "gmail" is in `services`.

Mail code reads only these fields. hostile.json holds the spec's hostile cases, keyed by name, each shaped like `get`.
"""

import json
import subprocess
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from test_speakable import _ServerEnv

FIX = Path(__file__).resolve().parent / "fixtures" / "mail"
ME = "you@example.com"
OTHER = "other@example.com"
NOMAIL = "nomail@example.com"


def fixture(name):
    return json.loads((FIX / name).read_text())


class Gog:
    """Stands in for subprocess.run: answers by argv from the fixtures, records every call. Never the real gog."""

    def __init__(self, fail=()):
        self.calls, self.fail, self.search = [], set(fail), fixture("search.json")

    def __call__(self, argv, **kw):
        assert isinstance(argv, list) and not kw.get("shell"), argv
        if argv[0] != "gog":                      # (anything else the server runs meanwhile: not installed here)
            raise FileNotFoundError(argv[0])
        self.calls.append(argv)
        rest = argv[1:]
        if rest[:2] == ["auth", "list"]:
            base = fixture("auth_list.json")["accounts"][0]
            out = {"accounts": [dict(base, email=ME), dict(base, email=OTHER), dict(base, email=NOMAIL, services=["calendar"])]}
        else:
            acct = rest[rest.index("-a") + 1]
            if acct in self.fail:
                raise subprocess.CalledProcessError(1, argv)
            out = self.search
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(out).encode())

    def searches(self):
        return [c for c in self.calls if "search" in c]


class MailBoardTest(_ServerEnv):
    def setUp(self):
        s = self.server
        saved = dict(s.CFG)
        self.addCleanup(lambda: (s.CFG.clear(), s.CFG.update(saved)))
        s.CFG.update(mail_on=True, mail_accounts=[ME], mail_model="")
        self.events = []
        self.gog = Gog()
        for p in (mock.patch.object(s, "BRIDGED", True), mock.patch.object(s.BUS, "pub", side_effect=lambda **e: self.events.append(e)),
                  mock.patch.object(s.subprocess, "run", self.gog), mock.patch.object(s.quick, "projects", return_value={})):
            p.start()
            self.addCleanup(p.stop)
        s.STAGES.clear()
        self.addCleanup(s.STAGES.clear)
        self.addCleanup(lambda: setattr(s, "MAIL_DRAFT", None))

    def board(self):
        self.server.mail_stage(None, self.server.STAGES.current())
        return self.server.STAGES.current()

    def test_defaults_are_off(self):
        d = self.server.DEFAULTS
        self.assertEqual((d["mail_on"], d["mail_accounts"], d["mail_model"]), (False, [], ""))

    def test_nothing_runs_while_mail_is_off(self):
        s = self.server
        s.CFG["mail_on"] = False
        with mock.patch.object(s.threading, "Thread") as thread:
            self.assertIn("off", s.mail_open()["say"])
            thread.assert_not_called()
        s.mail_stage(None, None)
        self.assertEqual(self.gog.calls, [])
        self.assertIsNone(s.STAGES.current())

    def test_every_search_is_readonly_for_a_listed_gmail_address(self):
        s = self.server
        s.CFG["mail_accounts"] = [ME, OTHER, NOMAIL, "gone@example.com"]
        self.assertEqual(len(self.board()["rows"]), 4)
        got = self.gog.searches()
        self.assertEqual([c[c.index("-a") + 1] for c in got], [ME, OTHER])        # not the no-gmail one, not the unlisted one
        for c in got:
            self.assertEqual(c[:3], ["gog", "--readonly", "--json"])
            self.assertEqual(c[-5:], ["messages", "search", "in:inbox is:unread newer_than:3d", "--max", "5"])
        self.assertFalse([c for c in self.gog.calls if "send" in c])

    def test_the_page_gets_no_ids_and_two_tokens_a_row(self):
        page = self.board()
        self.assertEqual(page["kind"], "mail")
        self.assertNotIn("note", page)
        toks = set()
        for row in page["rows"]:
            self.assertEqual(set(row), {"account", "from", "subject", "age", "hear", "reply"})
            self.assertNotEqual(row["hear"], row["reply"])
            toks |= {row["hear"], row["reply"]}
        self.assertEqual(len(toks), 2 * len(page["rows"]))
        self.assertNotIn("fixture0000000001", json.dumps(self.events))
        self.assertNotIn("threadId", json.dumps(page))
        row = page["rows"][0]
        self.assertEqual(self.server.STAGES.get(row["hear"])[0], "mail_hear")
        got = self.server.STAGES.get(row["reply"])
        self.assertEqual((got[0], set(got[1])), ("mail_reply", {"account", "id", "thread"}))
        self.assertEqual((row["from"], row["account"]), ("sender@example.com", ME))

    def test_a_row_without_a_message_or_thread_id_is_left_out(self):
        del self.gog.search["messages"][0]["threadId"]
        self.gog.search["messages"][1]["id"] = ""
        self.assertEqual(self.board()["rows"], [])

    def test_a_failing_account_gives_a_row_with_no_error_text(self):
        self.server.CFG["mail_accounts"] = [ME, OTHER]
        self.gog.fail = {OTHER}
        rows = self.board()["rows"]
        bad = [r for r in rows if r["account"] == OTHER]
        self.assertEqual([(r["subject"], r["hear"], r["reply"]) for r in bad], [(f"Couldn't read {OTHER}", None, None)])
        self.assertEqual(len([r for r in rows if r["account"] == ME]), 2)

    def test_a_mail_board_is_not_kept(self):
        s = self.server
        facts = s.stages.validate({"v": 1, "kind": "facts", "title": "T", "points": ["a"]})
        tok = self.board()["rows"][0]["hear"]
        s.STAGES.put(facts)                               # a facts board replaces it
        self.assertIsNone(s.STAGES.get(tok))
        self.assertIsNone(s.STAGES.back())
        self.assertFalse(s.STAGES.has_prev())
        tok = self.board()["rows"][0]["hear"]
        s.STAGES.close()                                  # or it is closed
        self.assertIsNone(s.STAGES.get(tok))
        self.assertIsNone(s.STAGES.back())

    def test_a_facts_board_is_still_kept_unless_mail_replaces_it(self):
        s = self.server
        s.STAGES.put(s.stages.validate({"v": 1, "kind": "facts", "title": "T", "points": ["a"]}))
        s.STAGES.put(s.stages.validate({"v": 1, "kind": "facts", "title": "U", "points": ["a"]}))
        self.assertEqual(s.STAGES.back()["title"], "T")   # (the ordinary rule is unchanged)
        s.STAGES.put({"v": 1, "kind": "mail", "rows": []})
        self.assertEqual(s.STAGES.back()["title"], "T")   # (T was kept under mail; mail itself goes nowhere)
        self.assertIsNone(s.STAGES.back())

    def test_it_publishes_only_if_nothing_changed_meanwhile(self):
        s = self.server
        before = s.STAGES.current()
        real = s.mail_accounts

        def late():
            got = real()
            s.mail_reset()                                # mail was switched while gog was still answering
            return got
        with mock.patch.object(s, "mail_accounts", late):
            s.mail_stage(None, before)
        self.assertIsNone(s.STAGES.current())
        s.STAGES.put(s.stages.validate({"v": 1, "kind": "facts", "title": "T", "points": ["a"]}))
        s.mail_stage(None, None)                          # the stage it started from is gone
        self.assertEqual(s.STAGES.current()["kind"], "facts")

    def test_changing_a_mail_setting_closes_the_board_and_drops_a_draft(self):
        s = self.server
        for body in ({"mail_on": False}, {"mail_accounts": [OTHER]}, {"mail_model": "gemma4:e4b"}):
            s.CFG.update(mail_on=True, mail_accounts=[ME], mail_model="")
            self.board()
            s.MAIL_DRAFT = {"id": "d"}
            gen = s.MAIL_GEN
            self.assertEqual(self.post("/api/settings", body)[0], 200, body)
            self.assertIsNone(s.STAGES.current(), body)
            self.assertIsNone(s.MAIL_DRAFT, body)
            self.assertGreater(s.MAIL_GEN, gen)
        self.board()
        gen = s.MAIL_GEN
        self.post("/api/settings", {"mail_model": "gemma4:e4b"})        # the same value again changes nothing
        self.assertEqual((s.MAIL_GEN, s.STAGES.current()["kind"]), (gen, "mail"))

    def test_settings_refuse_bad_values(self):
        s = self.server
        for body in ({"mail_accounts": ["a b@example.com"]}, {"mail_accounts": ["a@x.com,b@x.com"]}, {"mail_accounts": ["a@example.com"] * 6},
                     {"mail_accounts": "a@example.com"}, {"mail_model": "x y"}, {"mail_model": "x" * 81}, {"mail_model": 5}):
            self.post("/api/settings", body)
        self.assertEqual((s.CFG["mail_accounts"], s.CFG["mail_model"]), ([ME], ""))
        self.post("/api/settings", {"mail_on": 1})
        self.assertIs(s.CFG["mail_on"], True)
        info = s.state_info()
        self.assertEqual((info["mail_on"], info["mail_accounts"], info["mail_model"]), (True, [ME], ""))

    def test_capture_is_refused_while_mail_is_up(self):
        s = self.server
        shot = {"kind": "screen", "image": "x"}
        self.board()
        with mock.patch.object(s, "BRIDGED", False), mock.patch.object(s, "capture", return_value=shot) as cap:
            code, body = self.post("/api/capture", {"kind": "screen"}, token=s.TOOL_TOKEN)
            self.assertEqual((code, body), (403, {"error": "mail is on screen"}))
            cap.assert_not_called()
            s.STAGES.close()
            self.assertEqual(self.post("/api/capture", {"kind": "screen"}, token=s.TOOL_TOKEN), (200, shot))
            s.MAIL_DRAFT = {"id": "d"}
            self.assertEqual(self.post("/api/capture", {"kind": "screen"}, token=s.TOOL_TOKEN)[0], 403)

    def test_the_agent_cannot_make_a_mail_board(self):
        s = self.server
        self.assertEqual(s.stages.validate({"v": 1, "kind": "mail", "rows": [{"account": ME, "id": "x", "thread": "y"}]}), {"v": 1, "kind": "mail"})
        self.assertNotIn("mail", s.stages.SERVER_KINDS)

    def test_mail_tokens_reach_no_stage_button(self):
        s = self.server
        page = self.board()
        with mock.patch.object(s.subprocess, "Popen") as popen:
            for act in ("copy", "open", "play", "session", "terminal"):
                for key in ("hear", "reply"):
                    self.assertFalse(s.stage_act(page["rows"][0][key], act)["ok"])
            popen.assert_not_called()

    def test_the_phrases_open_the_board_without_an_agent_turn(self):
        s = self.server
        for said in ("read my mail", "Any new email?", "check my email please", "hey nixi, check my email"):
            self.assertEqual(s.quick.handle(said), {"mail": True}, said)
        for said in ("check my emails", "read my mail to bob", "email bob"):
            self.assertNotEqual(s.quick.handle(said), {"mail": True}, said)
        with mock.patch.object(s.threading, "Thread") as thread:
            code, body = self.post("/api/quick", {"text": "read my mail"})
        self.assertEqual((code, body["handled"], body["say"]), (200, True, "Let me look at your mail."))
        thread.assert_called_once()
        self.assertIs(thread.call_args.kwargs["target"], s.mail_stage)
        with mock.patch.object(s, "BRIDGED", False):
            self.assertEqual(s.mail_open()["say"], "Mail needs answer boards on in nixi mode.")

    def test_the_stage_block_makes_the_board_off_the_turn(self):
        s = self.server
        self.assertEqual(s.stages.validate({"v": 1, "kind": "mail"}), {"v": 1, "kind": "mail"})
        src = Path(s.__file__).read_text()
        self.assertIn('("video", "day", "mail")', src)

    def test_the_window_token_only(self):
        s = self.server
        self.assertEqual(self.post("/api/mail/open", {}, token=s.TOOL_TOKEN)[0], 403)
        with mock.patch.object(s.threading, "Thread"):
            self.assertEqual(self.post("/api/mail/open", {})[0], 200)
        self.assertEqual(self.get("/api/mail/options", token=s.TOOL_TOKEN)[0], 403)
        with mock.patch.object(urllib.request, "urlopen", side_effect=OSError):
            self.assertEqual(self.get("/api/mail/options"), (200, {"accounts": [ME, OTHER], "models": []}))

    def test_nothing_is_printed_or_written(self):
        out = self.server.sys
        self.gog.fail = {ME}
        with mock.patch.object(out, "stdout") as so, mock.patch.object(out, "stderr") as se:
            self.board()
        text = "".join(str(c) for c in so.mock_calls + se.mock_calls)
        for leak in ("Lunch", "sender@example.com", "fixture0000", "Traceback"):
            self.assertNotIn(leak, text)
        self.assertIn("CalledProcessError", text)

    # ---- the real handler
    def _handler(self, path, body, token):
        s = self.server
        h = object.__new__(s.Handler)
        h.path = path
        h.headers = {"X-Nixi-Token": token or s.TOKEN}
        h._host_ok = lambda: True
        h._body = lambda: json.dumps(body).encode()
        h._json = mock.Mock()
        return h

    def post(self, path, body, token=None):
        h = self._handler(path, body, token)
        h.do_POST()
        args = h._json.call_args
        return (args.args[1] if len(args.args) > 1 else 200), args.args[0]

    def get(self, path, token=None):
        h = self._handler(path, {}, token)
        h.do_GET()
        args = h._json.call_args
        return (args.args[1] if len(args.args) > 1 else 200), args.args[0]


if __name__ == "__main__":
    unittest.main()
