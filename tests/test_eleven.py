import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import wave
from email.message import Message
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import eleven

VOICE = "abcdefghij123"
KEY = "known-fake-key"


class Response:
    def __init__(self, body=b"", status=200, content_type="application/json"):
        self.body = io.BytesIO(body)
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def getcode(self):
        return self.status

    def read(self, n=-1):
        return self.body.read(n)


class ElevenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_dir, self.old_cfg, self.old_open = eleven.DATA_DIR, eleven.CFG, eleven.urlopen
        eleven.DATA_DIR = Path(self.tmp.name)
        eleven.CFG = {}
        self.addCleanup(self.restore)

    def restore(self):
        eleven.DATA_DIR, eleven.CFG, eleven.urlopen = self.old_dir, self.old_cfg, self.old_open

    def voice_cache(self, preview_url="https://storage.googleapis.com:443/audio.mp3"):
        eleven._write(eleven.DATA_DIR / "eleven-voices.json", [{"id": VOICE, "preview_url": preview_url}])

    def test_key_symlink_and_rejections(self):
        target = Path(self.tmp.name) / "secret"
        target.write_text(KEY)
        link = Path(self.tmp.name) / "link"
        link.symlink_to(target)
        eleven.CFG["eleven_key_file"] = str(link)
        with mock.patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": self.tmp.name}):
            self.assertEqual(eleven._key(), KEY)
            target.write_text("x" * 257)
            self.assertFalse(eleven.has_key())
            target.unlink()
            self.assertFalse(eleven.has_key())
        target.write_text(KEY)
        with mock.patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": ""}):
            self.assertFalse(eleven.has_key())
        home = Path(self.tmp.name) / "home" / "x"
        home.parent.mkdir()
        home.write_text(KEY)
        link.unlink()
        link.symlink_to(home)
        self.assertFalse(eleven.has_key())

    def test_key_checks_fstat_after_nofollow_open(self):
        path = Path(self.tmp.name) / "key"
        path.write_text(KEY)
        eleven.CFG["eleven_key_file"] = str(path)
        with mock.patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": self.tmp.name}):
            original = eleven.os.open
            with mock.patch.object(eleven.os, "open", wraps=original) as opened:
                self.assertEqual(eleven._key(), KEY)
                self.assertEqual(opened.call_args.args[1], os.O_RDONLY | os.O_NOFOLLOW)
            path.unlink()
            path.mkdir()
            self.assertFalse(eleven.has_key())

    def test_voices_cache_and_expiry(self):
        calls = []
        def fake(req, timeout):
            calls.append(req)
            return Response(json.dumps({"voices": [{"voice_id": VOICE, "name": "A", "description": "z" * 130,
                                                  "labels": {"accent": "UK"}, "preview_url": "url",
                                                  "verified_languages": [{"language": "pl"}, {"language": "en"}, "x"]}]}).encode())
        eleven.urlopen = fake
        with mock.patch.object(eleven, "_key", return_value=KEY):
            self.assertEqual(eleven.voices()[0]["description"], "z" * 120)
            self.assertEqual(eleven.voices()[0]["accent"], "UK")
            self.assertEqual(eleven.voices()[0]["languages"], ["en", "pl"])   # (ElevenLabs' verified_languages, as the spec names)
            self.assertEqual(len(calls), 1)
            path = eleven.DATA_DIR / "eleven-voices.json"
            os.utime(path, (0, 0))
            eleven.voices()
            self.assertEqual(len(calls), 2)

    def test_speak_wav_and_request(self):
        self.voice_cache()
        seen = []
        def fake(req, timeout):
            seen.append((req, timeout))
            return Response(b"\x88\x13" * 4410)
        eleven.urlopen = fake
        with mock.patch.object(eleven, "_key", return_value=KEY):
            wav = eleven.speak("Hello.", VOICE)
        with wave.open(io.BytesIO(wav)) as audio:
            self.assertEqual((audio.getframerate(), audio.getnchannels(), audio.getsampwidth()), (22050, 1, 2))
            self.assertEqual(audio.getnframes(), 4410)
        from server import tidy_full
        self.assertIsNotNone(tidy_full(wav, "Hello.")[1])
        req, timeout = seen[0]
        self.assertIn("output_format=pcm_22050", req.full_url)
        self.assertEqual(json.loads(req.data)["model_id"], "eleven_flash_v2_5")
        self.assertEqual(req.get_header("Xi-api-key"), KEY)
        self.assertLessEqual(timeout, 1.5)

    def test_statuses_and_no_key_in_error(self):
        self.voice_cache()
        for status, kind in ((401, "auth"), (403, "auth"), (402, "quota"), (404, "bad_voice"),
                             (422, "bad_voice"), (500, "network")):
            def fail(req, timeout):
                raise urllib.error.HTTPError(req.full_url, status, KEY, {}, None)
            eleven.urlopen = fail
            with mock.patch.object(eleven, "_key", return_value=KEY):
                with self.assertRaises(eleven.ElevenError) as got:
                    eleven.speak("Hi", VOICE)
            self.assertEqual(got.exception.kind, kind)
            self.assertNotIn(KEY, str(got.exception))
        with self.assertRaises(eleven.ElevenError) as got:
            eleven.speak("Hi", "deletedvoice99")
        self.assertEqual(got.exception.kind, "bad_voice")
        self.assertIn("voice no longer on your account", str(got.exception))

    def test_retry_deadline_and_timeout(self):
        self.voice_cache()
        clock = [0.0]
        timeouts = []
        def fake(req, timeout):
            timeouts.append(timeout)
            clock[0] += 0.5
            if len(timeouts) == 1:
                raise urllib.error.HTTPError(req.full_url, 429, "", {"Retry-After": "1"}, None)
            return Response(b"\x00\x00")
        eleven.urlopen = fake
        with mock.patch.object(eleven, "_key", return_value=KEY), \
             mock.patch.object(eleven.time, "monotonic", side_effect=lambda: clock[0]), \
             mock.patch.object(eleven.time, "sleep", side_effect=lambda n: clock.__setitem__(0, clock[0] + n)):
            eleven.speak("Hi", VOICE)
        self.assertEqual(timeouts, [1.5, 1.5])
        timeouts.clear()
        clock[0] = 0
        def slow(req, timeout):
            timeouts.append(timeout)
            clock[0] += 3
            raise urllib.error.HTTPError(req.full_url, 429, "", {"Retry-After": "1"}, None)
        eleven.urlopen = slow
        with mock.patch.object(eleven, "_key", return_value=KEY), \
             mock.patch.object(eleven.time, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(eleven.ElevenError) as got:
                eleven.speak("Hi", VOICE)
        self.assertEqual(got.exception.kind, "quota")
        self.assertEqual(timeouts, [1.5])

    def test_body_obeys_one_sentence_deadline(self):
        self.voice_cache()
        clock = [0.0]
        class SlowResponse(Response):
            def read(self, n=-1):
                clock[0] += 4.1
                return b"\x00\x00"
        eleven.urlopen = lambda req, timeout: SlowResponse()
        with mock.patch.object(eleven, "_key", return_value=KEY), \
             mock.patch.object(eleven.time, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(eleven.ElevenError) as got:
                eleven.speak("Hi", VOICE)
        self.assertEqual(got.exception.kind, "network")

    def test_usage_cap_settle_and_new_day(self):
        barrier = threading.Barrier(2)
        outcomes = []
        def take():
            barrier.wait()
            try:
                outcomes.append(eleven.reserve(10, 10))
            except eleven.ElevenError as exc:
                outcomes.append(exc.kind)
        threads = [threading.Thread(target=take) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertCountEqual(outcomes, [10, "cap"])
        eleven.settle(10, False, True)
        self.assertEqual(eleven.today()["used"], 10)
        eleven._write(eleven.DATA_DIR / "eleven-usage.json", {"date": "2000-01-01", "used": 50, "reserved": 10})
        self.assertEqual(eleven.today()["used"], 0)
        eleven.reserve(5, 10)
        eleven.settle(5, False, False)
        self.assertEqual(eleven.today()["reserved"], 0)

    def test_preview_rejections_and_success(self):
        self.voice_cache()
        eleven.urlopen = lambda req, timeout: Response(b"MP3", content_type="audio/mpeg")
        self.assertEqual(eleven.preview(VOICE), b"MP3")
        for url in ("http://storage.googleapis.com:443/a", "https://127.0.0.1:443/a",
                    "https://storage.googleapis.com.evil:443/a", "https://storage.googleapis.com/a"):
            self.voice_cache(url)
            with self.assertRaises(eleven.ElevenError):
                eleven.preview(VOICE)
        self.voice_cache()
        for response in (Response(status=302), Response(b"x" * (1024 * 1024 + 1), content_type="audio/mpeg"),
                         Response(b"x", content_type="text/html")):
            eleven.urlopen = lambda req, timeout, response=response: response
            with self.assertRaises(eleven.ElevenError):
                eleven.preview(VOICE)
        with self.assertRaises(eleven.ElevenError) as got:
            eleven.preview("deletedvoice99")
        self.assertEqual(got.exception.kind, "bad_voice")


if __name__ == "__main__":
    unittest.main()
