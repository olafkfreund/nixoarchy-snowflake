"""WhatsApp server state and click boundaries, under a disposable HOME."""

import io
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import nixi_env

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))


class FakeWA:
    def __init__(self, run):
        self.run = str(run)
        self.max_file = 1024
        self.boot = "boot-1"
        self.outcome = "sent"
        self.before_send = None
        self.calls = []
        self.news = []
        (run / "stage").mkdir(parents=True)
        (run / "dl").mkdir()

    def status(self):
        return {"state": "ready", "boot": self.boot}, self.boot

    def chats(self, q="", limit=20):
        return [{"jid": "1@s.whatsapp.net", "name": "One"}], self.boot

    def thread(self, jid, limit=100, before=0):
        return [{"id": "m1", "text": "hello", "kind": "text"}], self.boot

    def new(self, after=0):
        return [row for row in self.news if row["seq"] > after], self.boot

    def send(self, jid, text, boot):
        self.calls.append(("send", jid, text, boot))
        if self.before_send:
            self.before_send()
        if boot != self.boot or self.outcome == "not_sent":
            raise self.not_sent("stale", self.boot)
        if self.outcome == "unknown":
            raise self.unknown("lost", self.boot)
        return {"result": "sent"}, self.boot

    def send_file(self, jid, staged, caption, name, boot):
        self.calls.append(("file", jid, staged, name, boot))
        if self.before_send:
            self.before_send()
        if boot != self.boot or self.outcome == "not_sent":
            raise self.not_sent("stale", self.boot)
        if self.outcome == "unknown":
            raise self.unknown("lost", self.boot)
        (Path(self.run) / "stage" / staged).unlink()
        return {"result": "sent"}, self.boot

    def stage(self, stream, n):
        name = ("a" if not list((Path(self.run) / "stage").iterdir()) else "b") * 24
        with open(Path(self.run) / "stage" / name, "xb") as out:
            left = n
            while left:
                chunk = stream.read(min(left, 8))
                if not chunk:
                    raise ValueError("short upload")
                out.write(chunk)
                left -= len(chunk)
        return name

    def download(self, jid, id):
        name = "1-0123456789abcdef.bin"
        (Path(self.run) / "dl" / name).write_bytes(b"new")
        return {"file": name, "name": "same.bin"}, self.boot

    def fetch(self, file, dest_dir=None, name=None):
        from whatsapp import WhatsApp
        return WhatsApp(self.run).fetch(file, dest_dir=self.dest, name=name)

    def forget(self, boot):
        self.calls.append(("forget", boot))
        return {"ok": True}, self.boot


class WhatsAppServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_env = os.environ.copy()
        cls.home = Path(tempfile.mkdtemp(prefix="nixi-wa-test-"))
        for k, part in (("HOME", ""), ("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
            path = cls.home / part
            path.mkdir(exist_ok=True)
            os.environ[k] = str(path)
        os.environ["XDG_RUNTIME_DIR"] = nixi_env.run_dir()
        import server
        cls.s = server
        nixi_env.check_floor_path(server.FLOOR.path)
        assert server.CONF_PATH.is_relative_to(cls.home)

    @classmethod
    def tearDownClass(cls):
        os.environ.clear()
        os.environ.update(cls.old_env)
        shutil.rmtree(cls.home)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wa-case-", dir=self.home))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.fake = FakeWA(self.tmp / "run")
        self.fake.dest = self.tmp / "Downloads" / "WhatsApp"
        self.fake.not_sent = self.s.whatsapp.NotSent
        self.fake.unknown = self.s.whatsapp.Unknown
        self.patches = [mock.patch.object(self.s, "WA", self.fake),
                        mock.patch.object(self.s.Desk, "locked", return_value=False),
                        mock.patch.object(self.s.subprocess, "run"),
                        mock.patch.object(self.s, "WA_CONFIG", {"bridge": True, "unit": "nixi-whatsapp.service"})]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.s.CFG["whatsapp_on"] = True
        self.s.Ambient.locked = self.s.Ambient.meeting = self.s.Ambient.dnd = self.s.Ambient.phone_call = False
        self.s.STAGES.clear()
        self.s.wa_clear("boot-1")
        self.s.CFG["whatsapp_on"] = True

    def draft(self, file=False):
        self.assertTrue(self.s.wa_open()["ok"])
        token = self.s.STAGES.current()["rows"][0]["open"]
        self.assertTrue(self.s.wa_thread(token)["ok"])
        token = self.s.STAGES.current()["file" if file else "reply"]
        self.assertTrue(self.s.wa_draft(token, "wa_file" if file else "wa_draft")["ok"])
        return self.s.STAGES.current()["draft"]

    def test_text_rearm_unknown_and_stale_boot(self):
        d = self.draft()
        self.fake.outcome = "not_sent"
        self.assertEqual(self.s.wa_send(d, "hi", True)["result"], "not_sent")
        self.assertEqual(self.s.WA_DRAFT["id"], d)
        self.fake.outcome = "unknown"
        self.assertEqual(self.s.wa_send(d, "hi", True)["result"], "unknown")
        self.assertIsNone(self.s.WA_DRAFT)
        self.assertIn("May have been sent", self.s.STAGES.current()["error"])
        d = self.draft()
        self.fake.boot = "boot-2"
        self.assertEqual(self.s.wa_send(d, "hi", True)["result"], "not_sent")
        self.assertIsNone(self.s.WA_DRAFT)

    def test_file_stage_replace_expire_and_send(self):
        d = self.draft(file=True)
        self.assertTrue(self.s.wa_stage(d, io.BytesIO(b"abc"), 3, "a.txt")["ok"])
        staged = self.s.WA_FILE["staged"]
        self.assertTrue((Path(self.fake.run) / "stage" / staged).exists())
        self.assertTrue(self.s.wa_stage(d, io.BytesIO(b"four"), 4, "b.txt")["ok"])
        self.assertFalse((Path(self.fake.run) / "stage" / staged).exists())
        staged = self.s.WA_FILE["staged"]
        self.fake.outcome = "not_sent"
        self.assertEqual(self.s.wa_send(d, "", True, True)["result"], "not_sent")
        self.assertEqual(self.s.WA_DRAFT["id"], d)
        self.s.WA_DRAFT["made"] -= 601
        self.s.wa_sweep()
        self.assertFalse((Path(self.fake.run) / "stage" / staged).exists())
        d = self.draft(file=True)
        self.s.wa_stage(d, io.BytesIO(b"abc"), 3, "a.txt")
        self.s.wa_clear()
        self.assertFalse(list((Path(self.fake.run) / "stage").iterdir()))

    def test_file_unknown_and_lock_before_commit(self):
        d = self.draft(file=True)
        self.s.wa_stage(d, io.BytesIO(b"abc"), 3, "a.txt")
        self.fake.outcome = "unknown"
        self.assertEqual(self.s.wa_send(d, "", True, True)["result"], "unknown")
        self.assertIsNone(self.s.WA_DRAFT)
        self.assertFalse(list((Path(self.fake.run) / "stage").iterdir()))
        d = self.draft()
        before = len(self.fake.calls)
        with mock.patch.object(self.s.Desk, "locked", side_effect=[False, True]):
            self.assertFalse(self.s.wa_send(d, "hi", True)["ok"])
        self.assertEqual(len(self.fake.calls), before)

    def test_commit_and_generation(self):
        d = self.draft()
        self.s.wa_clear()
        self.assertFalse(self.s.wa_send(d, "hi", True)["ok"])
        self.assertFalse(self.fake.calls)
        self.s.CFG["whatsapp_on"] = True
        self.s.wa_clear("boot-1")
        d = self.draft()
        self.fake.before_send = lambda: self.s.wa_clear()
        self.assertTrue(self.s.wa_send(d, "hi", True)["ok"])
        self.assertEqual(self.fake.calls[-1][0], "send")

    def test_off_lock_and_restart_on_each_side_of_commit(self):
        for change in ("off", "lock", "restart"):
            for after_commit in (False, True):
                with self.subTest(change=change, after_commit=after_commit):
                    self.s.CFG["whatsapp_on"] = True
                    self.s.Ambient.locked = False
                    self.fake.boot = "boot-1"
                    self.s.wa_clear("boot-1")
                    d = self.draft()
                    before = len(self.fake.calls)

                    def move():
                        if change == "off":
                            self.s.CFG["whatsapp_on"] = False
                            self.s.wa_switch(False)
                        elif change == "lock":
                            self.s.Ambient.locked = True
                            self.s.wa_clear()
                        else:
                            self.fake.boot = "boot-2"
                            self.s.wa_boot("boot-2")

                    if after_commit:
                        self.fake.before_send = move
                        result = self.s.wa_send(d, "hello", True)
                        self.assertEqual(len(self.fake.calls), before + 1)
                        self.assertIn(result["result"], ("sent", "not_sent"))
                    else:
                        calls = 0

                        def locked():
                            nonlocal calls
                            calls += 1
                            if calls == 2:
                                move()
                            return False

                        with mock.patch.object(self.s.Desk, "locked", side_effect=locked):
                            self.assertFalse(self.s.wa_send(d, "hello", True)["ok"])
                        self.assertEqual(len(self.fake.calls), before)
                    self.fake.before_send = None

    def test_poll_cursor_quiet_and_off(self):
        self.fake.news = [{"seq": 1, "jid": "1@s.whatsapp.net", "is_group": False},
                          {"seq": 2, "jid": "g@g.us", "is_group": True, "mentions_me": False},
                          {"seq": 3, "jid": "g@g.us", "is_group": True, "mentions_me": True}]
        # a fresh cursor only catches up: the backlog never becomes cards
        self.assertEqual(self.s.wa_poll_once(0), 3)
        self.assertEqual(len(self.s.WA_PENDING), 0)
        self.fake.news = [{"seq": 4, "jid": "1@s.whatsapp.net", "is_group": False},
                          {"seq": 5, "jid": "g@g.us", "is_group": True, "mentions_me": False},
                          {"seq": 6, "jid": "g@g.us", "is_group": True, "mentions_me": True}]
        self.s.Ambient.dnd = True
        self.assertEqual(self.s.wa_poll_once(3), 6)
        self.assertEqual(len(self.s.WA_PENDING), 2)
        self.s.Ambient.dnd = False
        self.assertTrue(self.s.wa_show_pending())
        self.assertEqual(self.s.STAGES.current()["kind"], "wa_new")
        self.assertEqual(self.s.wa_poll_once(6), 6)
        self.assertEqual(len(self.s.WA_PENDING), 0)
        self.s.wa_switch(False)
        self.assertIsNone(self.s.STAGES.current())

    def test_each_quiet_rule_keeps_notification_queued(self):
        self.s.WA_PENDING.append((self.s.WA_GEN, "1@s.whatsapp.net"))
        for field in ("meeting", "dnd", "phone_call"):
            setattr(self.s.Ambient, field, True)
            self.assertFalse(self.s.wa_show_pending(), field)
            setattr(self.s.Ambient, field, False)
        with mock.patch.object(self.s.Desk, "locked", return_value=True):
            self.assertFalse(self.s.wa_show_pending())
        with mock.patch.object(self.s.Call, "visible", return_value=True):
            self.assertFalse(self.s.wa_show_pending())
        self.draft()
        self.assertFalse(self.s.wa_show_pending())
        self.s.STAGES.close()
        self.assertTrue(self.s.wa_show_pending())

    def test_off_removes_staged_file_and_calls_systemctl(self):
        d = self.draft(file=True)
        self.s.wa_stage(d, io.BytesIO(b"abc"), 3, "a.txt")
        path = Path(self.fake.run) / "stage" / self.s.WA_FILE["staged"]
        self.assertTrue(path.exists())
        self.assertTrue(self.s.wa_switch(False))
        self.assertIsNone(self.s.STAGES.current())
        self.assertFalse(path.exists())
        self.s.subprocess.run.assert_called_with(
            ["systemctl", "--user", "stop", "nixi-whatsapp.service"], check=False,
            stdout=self.s.subprocess.DEVNULL, stderr=self.s.subprocess.DEVNULL)

    def test_unlink_forgets_then_turns_off(self):
        self.draft()
        self.assertTrue(self.s.wa_forget()["ok"])
        self.assertIn(("forget", "boot-1"), self.fake.calls)
        self.assertFalse(self.s.CFG["whatsapp_on"])
        self.assertIsNone(self.s.STAGES.current())

    def test_download_never_overwrites(self):
        d = self.draft()
        self.s.STAGES.put({"v": 1, "kind": "wa_thread", "card": "thread", "jid": "1@s.whatsapp.net",
                           "messages": [{"id": "m1", "kind": "document", "file_name": "same.bin"}]})
        token = self.s.STAGES.current()["messages"][0]["download"]
        self.fake.dest.mkdir(parents=True)
        (self.fake.dest / "same.bin").write_bytes(b"old")
        self.assertTrue(self.s.wa_download(token)["ok"])
        self.assertEqual((self.fake.dest / "same.bin").read_bytes(), b"old")
        self.assertEqual((self.fake.dest / "same-1.bin").read_bytes(), b"new")

    def test_voice_note_card_has_download_without_filename(self):
        page = self.s.STAGES.put({"v": 1, "kind": "wa_thread", "card": "voice", "jid": "1@s.whatsapp.net",
                                  "messages": [{"id": "voice", "kind": "audio", "file_name": ""}]})
        self.assertEqual(page["messages"][0]["kind"], "voice message")
        self.assertIn("download", page["messages"][0])

    def test_click_endpoints_reject_missing_key(self):
        d = self.draft(file=True)
        srv = self.s.ThreadingHTTPServer(("127.0.0.1", 0), self.s.Handler)
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        for path in ("/api/wa/send", "/api/wa/send-file", "/api/wa/download", "/api/wa/forget", "/api/wa/stage?draft=" + d):
            conn = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=3)
            body = b"abc" if "stage" in path else b"{}"
            conn.request("POST", path, body, {"X-Nixi-Token": self.s.TOKEN,
                                                "Content-Length": str(len(body)),
                                                "X-Nixi-File-Name": "a.txt"})
            res = conn.getresponse()
            res.read()
            self.assertEqual(res.status, 403, path)
            conn.close()
        self.assertFalse(self.fake.calls)
        with mock.patch.dict(self.s.CLICK, {"claimed": True, "spoiled": False}):
            conn = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=3)
            conn.request("POST", "/api/wa/stage?draft=" + d, b"abc",
                         {"X-Nixi-Token": self.s.TOKEN, "X-Nixi-Click": self.s.CLICK_KEY,
                          "X-Nixi-File-Name": "a.txt", "Content-Length": "3"})
            res = conn.getresponse()
            self.assertTrue(json.loads(res.read())["ok"])
            conn.close()
            self.assertEqual(self.s.WA_FILE["name"], "a.txt")
