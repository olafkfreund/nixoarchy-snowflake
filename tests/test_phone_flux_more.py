"""#100: more of Flux from Nixi's phone feature. Step 1: the client, the dispatch guard, strings and phrases."""

import sys
import unittest
from pathlib import Path
from unittest import mock

import nixi_env  # noqa: F401
from test_phone import StubPhone, dev, device, snapshot
from test_speakable import REPO_ROOT, _ServerEnv

sys.path.insert(0, str(REPO_ROOT / "app"))
import phone  # noqa: E402

NEW_KEYS = ("phone.note_sent", "phone.note_update", "phone.note_unsure", "phone.note_offline", "phone.nothing_running",
            "phone.when_done_set", "phone.when_done_button", "phone.turn_done", "phone.turn_stopped", "phone.turn_failed",
            "phone.offline_hint", "phone.fingerprint", "phone.open_button", "phone.thread_title", "phone.thread_empty",
            "phone.notes_title", "phone.notes_empty", "phone.notify_none", "phone.notify_changed", "phone.notify_sent",
            "phone.notify_draft_title")


class ClientTest(unittest.TestCase):
    def test_methods_are_exactly_the_allowed_set(self):
        self.assertEqual(phone.Phone.METHODS, {"ring", "share.url", "share.text", "share.files", "clipboard.send",
                                               "sms.refresh", "sms.send", "dnd.set", "notify.send", "sms.thread",
                                               "notification.reply"})

    def test_devices_carry_fingerprint_and_ip(self):
        p = phone.Phone()
        d = device()
        d.update(fingerprint="ABCD", ip="10.0.0.2")
        p.snap = snapshot([d])
        row = p.devices()[0]
        self.assertEqual((row["fingerprint"], row["ip"]), ("ABCD", "10.0.0.2"))

    def test_notifications_rev_follows_text_and_reply_id_and_hides_reply_id(self):
        p = phone.Phone()

        def rows(text="hi", reply="r1", paired=True):
            d = device(paired=paired)
            d["notifications"] = [{"id": "n1", "app": "Chat", "title": "Ann", "text": text, "time": 5, "replyId": reply,
                                   "actions": ["x"]}]
            p.snap = snapshot([d])
            return p.notifications("pixel")

        a, b, c = rows(), rows(text="other"), rows(reply="r2")
        self.assertEqual(len({a[0]["rev"], b[0]["rev"], c[0]["rev"]}), 3)
        self.assertEqual(rows()[0]["rev"], a[0]["rev"])
        # field boundaries are unambiguous even with NUL inside a field
        def nul(title, text):
            d = device()
            d["notifications"] = [{"id": "n1", "app": "Chat", "title": title, "text": text, "replyId": "r"}]
            p.snap = snapshot([d])
            return p.notifications("pixel")[0]["rev"]
        self.assertNotEqual(nul("Ann\0B", "C"), nul("Ann", "B\0C"))
        self.assertEqual(set(a[0]), {"id", "app", "title", "text", "time", "can_reply", "rev"})
        self.assertTrue(a[0]["can_reply"])
        self.assertFalse(rows(reply="")[0]["can_reply"])
        self.assertEqual(rows(paired=False), [])
        self.assertEqual(p.notifications("nope"), [])


class PhraseTest(_ServerEnv):
    def setUp(self):
        self.q = self.server.quick
        self.addCleanup(setattr, self.server.lang, "active", self.server.lang.active)

    def h(self, text):
        return self.q.handle(text)

    def test_when_done_is_not_a_note(self):
        self.assertEqual(self.h("tell my phone when this is done"), {"phone": {"do": "when_done", "name": None}})
        self.assertEqual(self.h("Nixi, ping my phone when you're done!")["phone"]["do"], "when_done")

    def test_note_keeps_case_and_is_bounded(self):
        text = ("Ab" * 100)
        self.assertEqual(self.h("tell my phone " + text), {"phone": {"do": "note", "text": text}})
        self.assertNotEqual((self.h("tell my phone " + text + "x") or {}).get("phone", {}).get("do"), "note")
        self.assertEqual(self.h("send my phone a note: Buy Milk"), {"phone": {"do": "note", "text": "Buy Milk"}})

    def test_notes_and_notify_reply(self):
        self.assertEqual(self.h("show my phone notifications"), {"phone": {"do": "notes"}})
        self.assertEqual(self.h("answer Ann on my phone: On my way"),
                         {"phone": {"do": "notify_reply", "text": "On my way", "name": "Ann"}})

    def test_session_send_still_wins(self):
        self.assertEqual(self.h("tell the build session: x"), {"session_send": ["build", "x"]})

    def test_each_language_parses(self):
        for code, say in (("nb", "si fra til telefonen min når dette er ferdig"), ("pl", "powiedz mojemu telefonowi, gdy skończysz")):
            self.server.lang.active = code
            self.assertEqual(self.h(say), {"phone": {"do": "when_done", "name": None}}, code)
        self.server.lang.active = "nb"
        self.assertEqual(self.h("vis varslene på telefonen min"), {"phone": {"do": "notes"}})
        self.assertEqual(self.h("svar Ola på telefonen min: Ja")["phone"]["do"], "notify_reply")
        self.assertEqual(self.h("si til telefonen min Hei")["phone"], {"do": "note", "text": "Hei"})
        self.server.lang.active = "pl"
        self.assertEqual(self.h("pokaż powiadomienia z mojego telefonu"), {"phone": {"do": "notes"}})
        self.assertEqual(self.h("odpowiedz Ola na moim telefonie: Tak")["phone"]["do"], "notify_reply")
        self.assertEqual(self.h("powiedz mojemu telefonowi Cześć")["phone"], {"do": "note", "text": "Cześć"})

    def test_every_new_key_exists_in_all_languages(self):
        for code in ("en", "nb", "pl"):
            lines = self.server.lang.load(code)["lines"]
            for k in NEW_KEYS:
                self.assertIn(k, lines, (code, k))


class DispatchGuardTest(_ServerEnv):
    def test_new_actions_never_reach_phone_share(self):
        s = self.server
        saved = dict(s.CFG)
        self.addCleanup(lambda: (s.CFG.clear(), s.CFG.update(saved)))
        s.CFG["phone_on"] = True
        with mock.patch.object(s, "Phone", StubPhone([dev("pixel", "Pixel")])), mock.patch.object(s, "phone_share") as share:
            for do in ("note", "when_done", "notes", "notify_reply", "bogus"):
                self.assertIsNone(s.phone_quick({"do": do, "text": "x", "name": None}), do)
            share.assert_not_called()


if __name__ == "__main__":
    unittest.main()
