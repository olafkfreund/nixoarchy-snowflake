"""#100: more of Flux from Nixi's phone feature. Steps 1–2: client, phrases and notes."""

import io
import json
import sys
import threading
import time
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
            for do in ("bogus",):
                self.assertIsNone(s.phone_quick({"do": do, "text": "x", "name": None}), do)
            share.assert_not_called()


class NoteTest(_ServerEnv):
    def setUp(self):
        s = self.s = self.server
        self.saved = (dict(s.CFG), s.PHONE_GEN, s.PHONE_WHEN_DONE, s.ST.active_turn)
        s.CFG["phone_on"] = True
        self.p = StubPhone([dev("pixel", "Pixel", can=())])
        self.patcher = mock.patch.object(s, "Phone", self.p)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(self.restore)
        s.STAGES.close()

    def restore(self):
        s = self.s
        s.CFG.clear()
        s.CFG.update(self.saved[0])
        s.PHONE_GEN, s.PHONE_WHEN_DONE, s.ST.active_turn = self.saved[1:]
        s.STAGES.close()

    def test_note_now_and_errors(self):
        s = self.s
        self.assertEqual(s.phone_quick({"do": "note", "text": "Buy Milk"})["say"], s.lang.t("phone.note_sent"))
        self.assertEqual(self.p.calls, [("notify.send", {"device": "pixel", "title": "Nixi", "body": "Buy Milk"})])
        for exc, key in ((RuntimeError("not_supported"), "phone.note_update"), (RuntimeError("other"), "phone.failed"),
                         (TimeoutError(), "phone.note_unsure"), (phone.NotSent(), "phone.not_running")):
            self.p.errors["notify.send"] = exc
            before = len(self.p.calls)
            self.assertEqual(s.phone_note(self.p.devices()[0], "x", s.PHONE_GEN)["say"], s.lang.t(key))
            self.assertEqual(len(self.p.calls), before + 1)
        self.p.errors.clear()
        s.PHONE_GEN += 1
        self.assertEqual(s.phone_note(self.p.devices()[0], "x", s.PHONE_GEN - 1)["mood"], "sad")
        self.assertEqual(len(self.p.calls), 5)

    def test_reset_waits_for_note_past_its_check(self):
        s = self.s
        inside, go = threading.Event(), threading.Event()
        def call(method, **kw):
            inside.set()
            go.wait(2)
            self.p.calls.append((method, kw))
        with mock.patch.object(self.p, "call", side_effect=call):
            t = threading.Thread(target=s.phone_note, args=(self.p.devices()[0], "x", s.PHONE_GEN))
            t.start()
            self.assertTrue(inside.wait(2))
            got = []
            with mock.patch.object(self.p, "stop", side_effect=lambda: got.append(len(self.p.calls))):
                r = threading.Thread(target=s.phone_reset)
                r.start()
                time.sleep(0.1)
                self.assertEqual(got, [])
                go.set()
                t.join(2)
                r.join(2)
            self.assertEqual(got, [1])

    def test_chooser_not_published_after_reset_and_failed_send_is_told(self):
        s = self.s
        self.p._devices.append(dev("ipad", "iPad"))
        with mock.patch.object(s, "BRIDGED", True), mock.patch.object(s, "stages_on", return_value=True), mock.patch.object(s.BUS, "pub") as pub:
            r = s.phone_pick_card(self.p.devices(), "note", {"gen": s.PHONE_GEN - 1, "text": "x"}, s.PHONE_GEN - 1)
            self.assertEqual(r["mood"], "sad")
            self.assertIsNone(s.STAGES.current())
            pub.assert_not_called()
            self.p.errors["notify.send"] = TimeoutError()
            s.phone_note_say(self.p.devices()[0], "x", s.PHONE_GEN)
            pub.assert_called_once_with(t="note", text=s.lang.t("phone.note_unsure"))
            pub.reset_mock()
            s.phone_note_say(self.p.devices()[0], "x", s.PHONE_GEN - 1)
            pub.assert_not_called()

    def test_chooser_token_hides_text_and_turn_and_rejects_stale_turn(self):
        s = self.s
        self.p._devices.append(dev("ipad", "iPad"))
        with mock.patch.object(s, "BRIDGED", True), mock.patch.object(s, "stages_on", return_value=True), mock.patch.object(s.BUS, "pub"):
            s.phone_quick({"do": "note", "text": "Private note"})
            page = s.STAGES.current()
            self.assertNotIn("Private note", json.dumps(page))
            self.assertNotIn("pending", page)
            self.assertEqual(set(page["devices"][0]), {"name", "pick"})
            h = s.Handler.__new__(s.Handler)
            h.path = "/api/phone/pick"
            h.headers = {"X-Nixi-Token": s.TOKEN}
            h._host_ok = lambda: True
            h._body = lambda: json.dumps({"token": page["devices"][1]["pick"], "device": "pixel"}).encode()
            h._json = mock.Mock()
            h.do_POST()
            r, code = h._json.call_args.args
            self.assertEqual((r["ok"], code), (True, 200))
            self.assertEqual(self.p.calls[-1], ("notify.send", {"device": "ipad", "title": "Nixi", "body": "Private note"}))
            s.ST.active_turn = 12
            s.phone_quick({"do": "when_done"})
            token = s.STAGES.current()["devices"][0]["pick"]
            s.ST.active_turn = 13
            r, _ = s.phone_pick_note(token)
            self.assertEqual(r["say"], s.lang.t("phone.nothing_running"))
            self.assertIsNone(s.PHONE_WHEN_DONE)

    def test_when_done_outcomes_and_cancellation(self):
        s = self.s
        self.assertEqual(s.phone_when_done(self.p.devices()[0])["say"], s.lang.t("phone.nothing_running"))
        for outcome in ("done", "stopped", "failed"):
            s.ST.active_turn = 5
            s.phone_when_done(self.p.devices()[0])
            slot = s.PHONE_WHEN_DONE
            sent = threading.Event()
            def call(method, **kw):
                self.p.calls.append((method, kw))
                sent.set()
            with mock.patch.object(self.p, "call", side_effect=call):
                s.phone_fire(slot, outcome)
                self.assertTrue(sent.wait(2))
            self.assertEqual(self.p.calls[-1][1]["body"], s.lang.t("phone.turn_" + outcome))
        slot = {**slot, "at": time.monotonic() - 1800}
        s.phone_fire(slot, "done")
        self.assertEqual(len(self.p.calls), 3)
        slot["at"] = time.monotonic()
        self.p._devices[0]["online"] = False
        with mock.patch.object(s.BUS, "pub") as pub:
            s.phone_fire(slot, "done")
            pub.assert_called_once()
        self.p._devices.clear()
        s.phone_fire(slot, "done")
        s.PHONE_GEN += 1
        self.p._devices.append(dev("pixel", "Pixel"))
        s.phone_fire(slot, "done")
        self.assertEqual(len(self.p.calls), 3)

    def test_reset_before_queued_send_drops_it(self):
        s = self.s
        s.ST.active_turn = 5
        s.phone_when_done(self.p.devices()[0])
        slot = s.PHONE_WHEN_DONE
        queued = []
        def thread(*, target, args, daemon):
            return mock.Mock(start=lambda: queued.append((target, args)))
        with mock.patch.object(s.threading, "Thread", side_effect=thread):
            s.phone_fire(slot, "done")
        self.assertEqual(len(queued), 1)
        s.PHONE_GEN += 1
        queued[0][0](*queued[0][1])
        self.assertEqual(self.p.calls, [])

    def test_ask_tracks_turn_and_fires_once(self):
        s = self.s
        h = s.Handler.__new__(s.Handler)
        h.wfile = io.BytesIO()
        h.send_response = h.send_header = h.end_headers = mock.Mock()
        h._body = lambda: b'{"prompt":"hello"}'
        h._json = mock.Mock()
        for event, expected in (({"t": "result", "is_error": False}, "done"),
                                ({"t": "stopped"}, "stopped"), ({"t": "error"}, "failed")):
            seen = []
            def bridge(prompt, emit, *_):
                seen.append(s.ST.active_turn)
                s.phone_when_done(self.p.devices()[0])
                emit(**event)
            with mock.patch.object(s, "BRIDGED", True), mock.patch.object(s, "run_bridge", side_effect=bridge), \
                 mock.patch.object(s, "phone_fire") as fire, mock.patch.object(s, "hist_add"), \
                 mock.patch.object(s, "pick_auto", return_value=None), mock.patch.dict(s.CFG, {"auto_compact": False}):
                h.ask()
            self.assertIsNotNone(seen[0])
            self.assertIsNone(s.ST.active_turn)
            self.assertIsNone(s.ST.send_watch)
            self.assertIsNone(s.PHONE_WHEN_DONE)
            self.assertEqual(fire.call_args.args[1], expected)

    def test_page_and_window_token_routes(self):
        page = (REPO_ROOT / "app/static/index.html").read_text()
        self.assertLess(page.index('<div id="chip"></div>'), page.index('<button id="phoneDone"'))
        self.assertIn("'/api/phone/pick'", page)
        self.assertIn("'/api/phone/when-done'", page)
        self.assertNotIn("/api/phone/pick", self.s.TOOL_PATHS)
        self.assertNotIn("/api/phone/when-done", self.s.TOOL_PATHS)
        h = self.s.Handler.__new__(self.s.Handler)
        h.headers = {"X-Nixi-Token": self.s.TOOL_TOKEN}
        h._host_ok = lambda: True
        h._json = mock.Mock()
        for route in ("/api/phone/pick", "/api/phone/when-done"):
            h.path = route
            h.do_POST()
            self.assertEqual(h._json.call_args.args[1], 403)
        h.headers = {"X-Nixi-Token": self.s.TOKEN}
        h._body = lambda: b"{}"
        self.s.ST.active_turn = 44
        h.path = "/api/phone/when-done"
        h.do_POST()
        self.assertTrue(h._json.call_args.args[0]["ok"])
        self.assertEqual(self.s.PHONE_WHEN_DONE["turn"], 44)

    def test_unpair_clears_slot_even_if_device_returns(self):
        s = self.s
        s.ST.active_turn = 8
        s.phone_when_done(self.p.devices()[0])
        self.p._devices.clear()
        with mock.patch.object(s, "phone_battery_check"), mock.patch.object(s, "phone_call_sync"), \
             mock.patch.object(s, "phone_approvals_sync"), mock.patch.object(s, "phone_pub"):
            s.phone_state()
        self.assertIsNone(s.PHONE_WHEN_DONE)
        self.p._devices.append(dev("pixel", "Pixel"))

    def test_arm_and_finish_are_atomic(self):
        s = self.s
        s.ST.active_turn = 9
        start = threading.Event()
        armed = threading.Event()
        def arm():
            start.wait(2)
            s.phone_when_done(self.p.devices()[0])
            armed.set()
        t = threading.Thread(target=arm)
        t.start()
        with s.WATCH_LOCK:
            start.set()
            s.ST.active_turn = None
        self.assertTrue(armed.wait(2))
        t.join(2)
        self.assertIsNone(s.PHONE_WHEN_DONE)


class PhoneTabTest(_ServerEnv):
    def setUp(self):
        s = self.s = self.server
        saved = dict(s.CFG)
        self.addCleanup(lambda: (s.CFG.clear(), s.CFG.update(saved)))
        s.CFG["phone_on"] = True
        d1 = dev("pixel", "Pixel 7 +4790000000 code 123456")
        d1.update(fingerprint="ab:cd:ef:01:23", ip="10.0.0.5", notifications=[{"text": "secret text"}])
        d2 = dev("tab", "Tab", online=False, last=time.time() - 120)
        self.p = StubPhone([d1, d2])
        patcher = mock.patch.object(s, "Phone", self.p)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_rows_have_exactly_the_listed_keys_and_no_content(self):
        rows = self.s.phone_devices()
        keys = {"name", "online", "last_seen_ago", "charge", "charging", "fingerprint", "ip", "status", "hint"}
        self.assertTrue(all(set(r) == keys for r in rows))
        self.assertEqual((rows[0]["fingerprint"], rows[0]["ip"]), ("abcd ef01 23", "10.0.0.5"))
        blob = json.dumps(rows)
        for secret in ("secret text", "4790000000", "123456"):
            self.assertNotIn(secret, blob)

    def test_hint_only_when_offline(self):
        rows = self.s.phone_devices()
        self.assertEqual((rows[0]["hint"], rows[1]["hint"]), ("", self.s.lang.t("phone.offline_hint")))
        self.assertTrue(rows[1]["last_seen_ago"])

    def test_status_is_translated(self):
        rows = self.s.phone_devices()
        self.assertEqual(rows[0]["status"], self.s.lang.t("phone.online"))
        self.assertNotEqual(rows[1]["status"], rows[0]["status"])

    def test_pub_dropped_when_reset_runs_meanwhile(self):
        s = self.s
        sent = []
        orig = s.phone_devices
        def devs():
            r = orig()
            s.PHONE_GEN += 1                  # a reset lands after the rows were built
            return r
        with mock.patch.object(s, "phone_devices", devs), mock.patch.object(s.BUS, "pub", lambda **k: sent.append(k)):
            s.phone_pub()
        self.assertEqual(sent, [])

    def test_empty_when_off_or_disconnected(self):
        self.s.CFG["phone_on"] = False
        self.assertEqual(self.s.phone_devices(), [])
        self.s.CFG["phone_on"] = True
        self.p.connected = False
        self.assertEqual(self.s.phone_devices(), [])


class ThreadTest(_ServerEnv):
    def setUp(self):
        s = self.s = self.server
        saved = dict(s.CFG), s.PHONE_GEN
        self.addCleanup(self.restore, saved)
        s.CFG["phone_on"] = True
        self.p = StubPhone([dev("pixel", "Pixel", can=("sms",))])
        self.p.threads = [{"device": "pixel", "address": "+4790000000", "name": "Kari", "last": "hi", "time": 1, "thread": 12}]
        self.p.results["sms.thread"] = {"messages": [
            {"name": "Verification", "body": "123456", "outgoing": False, "time": 5},
            {"name": "Me", "body": "ok", "outgoing": True, "time": 6}]}
        for pt in (mock.patch.object(s, "Phone", self.p), mock.patch.object(s, "BRIDGED", True),
                   mock.patch.object(s, "stages_on", lambda: True), mock.patch.object(s.BUS, "pub"),
                   mock.patch.object(s.Speaker, "available", lambda: False)):
            pt.start()
            self.addCleanup(pt.stop)
        s.STAGES.close()

    def restore(self, saved):
        self.s.CFG.clear()
        self.s.CFG.update(saved[0])
        self.s.PHONE_GEN = saved[1]
        self.s.STAGES.close()

    def open_token(self):
        self.s.phone_read_messages()
        page = self.s.STAGES.current()
        self.assertNotIn("thread", json.dumps(page["rows"]))
        return page["rows"][0]["open"]

    def test_thread_comes_from_token_scrubbed_and_hidden_ids(self):
        s = self.s
        r, code = s.phone_thread_open(self.open_token())
        self.assertEqual((code, r["ok"]), (200, True))
        self.assertEqual(self.p.calls[-1], ("sms.thread", {"device": "pixel", "thread": 12}))
        page = s.STAGES.current()
        self.assertEqual(page["kind"], "phone_thread")
        self.assertTrue(page["from_phone"])
        blob = json.dumps(page)
        for hidden in ("123456", "pixel", "+4790000000"):
            self.assertNotIn(hidden, blob)
        self.assertEqual([m["outgoing"] for m in page["messages"]], [False, True])
        self.assertEqual(s.STAGES.get(page["reply"])[0], "phone_reply")
        self.assertTrue(s.phone_on_screen())

    def test_bad_token_and_flux_error(self):
        s = self.s
        self.assertEqual(s.phone_thread_open("nope")[1], 410)
        tok = self.open_token()
        self.p.errors["sms.thread"] = RuntimeError("x")
        r, _ = s.phone_thread_open(tok)
        self.assertEqual(r["say"], s.lang.t("phone.failed"))
        self.assertEqual(s.STAGES.current()["kind"], "phone_sms")

    def test_late_reply_after_reset_is_not_put_and_reset_closes(self):
        s = self.s
        tok = self.open_token()
        orig = self.p.call

        def call(method, **kw):
            r = orig(method, **kw)
            s.PHONE_GEN += 1
            return r
        self.p.call = call
        r, _ = s.phone_thread_open(tok)
        self.assertFalse(r["ok"])
        self.assertEqual(s.STAGES.current()["kind"], "phone_sms")
        self.p.call = orig
        s.PHONE_GEN -= 1
        s.phone_thread_open(tok)
        self.assertEqual(s.STAGES.current()["kind"], "phone_thread")
        s.phone_reset()
        self.assertIsNone(s.STAGES.current())

    def test_late_reply_does_not_replace_newer_stage(self):
        s = self.s
        tok = self.open_token()
        orig = self.p.call

        def call(method, **kw):
            r = orig(method, **kw)
            s.STAGES.put({"v": 1, "kind": "phone_draft", "from_phone": True})
            return r
        self.p.call = call
        r, code = s.phone_thread_open(tok)
        self.assertEqual((code, r["ok"]), (410, False))
        self.assertEqual(s.STAGES.current()["kind"], "phone_draft")

    def test_thread_stage_is_published_under_the_phone_lock(self):
        s = self.s
        held = []
        s.BUS.pub.side_effect = lambda **kw: held.append(s.PHONE_LOCK.locked())
        s.phone_thread_open(self.open_token())
        self.assertIn(True, held[-1:])

    def test_route_ignores_body_ids_and_tool_token_refused(self):
        s = self.s
        tok = self.open_token()
        self.assertNotIn("/api/phone/thread", s.TOOL_PATHS)
        h = s.Handler.__new__(s.Handler)
        h._host_ok = lambda: True
        h._json = mock.Mock()
        h.path = "/api/phone/thread"
        h.headers = {"X-Nixi-Token": s.TOOL_TOKEN}
        h.do_POST()
        self.assertEqual(h._json.call_args.args[1], 403)
        h.headers = {"X-Nixi-Token": s.TOKEN}
        h._body = lambda: json.dumps({"token": tok, "device": "evil", "thread": 99}).encode()
        h.do_POST()
        self.assertEqual(self.p.calls[-1], ("sms.thread", {"device": "pixel", "thread": 12}))

    def test_page_source(self):
        page = (REPO_ROOT / "app/static/index.html").read_text()
        i = page.index("function stageText(ev){")
        self.assertIn("if(ev.from_phone) return '';", page[i:i + 80])
        self.assertIn("'/api/phone/thread'", page)


class NotificationTest(_ServerEnv):
    def setUp(self):
        s = self.s = self.server
        self.saved = dict(s.CFG), s.PHONE_GEN, s.PHONE_NOTE_DRAFT
        s.CFG["phone_on"] = True
        self.p = StubPhone([dev("pixel", "Pixel"), dev("tab", "Tab", online=False)])
        self.rows = {"pixel": [{"id": "n1", "app": "Chat", "title": "Verification", "text": "123456", "time": 3,
                                "can_reply": True, "rev": "a"},
                               {"id": "n2", "app": "Chat", "title": "Ann", "text": "Hi", "time": 2,
                                "can_reply": True, "rev": "b"}],
                     "tab": [{"id": "n3", "app": "Chat", "title": "Ann", "text": "Offline", "time": 1,
                              "can_reply": True, "rev": "c"}]}
        self.p.notifications = lambda device: self.rows.get(device, [])
        for pt in (mock.patch.object(s, "Phone", self.p), mock.patch.object(s, "BRIDGED", True),
                   mock.patch.object(s, "stages_on", lambda: True), mock.patch.object(s.BUS, "pub")):
            pt.start()
            self.addCleanup(pt.stop)
        s.STAGES.close()
        self.addCleanup(self.restore)

    def restore(self):
        s = self.s
        s.CFG.clear()
        s.CFG.update(self.saved[0])
        s.PHONE_GEN, s.PHONE_NOTE_DRAFT = self.saved[1:]
        s.STAGES.close()

    def draft(self, row=0):
        self.s.phone_quick({"do": "notes"})
        page = self.s.STAGES.current()
        self.assertEqual(page["kind"], "phone_notes")
        self.assertTrue(self.s.phone_on_screen())
        self.assertTrue(self.s.phone_note_draft(page["rows"][row]["reply"])["ok"])
        return self.s.STAGES.current()["draft"]

    def test_list_draft_send_and_scrub(self):
        s = self.s
        s.phone_quick({"do": "notes"})
        listing = s.STAGES.current()
        self.assertEqual(len(listing["rows"]), 3)  # offline devices are still listed
        self.assertNotIn("123456", json.dumps(listing))
        self.assertNotIn("pixel", json.dumps(listing))
        draft = self.draft()
        page = s.STAGES.current()
        self.assertEqual(page["kind"], "phone_note_draft")
        self.assertTrue(page["from_phone"])
        self.assertNotIn("123456", str(s.BUS.pub.call_args_list))
        self.assertNotIn("pixel", json.dumps(page))
        self.assertEqual(s.phone_note_reply(draft, "Yes", True), {"ok": True, "say": s.lang.t("phone.notify_sent")})
        self.assertEqual(self.p.calls[-1], ("notification.reply", {"device": "pixel", "id": "n1", "message": "Yes"}))
        self.assertFalse(s.phone_note_reply(draft, "Again", True)["ok"])
        self.assertEqual(len(self.p.calls), 1)

    def test_dictated_one_and_several(self):
        s = self.s
        s.phone_quick({"do": "notify_reply", "name": "verification", "text": "Ready"})
        self.assertEqual(s.STAGES.current()["text"], "Ready")
        draft = s.STAGES.current()["draft"]
        self.assertTrue(s.phone_note_reply(draft, "Ready", True)["ok"])
        s.phone_quick({"do": "notify_reply", "name": "ann", "text": "On my way"})
        page = s.STAGES.current()
        self.assertEqual(len(page["rows"]), 2)
        self.assertNotIn("On my way", json.dumps(page))
        self.assertTrue(s.phone_note_draft(page["rows"][0]["reply"])["ok"])
        self.assertEqual(s.STAGES.current()["text"], "On my way")
        self.assertTrue(s.phone_note_reply(s.STAGES.current()["draft"], "On my way", True)["ok"])
        self.assertEqual(s.phone_quick({"do": "notify_reply", "name": "Nobody", "text": "Hi"})["say"], s.lang.t("phone.notify_none"))

    def test_parallel_clicks_and_changed_or_expired(self):
        s = self.s
        draft = self.draft(1)
        results = []
        threads = [threading.Thread(target=lambda: results.append(s.phone_note_reply(draft, "Hi", True))) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(sum(r["ok"] for r in results), 1)
        self.assertEqual(len(self.p.calls), 1)
        for change in (lambda: self.rows["pixel"][1].update(rev="new"),
                       lambda: self.rows["pixel"].pop(1)):
            draft = self.draft(1)
            change()
            self.assertEqual(s.phone_note_reply(draft, "Hi", True)["say"], s.lang.t("phone.notify_changed"))
            self.assertIsNone(s.PHONE_NOTE_DRAFT)
            self.rows["pixel"] = [{"id": "n1", "app": "Chat", "title": "Verification", "text": "123456", "time": 3,
                                   "can_reply": True, "rev": "a"}, {"id": "n2", "app": "Chat", "title": "Ann", "text": "Hi", "time": 2,
                                   "can_reply": True, "rev": "b"}]
        draft = self.draft(1)
        s.PHONE_NOTE_DRAFT["created"] -= 600
        self.assertFalse(s.phone_note_reply(draft, "Hi", True)["ok"])
        self.assertEqual(len(self.p.calls), 1)

    def test_failure_restore_bounds_and_reset(self):
        s = self.s
        draft = self.draft(1)
        for text in ("", "  ", "x" * 1001):
            self.assertFalse(s.phone_note_reply(draft, text, True)["ok"])
            draft = self.draft(1)
        self.p.errors["notification.reply"] = phone.NotSent("offline")
        self.assertFalse(s.phone_note_reply(draft, "Hi", True)["ok"])
        self.assertEqual(s.PHONE_NOTE_DRAFT["id"], draft)
        self.p.errors["notification.reply"] = TimeoutError()
        self.assertFalse(s.phone_note_reply(draft, "Hi", True)["ok"])
        self.assertIsNone(s.PHONE_NOTE_DRAFT)
        self.draft(1)
        s.phone_reset()
        self.assertIsNone(s.PHONE_NOTE_DRAFT)
        self.assertIsNone(s.STAGES.current())

    def test_stale_draft_id_keeps_current_draft(self):
        s = self.s
        draft = self.draft(1)
        self.assertFalse(s.phone_note_reply("old-id", "Hi", True)["ok"])
        self.assertEqual(s.PHONE_NOTE_DRAFT["id"], draft)
        self.assertTrue(s.phone_note_reply(draft, "Hi", True)["ok"])

    def test_reset_waits_for_reply_past_its_check(self):
        s = self.s
        draft = self.draft(1)
        inside, go = threading.Event(), threading.Event()
        def call(method, **kw):
            inside.set()
            go.wait(2)
            self.p.calls.append((method, kw))
        with mock.patch.object(self.p, "call", side_effect=call):
            t = threading.Thread(target=s.phone_note_reply, args=(draft, "Hi", True))
            t.start()
            self.assertTrue(inside.wait(2))
            got = []
            with mock.patch.object(self.p, "stop", side_effect=lambda: got.append(len(self.p.calls))):
                r = threading.Thread(target=s.phone_reset)
                r.start()
                time.sleep(0.1)
                self.assertEqual(got, [])
                go.set()
                t.join(2)
                r.join(2)
            self.assertEqual(got, [1])

    def test_list_is_newest_ten_per_device_and_offline_cannot_send(self):
        s = self.s
        self.rows["pixel"] = [{"id": str(i), "app": "Chat", "title": "Ann", "text": str(i),
                               "time": i, "can_reply": True, "rev": str(i)} for i in range(12)]
        s.phone_quick({"do": "notes"})
        self.assertEqual([r["text"] for r in s.STAGES.current()["rows"][:10]], [str(i) for i in range(11, 1, -1)])
        draft = self.draft(10)
        self.assertEqual(s.phone_note_reply(draft, "Hi", True)["say"], s.lang.t("phone.notify_changed"))
        self.assertEqual(self.p.calls, [])

    def test_window_routes_and_page(self):
        s = self.s
        self.assertNotIn("/api/phone/note-draft", s.TOOL_PATHS)
        self.assertNotIn("/api/phone/note-reply", s.TOOL_PATHS)
        h = s.Handler.__new__(s.Handler)
        h._host_ok = lambda: True
        h._json = mock.Mock()
        h.headers = {"X-Nixi-Token": s.TOOL_TOKEN}
        for route in ("/api/phone/note-draft", "/api/phone/note-reply"):
            h.path = route
            h.do_POST()
            self.assertEqual(h._json.call_args.args[1], 403)
        s.phone_quick({"do": "notes"})
        token = s.STAGES.current()["rows"][1]["reply"]
        h.headers = {"X-Nixi-Token": s.TOKEN, "X-Nixi-Click": "test"}
        h._body = lambda: json.dumps({"token": token}).encode()
        h.path = "/api/phone/note-draft"
        h.do_POST()
        self.assertTrue(h._json.call_args.args[0]["ok"])
        h._body = lambda: json.dumps({"draft": s.STAGES.current()["draft"], "text": "Hi"}).encode()
        h.path = "/api/phone/note-reply"
        with mock.patch.object(s, "click_ok", return_value=True):
            h.do_POST()
        self.assertTrue(h._json.call_args.args[0]["ok"])
        self.assertEqual(self.p.calls[-1], ("notification.reply", {"device": "pixel", "id": "n2", "message": "Hi"}))
        page = (REPO_ROOT / "app/static/index.html").read_text()
        self.assertIn("'/api/phone/note-draft'", page)
        self.assertIn("'/api/phone/note-reply'", page)
        self.assertIn("CLICKKEY.hdr()", page[page.index('function stagePhoneNoteDraft'):page.index('function stagePhoneMissed')])


if __name__ == "__main__":
    unittest.main()
