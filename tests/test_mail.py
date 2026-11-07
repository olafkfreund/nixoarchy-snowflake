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
import io
import contextlib
import subprocess
import shlex
import threading
import ast
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
        self.get = fixture("get_plain.json")

    def __call__(self, argv, **kw):
        assert isinstance(argv, list) and not kw.get("shell"), argv
        if argv[0] != "gog":                      # (anything else the server runs meanwhile: not installed here)
            raise FileNotFoundError(argv[0])
        self.calls.append(argv)
        rest = argv[1:]
        if rest[:2] == ["auth", "list"]:
            base = fixture("auth_list.json")["accounts"][0]
            out = {"accounts": [dict(base, email=ME), dict(base, email=OTHER), dict(base, email=NOMAIL, services=["calendar"])]}
        elif "send" in rest:
            out = {"threadId": "fixture0000000001"}
        else:
            acct = rest[rest.index("-a") + 1]
            if acct in self.fail:
                raise subprocess.CalledProcessError(1, argv)
            out = self.get if "get" in rest else self.search
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
        s.Speaker.mail_sids.clear()
        self.addCleanup(s.Speaker.mail_sids.clear)

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

    def test_turning_mail_off_during_list_publishes_and_speaks_nothing(self):
        s = self.server
        real = s.mail_accounts
        def late():
            accounts = real()
            s.CFG["mail_on"] = False
            s.mail_reset()
            return accounts
        self.events.clear()
        with mock.patch.object(s, "mail_accounts", side_effect=late), mock.patch.object(s.Speaker, "say") as say:
            s.mail_stage(None, None)
        self.assertIsNone(s.STAGES.current())
        self.assertFalse([e for e in self.events if e.get("t") == "stage"])
        say.assert_not_called()

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
            self.assertFalse([c for c in popen.call_args_list if c.args and c.args[0] and c.args[0][0] == "claude"])

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

    def test_mail_clean_drops_controls_links_and_secret_lines(self):
        s = self.server
        raw = "Start\x07\u202e https://example.com/path\npassword=hidden\nEnd\u200b"
        self.assertEqual(s.mail_clean(raw, 100), "Start [link]\nEnd")
        self.assertEqual(s.mail_clean("ééé", 5), "éé")
        self.assertEqual(len(s.mail_clean("é" * 5000, 8000).encode()), 8000)

    def test_mail_scrub_uses_one_messages_otp_result(self):
        s = self.server
        fields = ["Verification code", "482913 expires soon", "Case 2026"]
        self.assertTrue(s.mail_otp(fields))
        self.assertEqual(s.mail_scrub(fields), ["Verification code", "[code] expires soon", "Case [code]"])
        self.assertEqual(s.mail_scrub(["Case 2026"], False), ["Case 2026"])
        self.assertEqual(s.mail_scrub(["login code ab12cd34 and 123 456"]), ["login code [code] and [code]"])
        self.assertEqual(s.mail_scrub(["code ab12cd34"], True), ["code [code]"])

    def test_html_text_drops_script_style_and_fetches_nothing(self):
        s = self.server
        with mock.patch.object(urllib.request, "urlopen") as open_url:
            self.assertEqual(s.mail_html_text('<style>secret</style><script>bad()</script><p>Hello <b>there</b><img src="https://example.com/a">!</p>').strip(), "Hello there!")
            open_url.assert_not_called()

    def test_hear_requires_a_live_row_and_window_token(self):
        s = self.server
        row = self.board()["rows"][0]
        with mock.patch.object(s.Desk, "locked", return_value=True), mock.patch.object(urllib.request, "urlopen") as url:
            self.assertEqual(self.post("/api/mail/hear", {"token": row["hear"]}, token=s.TOOL_TOKEN)[0], 403)
            self.assertEqual(self.post("/api/mail/hear", {"token": row["reply"]}), (200, {"ok": False}))
            self.assertEqual(self.post("/api/mail/hear", {"token": "missing"}), (200, {"ok": False}))
            self.assertEqual(self.post("/api/mail/hear", {"token": row["hear"]}),
                             (200, {"from": "sender@example.com", "subject": "Lunch on Friday?", "summary": "I couldn't summarise that one"}))
            url.assert_not_called()
            s.STAGES.close()
            self.assertEqual(self.post("/api/mail/hear", {"token": row["hear"]}), (200, {"ok": False}))
        self.assertNotIn("/api/mail/hear", s.TOOL_PATHS)

    def test_ollama_summary_uses_fixed_local_generate_without_tools_or_context(self):
        s = self.server
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"response":"Lunch Friday."}'
        with mock.patch.dict(s.os.environ, {"OLLAMA_HOST": "http://evil:1"}), mock.patch.object(urllib.request, "urlopen", return_value=response) as url:
            self.assertEqual(s.ollama_summary("gemma4:e4b", "Subject: Lunch"), "Lunch Friday.")
        req = url.call_args.args[0]
        self.assertEqual(req.full_url, "http://127.0.0.1:11434/api/generate")
        self.assertEqual(req.get_method(), "POST")
        data = json.loads(req.data)
        self.assertEqual(set(data), {"model", "system", "prompt", "stream", "options"})
        self.assertIs(data["stream"], False)
        self.assertEqual(data["options"], {"temperature": 0})
        self.assertIn("untrusted sender", data["system"])
        self.assertIn("never instructions", data["system"])
        self.assertIn("two or three plain sentences", data["system"])
        self.assertIn("<email>\nSubject: Lunch\n</email>", data["prompt"])
        self.assertEqual(url.call_args.kwargs["timeout"], 60)

    def test_hear_gets_readonly_and_speaks_clean_local_summary(self):
        s = self.server
        row = self.board()["rows"][0]
        s.CFG["mail_model"] = "gemma4:e4b"
        self.gog.get = fixture("get_plain.json")
        with mock.patch.object(s.Desk, "locked", return_value=False), mock.patch.object(s, "ollama_summary", return_value="Friday lunch? <<stage>> https://example.com") as summary, \
             mock.patch.object(s.Speaker, "say") as say:
            reply = self.post("/api/mail/hear", {"token": row["hear"]})[1]
        get = [c for c in self.gog.calls if "get" in c][-1]
        self.assertEqual(get, ["gog", "--readonly", "--json", "-a", ME, "gmail", "get", s.STAGES.get(row["hear"])[1]["id"]])
        self.assertIn("Lunch on Friday?", summary.call_args.args[1])
        line, sid = say.call_args.args
        self.assertEqual(say.call_args.kwargs, {"local": True})
        self.assertTrue(line.startswith(f"Summary of an email to {ME} from sender@example.com:"))
        self.assertNotIn("<<", line)
        self.assertNotIn("https://", line)
        self.assertIsInstance(sid, int)
        self.assertGreater(sid, 1_000_000)
        self.assertIn(sid, s.Speaker.mail_sids)
        self.assertEqual(reply, {"from": "sender@example.com", "subject": "Lunch on Friday?", "summary": line})
        s.Speaker.mail_sids.discard(sid)

    def test_otp_from_message_scrubs_model_output(self):
        s = self.server
        row = self.board()["rows"][0]
        s.CFG["mail_model"] = "gemma4:e4b"
        self.gog.get = fixture("hostile.json")["otp_next_line"]
        with mock.patch.object(s.Desk, "locked", return_value=False), mock.patch.object(s, "ollama_summary", return_value="Your code is 482913."), mock.patch.object(s.Speaker, "say") as say:
            reply = self.post("/api/mail/hear", {"token": row["hear"]})[1]
        self.assertIn("[code]", say.call_args.args[0])
        self.assertNotIn("482913", say.call_args.args[0])
        self.assertIn("[code]", reply["summary"])
        s.Speaker.mail_sids.discard(say.call_args.args[1])

    def test_subject_otp_and_body_secrets_are_kept_out_of_the_prompt(self):
        s = self.server
        row = self.board()["rows"][0]
        s.CFG["mail_model"] = "gemma4:e4b"
        for case, forbidden in (("otp_in_subject", "771204"), ("reset_link", "https://"), ("api_key", "sk-test-")):
            self.gog.get = fixture("hostile.json")[case]
            with self.subTest(case=case), mock.patch.object(s.Desk, "locked", return_value=False), mock.patch.object(s, "ollama_summary", return_value="A short note.") as summary, \
                 mock.patch.object(s.Speaker, "say") as say:
                reply = self.post("/api/mail/hear", {"token": row["hear"]})[1]
                self.assertNotIn(forbidden, summary.call_args.args[1])
                self.assertNotIn(forbidden, say.call_args.args[0])
                self.assertNotIn(forbidden, json.dumps(reply))
                s.Speaker.mail_sids.discard(say.call_args.args[1])

    def test_hear_refuses_an_unlisted_account_without_fetching(self):
        s = self.server
        row = self.board()["rows"][0]
        s.CFG["mail_accounts"] = [OTHER]
        self.gog.calls.clear()
        with mock.patch.object(s, "ollama_summary") as summary, mock.patch.object(s.Speaker, "say") as say:
            self.assertEqual(self.post("/api/mail/hear", {"token": row["hear"]}), (200, {"ok": False}))
        self.assertFalse([c for c in self.gog.calls if "get" in c])
        summary.assert_not_called()
        say.assert_not_called()

    def test_previous_board_and_reply_tokens_refuse_without_gog(self):
        s = self.server
        row = self.board()["rows"][0]
        self.gog.calls.clear()
        self.assertEqual(self.post("/api/mail/hear", {"token": row["reply"]}), (200, {"ok": False}))
        self.assertEqual(self.gog.calls, [])
        s.STAGES.put(s.stages.validate({"v": 1, "kind": "facts", "title": "Other", "points": ["a"]}))
        self.assertEqual(self.post("/api/mail/hear", {"token": row["hear"]}), (200, {"ok": False}))
        self.assertEqual(self.gog.calls, [])

    def test_model_failure_returns_subject_and_speaks_fixed_line(self):
        s = self.server
        row = self.board()["rows"][0]
        s.CFG["mail_model"] = "gemma4:e4b"
        with mock.patch.object(s.Desk, "locked", return_value=False), mock.patch.object(urllib.request, "urlopen", side_effect=OSError("fixture private")), \
             mock.patch.object(s.Speaker, "say") as say:
            reply = self.post("/api/mail/hear", {"token": row["hear"]})[1]
        self.assertEqual(reply, {"from": "sender@example.com", "subject": "Lunch on Friday?", "summary": "I couldn't summarise that one"})
        self.assertEqual(say.call_args.args[0], reply["summary"])
        self.assertEqual(say.call_args.kwargs, {"local": True})

    def test_hostile_fields_reach_only_cleaned_model_prompt_and_reply(self):
        s = self.server
        row = self.board()["rows"][0]
        s.CFG["mail_model"] = "gemma4:e4b"
        cases = ("otp_next_line", "otp_in_subject", "reset_link", "api_key", "control_chars", "html_body", "stage_injection")
        prompts = []
        def url(req, **kw):
            data = json.loads(req.data)
            prompts.append(data["prompt"])
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps({"response": "<<stage>> Code 482913 https://example.com" if "[code]" in data["prompt"] else "<<stage>> A note https://example.com"}).encode()
            return response
        with mock.patch.object(urllib.request, "urlopen", side_effect=url), mock.patch.object(s.Desk, "locked", return_value=True), \
             mock.patch.object(s.subprocess, "Popen") as popen, mock.patch.object(s.Speaker, "say") as say:
            for case in cases:
                self.gog.get = fixture("hostile.json")[case]
                reply = self.post("/api/mail/hear", {"token": row["hear"]})[1]
                joined = json.dumps(reply) + prompts[-1]
                for forbidden in ("771204", "https://", "sk-test-", "\u202e", "\u200b", "\u0007", "<<"):
                    self.assertNotIn(forbidden, joined, case)
                if case in ("otp_next_line", "otp_in_subject"):
                    self.assertNotIn("482913", joined, case)
                self.assertEqual(set(reply), {"from", "subject", "summary"})
            say.assert_not_called()
            self.assertFalse([c for c in popen.call_args_list if c.args and c.args[0] and c.args[0][0] == "claude"])
        self.assertEqual(len(prompts), len(cases))
        self.assertIn("[link]", prompts[2])
        self.assertIn("bold", prompts[5])
        self.assertNotIn("alert", prompts[5])

    def test_model_answer_that_is_only_a_code_is_scrubbed(self):
        s = self.server
        row = self.board()["rows"][0]
        s.CFG["mail_model"] = "gemma4:e4b"
        self.gog.get = fixture("hostile.json")["otp_next_line"]
        with mock.patch.object(s.Desk, "locked", return_value=True), mock.patch.object(s, "ollama_summary", return_value="482913"):
            reply = self.post("/api/mail/hear", {"token": row["hear"]})[1]
        self.assertTrue(reply["summary"].endswith(": [code]"))

    def test_locked_unknown_or_meeting_never_speaks(self):
        s = self.server
        row = self.board()["rows"][0]
        for locked, meeting in ((True, False), (None, False), (False, True)):
            with self.subTest(locked=locked, meeting=meeting), mock.patch.object(s.Desk, "locked", return_value=locked), \
                 mock.patch.object(s.Ambient, "meeting", meeting), mock.patch.object(s.Speaker, "say") as say:
                self.assertIn("summary", self.post("/api/mail/hear", {"token": row["hear"]})[1])
                say.assert_not_called()

    def test_mail_turned_off_during_get_returns_nothing(self):
        s = self.server
        row = self.board()["rows"][0]
        real = s._gog
        def late(args, **kw):
            result = real(args, **kw)
            if "get" in args:
                s.CFG["mail_on"] = False
                s.mail_reset()
            return result
        with mock.patch.object(s, "_gog", side_effect=late), mock.patch.object(s.Speaker, "say") as say:
            self.assertEqual(self.post("/api/mail/hear", {"token": row["hear"]}), (200, {"ok": False}))
            say.assert_not_called()

    def test_injection_cannot_change_stage_mood_approval_or_draft(self):
        s = self.server
        row = self.board()["rows"][0]
        s.CFG["mail_model"] = "gemma4:e4b"
        self.gog.get = fixture("hostile.json")["stage_injection"]
        before = s.STAGES.current()
        s.MAIL_DRAFT = {"id": "kept"}
        with mock.patch.object(s.Desk, "locked", return_value=True), mock.patch.object(s, "ollama_summary", return_value="Just a message."), \
             mock.patch.object(s.stages, "validate") as validate, mock.patch.object(s.APPROVALS, "ask") as ask:
            reply = self.post("/api/mail/hear", {"token": row["hear"]})[1]
        self.assertEqual(s.STAGES.current(), before)
        self.assertEqual(s.MAIL_DRAFT, {"id": "kept"})
        self.assertNotIn("mood", reply)
        validate.assert_not_called()
        ask.assert_not_called()

    def test_history_recall_and_output_unchanged_after_list_hear_failure(self):
        s = self.server
        paths = [s.HIST_PATH, s.recall.PATH]
        before = [(p.exists(), p.read_bytes() if p.exists() else b"") for p in paths]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.object(s.Desk, "locked", return_value=True):
            row = self.board()["rows"][0]
            self.post("/api/mail/hear", {"token": row["hear"]})
            s.CFG["mail_model"] = "gemma4:e4b"
            with mock.patch.object(urllib.request, "urlopen", side_effect=OSError("secret fixture text")):
                self.post("/api/mail/hear", {"token": row["hear"]})
        self.assertEqual(before, [(p.exists(), p.read_bytes() if p.exists() else b"") for p in paths])
        self.assertNotIn("secret fixture text", out.getvalue() + err.getvalue())
        for field in ("Lunch on Friday?", "sender@example.com", "fixture0000000001"):
            self.assertNotIn(field, out.getvalue() + err.getvalue())

    def test_a_changed_board_or_setting_stops_work_before_speech(self):
        s = self.server
        row = self.board()["rows"][0]
        s.CFG["mail_model"] = "gemma4:e4b"
        with mock.patch.object(s, "ollama_summary", side_effect=lambda *_: s.STAGES.close()), mock.patch.object(s.Speaker, "say") as say:
            self.assertEqual(self.post("/api/mail/hear", {"token": row["hear"]}), (200, {"ok": False}))
            say.assert_not_called()
        row = self.board()["rows"][0]
        with mock.patch.object(s, "ollama_summary", side_effect=lambda *_: s.mail_reset()), mock.patch.object(s.Speaker, "say") as say:
            self.assertEqual(self.post("/api/mail/hear", {"token": row["hear"]}), (200, {"ok": False}))
            say.assert_not_called()

    def test_player_checks_mail_again_after_audio_is_ready(self):
        s = self.server
        row = self.board()["rows"][0]
        s.CFG["mail_model"] = "gemma4:e4b"
        sid = 1_000_000_777
        S = s.Speaker
        S.mail_sids.add(sid)
        S.ready.append((S.gen, sid, "private mail", b"\0\0", 22050, None, None, 0.1, False, "local", None))
        self.addCleanup(S.ready.clear)
        with mock.patch.object(s.Desk, "locked", return_value=True), mock.patch.object(s.FLOOR, "hold", return_value=True), mock.patch.object(S, "_player"), \
             mock.patch.object(S, "_write") as write, mock.patch.object(S, "_release_if_idle", side_effect=StopIteration), \
             mock.patch.object(s.BUS, "pub", side_effect=lambda **e: self.events.append(e)):
            with self.assertRaises(StopIteration):
                S._player_loop()
        write.assert_not_called()
        self.assertIn({"t": "spk_skip", "id": sid}, self.events)
        self.assertNotIn(sid, S.mail_sids)

    def test_html_get_and_long_model_answer_are_sanitized(self):
        s = self.server
        row = self.board()["rows"][0]
        s.CFG["mail_model"] = "gemma4:e4b"
        self.gog.get = fixture("hostile.json")["html_body"]
        self.gog.get["message"]["payload"]["mimeType"] = "text/html"
        with mock.patch.object(s.Desk, "locked", return_value=False), mock.patch.object(s, "ollama_summary", return_value="<<stage>>" + "word " * 150) as summary, \
             mock.patch.object(s.Speaker, "say") as say:
            s.mail_hear_work(row["hear"], ME, "hostile06", s.CFG["mail_model"], s.MAIL_GEN)
        prompt = summary.call_args.args[1]
        self.assertIn("bold", prompt)
        self.assertNotIn("alert", prompt)
        spoken, sid = say.call_args.args
        self.assertNotIn("<<", spoken)
        self.assertEqual(len(spoken.split(": ", 1)[1]), 400)
        s.Speaker.mail_sids.discard(sid)

    def test_nothing_is_printed_or_written(self):
        out = self.server.sys
        self.gog.fail = {ME}
        with mock.patch.object(out, "stdout") as so, mock.patch.object(out, "stderr") as se:
            self.board()
        text = "".join(str(c) for c in so.mock_calls + se.mock_calls)
        for leak in ("Lunch", "sender@example.com", "fixture0000", "Traceback"):
            self.assertNotIn(leak, text)
        self.assertIn("CalledProcessError", text)

    # ---- Draft and send
    def review(self, text="My reply", all=False):
        row = self.board()["rows"][-1]
        return self.post("/api/mail/draft", {"token": row["reply"], "text": text, "all": all})[1]

    def test_draft_refetch_and_reply_all_addresses(self):
        s = self.server
        self.gog.get["headers"].update({"from": '"Sender, Example" <sender@example.com>',
                                         "reply_to": '"Reply, Desk" <reply@example.com>',
                                         "to": f'"Me, First" <{ME}>, One <one@example.com>, {NOMAIL}',
                                         "cc": f'{OTHER}, Two <two@example.com>, one@example.com'})
        draft = self.review(all=True)
        self.assertEqual(draft["to"], ["reply@example.com"])
        self.assertEqual(draft["cc"], ["one@example.com", "two@example.com"])
        self.assertEqual((draft["from"], draft["reply_to_differs"]), ("sender@example.com", True))
        self.assertEqual(draft["subject"], "Re: Lunch on Friday?")
        self.assertEqual([c for c in self.gog.calls if "get" in c][-1][-2:], ["fixture0000000001", "--format=metadata"])
        self.assertEqual(s.MAIL_DRAFT["body"], "My reply")

    def test_draft_refusals_and_body_byte_limit(self):
        for edit in ({"subject": "bad\nsubject"}, {"from": "bad address"}, {"reply_to": "bad address"},
                     {"to": "bad address"}, {"cc": "bad address"}):
            with self.subTest(edit=edit):
                self.gog.get = fixture("get_plain.json")
                self.gog.get["headers"].update(edit)
                self.assertFalse(self.review(all=True).get("draft"))
                self.assertIsNone(self.server.MAIL_DRAFT)
        self.gog.get = fixture("get_plain.json")
        del self.gog.get["message"]["threadId"]
        self.assertFalse(self.review().get("draft"))
        self.gog.get = fixture("get_plain.json")
        del self.gog.get["message"]["id"]
        self.assertFalse(self.review().get("draft"))
        self.gog.get = fixture("get_plain.json")
        self.gog.get["headers"]["reply_to"] = "one@example.com, two@example.com"
        self.assertFalse(self.review().get("draft"))
        self.gog.get = fixture("get_plain.json")
        self.gog.get["headers"]["to"] = ",".join(f"u{i}@example.com" for i in range(21))
        self.assertFalse(self.review(all=True).get("draft"))
        self.gog.get = fixture("get_plain.json")
        self.assertTrue(self.review("x" * 20000).get("draft"))
        self.assertFalse(self.review("x" * 20001).get("draft"))
        self.assertFalse(self.review("é" * 10001).get("draft"))

    def test_draft_race_cancel_and_setting_change(self):
        s = self.server
        row = self.board()["rows"][-1]
        real = s._gog
        started, release = threading.Event(), threading.Event()
        def delayed(args, **kw):
            if "get" in args and threading.current_thread().name == "older":
                started.set()
                release.wait(5)
            return real(args, **kw)
        answers = []
        with mock.patch.object(s, "_gog", side_effect=delayed):
            older = threading.Thread(name="older", target=lambda: answers.append(s.mail_draft(row["reply"], "older", False)))
            older.start()
            self.assertTrue(started.wait(5))
            newer = s.mail_draft(row["reply"], "newer", False)
            release.set(); older.join(5)
        self.assertEqual(s.MAIL_DRAFT["body"], "newer")
        self.assertEqual(answers, [{"error": "that reply was replaced"}])
        self.assertEqual(s.mail_cancel(newer["draft"]), {"ok": True})
        self.assertIsNone(s.MAIL_DRAFT)
        self.assertEqual(s.mail_cancel(newer["draft"]), {"ok": False})
        for setting_change in (False, True):
            existing = s.mail_draft(row["reply"], "existing", False)
            started.clear(); release.clear(); answers.clear()
            with mock.patch.object(s, "_gog", side_effect=delayed):
                older = threading.Thread(name="older", target=lambda: answers.append(s.mail_draft(row["reply"], "late", False)))
                older.start(); self.assertTrue(started.wait(5))
                if setting_change:
                    s.mail_reset()
                else:
                    s.mail_cancel(existing["draft"])
                release.set(); older.join(5)
            self.assertIsNone(s.MAIL_DRAFT)
            self.assertFalse(answers[0].get("draft"))
        self.assertEqual(self.post("/api/mail/draft", {"token": row["hear"], "text": "x", "all": False})[1], {"ok": False})

    def test_send_argv_audit_and_one_use(self):
        s = self.server
        draft = self.review("Body stays on stdin")
        self.gog.calls.clear()
        sent = self.post("/api/mail/send", {"draft": draft["draft"], "text": draft["body"]})[1]
        argv = [c for c in self.gog.calls if "send" in c][0]
        self.assertEqual(sent, {"sent": True, "thread": "fixture0000000001"})
        self.assertEqual(argv, ["gog", "--json", "-a", ME, "gmail", "send", "--to", "sender@example.com",
                                "--subject", "Re: Lunch on Friday?", "--reply-to-message-id", "fixture0000000001", "--body-file", "-"])
        self.assertTrue(s.click_only(shlex.join(argv)))
        self.assertFalse(any(flag in argv for flag in ("--readonly", "--reply-all", "--from")))
        self.assertEqual(self.post("/api/mail/send", {"draft": draft["draft"], "text": draft["body"]})[1], {"ok": False})
        log = (s.DATA_DIR / "sends.log").read_text()
        self.assertIn("sender@example.com", log)
        self.assertNotIn("Body stays on stdin", log)
        self.assertNotIn("Lunch on Friday?", log)

    def test_send_spies_guard_and_thread_difference(self):
        s = self.server
        draft = self.review()
        events = []
        real = self.gog
        def run(argv, **kw):
            if "send" in argv:
                events.append(("run", argv, kw))
                return subprocess.CompletedProcess(argv, 0, stdout=b'{"threadId":"different"}')
            return real(argv, **kw)
        with mock.patch.object(s, "click_only", side_effect=lambda cmd: events.append(("click", cmd)) or True), \
             mock.patch.object(s, "send_detail", side_effect=lambda cmd: events.append(("detail", cmd)) or {"kind": "gog"}), \
             mock.patch.object(s, "sends_log", side_effect=lambda detail, decision: events.append(("log", detail, decision))), \
             mock.patch.object(s.subprocess, "run", side_effect=run):
            self.assertEqual(s.mail_send(draft["draft"], draft["body"]), {"sent": True, "other_thread": True})
        argv = events[-1][1]
        self.assertEqual([e[0] for e in events], ["click", "detail", "log", "run"])
        self.assertEqual(events[0][1], shlex.join(argv))
        self.assertEqual(events[1][1], shlex.join(argv))
        self.assertEqual(events[-1][2]["input"], draft["body"].encode())
        self.assertEqual(events[-1][2]["timeout"], 30)
        draft = self.review()
        with mock.patch.object(s, "click_only", return_value=False), mock.patch.object(s, "sends_log") as log:
            self.gog.calls.clear()
            self.assertEqual(s.mail_send(draft["draft"], draft["body"]), {"error": "guard"})
            log.assert_not_called()
            self.assertFalse([c for c in self.gog.calls if "send" in c])

    def test_timeout_crash_and_second_send(self):
        s = self.server
        for error, expected in ((subprocess.TimeoutExpired("gog", 30), {"unknown": True}), (OSError("private"), {"error": "OSError"})):
            with self.subTest(error=type(error).__name__):
                draft = self.review()
                path = s.DATA_DIR / "sends.log"
                before = len(path.read_text().splitlines()) if path.exists() else 0
                def failing_send(argv, **kw):
                    if "send" in argv:
                        raise error
                    return self.gog(argv, **kw)
                with mock.patch.object(s.subprocess, "run", side_effect=failing_send):
                    self.assertEqual(s.mail_send(draft["draft"], draft["body"]), expected)
                self.assertEqual(len(path.read_text().splitlines()), before + 1)
                self.assertEqual(s.mail_send(draft["draft"], draft["body"]), {"ok": False})

    def test_stale_changed_expired_or_unlisted_sends_nothing(self):
        s = self.server
        for mutate in (lambda d: "wrong", lambda d: d["draft"]):
            draft = self.review()
            self.assertEqual(s.mail_send(mutate(draft), draft["body"] + "x"), {"error": "the words changed, review them again"} if mutate(draft) == draft["draft"] else {"ok": False})
        draft = self.review()
        with mock.patch.object(s.time, "monotonic", return_value=s.MAIL_DRAFT["made"] + 601):
            self.assertEqual(s.mail_send(draft["draft"], draft["body"]), {"ok": False})
        draft = self.review(); s.CFG["mail_on"] = False
        self.assertEqual(s.mail_send(draft["draft"], draft["body"]), {"ok": False})
        s.CFG["mail_on"] = True
        draft = self.review(); s.CFG["mail_accounts"] = []
        self.gog.calls.clear()
        self.assertEqual(s.mail_send(draft["draft"], draft["body"]), {"ok": False})
        self.assertFalse([c for c in self.gog.calls if "send" in c])

    def test_two_threads_send_one_draft_once(self):
        s = self.server
        draft = self.review()
        self.gog.calls.clear()
        barrier = threading.Barrier(3)
        answers = []
        def worker():
            barrier.wait()
            answers.append(s.mail_send(draft["draft"], draft["body"]))
        workers = [threading.Thread(target=worker) for _ in range(2)]
        for worker_thread in workers: worker_thread.start()
        barrier.wait()
        for worker_thread in workers: worker_thread.join(5)
        self.assertEqual(len([c for c in self.gog.calls if "send" in c]), 1)
        self.assertEqual(len(answers), 2)

    def test_mail_routes_reject_tool_token(self):
        for path, payload in (("/api/mail/draft", {}), ("/api/mail/send", {}), ("/api/mail/cancel", {}),
                              ("/api/mail/hear", {}), ("/api/mail/open", {})):
            self.assertEqual(self.post(path, payload, token=self.server.TOOL_TOKEN)[0], 403, path)
        self.assertEqual(self.get("/api/mail/options", token=self.server.TOOL_TOKEN)[0], 403)

    def test_no_agent_turn_or_claude_for_mail_flow(self):
        s = self.server
        with mock.patch.object(s, "run_bridge") as bridge, mock.patch.object(s, "run_claude") as claude, \
             mock.patch.object(s.subprocess, "Popen") as popen, mock.patch.object(s.Desk, "locked", return_value=True):
            row = self.board()["rows"][-1]
            self.post("/api/mail/hear", {"token": row["hear"]})
            draft = self.post("/api/mail/draft", {"token": row["reply"], "text": "Hi", "all": False})[1]
            self.post("/api/mail/send", {"draft": draft["draft"], "text": "Hi"})
        bridge.assert_not_called(); claude.assert_not_called(); popen.assert_not_called()

    def test_notification_does_not_change_draft(self):
        draft = self.review()
        before = dict(self.server.MAIL_DRAFT)
        self.server.BUS.pub(t="notification", text="A notice")
        self.assertEqual(self.server.MAIL_DRAFT, before)

    def test_send_source_has_one_guard_and_one_send_route(self):
        source = (Path(__file__).resolve().parent.parent / "app" / "server.py").read_text()
        tree = ast.parse(source)
        for name in ("click_only", "send_detail", "sends_log"):
            self.assertEqual(sum(isinstance(n, ast.FunctionDef) and n.name == name for n in tree.body), 1)
        send_lists = []
        for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            for node in ast.walk(fn):
                if isinstance(node, ast.List) and any(isinstance(v, ast.Constant) and v.value == "send" for v in node.elts):
                    send_lists.append(fn.name)
        self.assertEqual(send_lists, ["mail_send"])

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
