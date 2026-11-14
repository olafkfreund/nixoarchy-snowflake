import io
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import wave
from email.message import Message
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import eleven

VOICE = "abcdefghij123"
KEY = "known-fake-key-1234"


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

    def voice_cache(self, preview_url="https://storage.googleapis.com/eleven-public-prod/premade/voices/a/b.mp3"):
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

    def test_key_from_sops_layout(self):
        self.assertEqual(eleven.KEY_ROOTS, ("/run/agenix", "/run/agenix.d", "/run/secrets", "/run/secrets.d"))
        base = Path(os.path.realpath(self.tmp.name))
        generation = base / "secrets.d/1"
        generation.mkdir(parents=True)
        (generation / "api-elevenlabs").write_text(KEY)
        link = base / "secrets"
        link.symlink_to(generation)
        (base / "outside").write_text(KEY)
        evil = base / "secrets.d-evil/key"
        evil.parent.mkdir()
        evil.write_text(KEY)
        eleven.CFG["eleven_key_file"] = str(link / "api-elevenlabs")

        with mock.patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": ""}):
            with mock.patch.object(eleven, "KEY_ROOTS", (str(link),)):
                self.assertFalse(eleven.has_key())
            with mock.patch.object(eleven, "KEY_ROOTS", (str(link), str(base / "secrets.d"))):
                self.assertEqual(eleven._key(), KEY)
                next_generation = base / "secrets.d/2"
                next_generation.mkdir()
                next_key = next_generation / "api-elevenlabs"
                next_key.write_text("new-fake-key-5678abcd")
                link.unlink()
                link.symlink_to(next_generation)
                self.assertEqual(eleven._key(), "new-fake-key-5678abcd")
                next_key.unlink()
                next_key.symlink_to(base / "outside")
                self.assertFalse(eleven.has_key())
                next_key.unlink()
                next_key.symlink_to(evil)
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

    def test_multiline_key_is_rejected_without_disclosure(self):
        bad = "known-fake-key-1234\nsecond-secret-line-1234"
        path = Path(self.tmp.name) / "key"
        path.write_text(bad)
        eleven.CFG["eleven_key_file"] = str(path)
        with mock.patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": self.tmp.name}):
            with self.assertRaises(eleven.ElevenError) as got:
                eleven._key()
        self.assertEqual(got.exception.kind, "key")
        self.assertNotIn(bad, str(got.exception))
        self.assertNotIn("second-secret-line", str(got.exception))

    def test_opener_value_error_is_redacted(self):
        req = urllib.request.Request("https://api.elevenlabs.io/v1/voices")
        with mock.patch.object(eleven, "_open", side_effect=ValueError("Invalid header value b'known-fake-key-1234'")):
            with self.assertRaises(eleven.ElevenError) as got:
                eleven._request(req, time.monotonic() + 1)
        self.assertEqual(got.exception.kind, "network")
        self.assertNotIn(KEY, str(got.exception))

    def test_trickling_body_obeys_deadline(self):
        class Trickle(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                try:
                    for _ in range(20):
                        self.wfile.write(b"x" * 100)
                        self.wfile.flush()
                        time.sleep(.5)
                except BrokenPipeError:
                    pass
            def log_message(self, *args):
                pass
        try:
            srv = http.server.HTTPServer(("127.0.0.1", 0), Trickle)
        except PermissionError:
            self.skipTest("sandbox forbids loopback sockets")
        self.addCleanup(srv.server_close)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        start = time.monotonic()
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_port}/", timeout=1.5) as response:
            with self.assertRaises(eleven.ElevenError) as got:
                eleven._read(response, start + 4)
        self.assertEqual(got.exception.kind, "network")
        self.assertLess(time.monotonic() - start, 6)

    def test_post_timed_out_waiting_for_headers_counts_as_sent(self):   # Codex review on PR #40: it may be billed
        got_body = threading.Event()
        class Slow(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0)); got_body.set()
                time.sleep(2.5)                       # past the 1.5 s first-byte timeout
                try:
                    self.send_response(200); self.end_headers()
                except BrokenPipeError:
                    pass
            def log_message(self, *args):
                pass
        try:
            srv = http.server.HTTPServer(("127.0.0.1", 0), Slow)
        except PermissionError:
            self.skipTest("sandbox forbids loopback sockets")
        self.addCleanup(srv.server_close)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        eleven.urlopen = urllib.request.urlopen       # (the real urlopen, not a fake: the bare timeout is what matters)
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_port}/", data=b'{"text":"hi"}')
        with self.assertRaises(eleven.ElevenError) as got:
            eleven._request(req, time.monotonic() + 4)
        self.assertTrue(got_body.is_set())
        self.assertEqual(got.exception.kind, "network")
        self.assertTrue(got.exception.sent)

    def test_refused_connection_is_not_sent(self):
        import socket
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()   # (nothing listens there)
        eleven.urlopen = urllib.request.urlopen
        with self.assertRaises(eleven.ElevenError) as got:
            eleven._request(urllib.request.Request(f"http://127.0.0.1:{port}/", data=b"{}"), time.monotonic() + 4)
        self.assertFalse(got.exception.sent)

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
            return Response(b"MP3")
        eleven.urlopen = fake
        with mock.patch.object(eleven, "_key", return_value=KEY), \
             mock.patch.object(eleven.shutil, "which", return_value="/bin/ffmpeg"), \
             mock.patch.object(eleven.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"\x88\x13" * 4410)) as decode:
            wav = eleven.speak("Hello.", VOICE)
        with wave.open(io.BytesIO(wav)) as audio:
            self.assertEqual((audio.getframerate(), audio.getnchannels(), audio.getsampwidth()), (44100, 1, 2))
            self.assertEqual(audio.getnframes(), 4410)
        self.wav = wav                                   # (tidy_full timing is checked in ElevenWavTimingTest, under a throwaway HOME)
        req, timeout = seen[0]
        self.assertIn("output_format=mp3_44100_128", req.full_url)
        self.assertEqual(json.loads(req.data), {"text": "Hello.", "model_id": "eleven_v4_turbo",
                                               "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}})
        self.assertEqual(req.get_header("Xi-api-key"), KEY)
        self.assertLessEqual(timeout, 1.5)
        self.assertEqual(decode.call_args.args[0], ["/bin/ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                                                    "-f", "mp3", "-i", "pipe:0", "-af",
                                                    "volume=6dB,alimiter=limit=0.84:level=0", "-ac", "1", "-ar", "44100",
                                                    "-f", "s16le", "pipe:1"])
        self.assertEqual(decode.call_args.kwargs["input"], b"MP3")
        self.assertLessEqual(decode.call_args.kwargs["timeout"], 4)
        self.assertEqual(decode.call_args.kwargs["stderr"], subprocess.DEVNULL)
        self.assertNotIn("shell", decode.call_args.kwargs)

    def test_speak_without_ffmpeg(self):
        self.voice_cache()
        seen = []
        def fake(req, timeout):
            seen.append(req)
            return Response(b"\x88\x13" * 4410)
        eleven.urlopen = fake
        with mock.patch.object(eleven, "_key", return_value=KEY), \
             mock.patch.object(eleven.shutil, "which", return_value=None), \
             mock.patch.object(eleven.subprocess, "run") as decode:
            wav = eleven.speak("Hi", VOICE)
        with wave.open(io.BytesIO(wav)) as audio:
            self.assertEqual((audio.getframerate(), audio.getnchannels(), audio.getsampwidth()), (22050, 1, 2))
            self.assertEqual(audio.getnframes(), 4410)
        self.assertIn("output_format=pcm_22050", seen[0].full_url)
        self.assertEqual(json.loads(seen[0].data)["voice_settings"], {"stability": 0.5, "similarity_boost": 0.75})
        decode.assert_not_called()

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_speak_really_decodes_mp3(self):                # the mocks above only restate the argv: this runs the filter
        mp3 = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                              "-f", "mp3", "pipe:1"], stdout=subprocess.PIPE, check=True).stdout
        self.voice_cache()
        eleven.urlopen = lambda req, timeout: Response(mp3)
        with mock.patch.object(eleven, "_key", return_value=KEY):
            wav = eleven.speak("Hello.", VOICE)
        with wave.open(io.BytesIO(wav)) as audio:
            self.assertEqual((audio.getframerate(), audio.getnchannels(), audio.getsampwidth()), (44100, 1, 2))
            self.assertAlmostEqual(audio.getnframes() / 44100, 1, delta=0.2)

    def test_speak_decode_failure_raises_redacted_error(self):
        self.voice_cache()
        eleven.urlopen = lambda req, timeout: Response(b"MP3")
        with mock.patch.object(eleven, "_key", return_value=KEY), \
             mock.patch.object(eleven.shutil, "which", return_value="/bin/ffmpeg"), \
             mock.patch.object(eleven.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, b"", b"secret URL")):
            with self.assertRaises(eleven.ElevenError) as got:
                eleven.speak("Hi", VOICE)
        self.assertEqual(got.exception.kind, "decode")
        self.assertTrue(got.exception.sent)
        self.assertNotIn("secret URL", str(got.exception))

    def test_speak_decode_uses_remaining_deadline(self):
        self.voice_cache()
        clock = [0.0]
        def fake(req, timeout):
            clock[0] = 3.5
            return Response(b"MP3")
        eleven.urlopen = fake
        with mock.patch.object(eleven, "_key", return_value=KEY), \
             mock.patch.object(eleven.shutil, "which", return_value="/bin/ffmpeg"), \
             mock.patch.object(eleven.time, "monotonic", side_effect=lambda: clock[0]), \
             mock.patch.object(eleven.subprocess, "run", side_effect=subprocess.TimeoutExpired("ffmpeg", 0.5)) as decode:
            with self.assertRaises(eleven.ElevenError) as got:
                eleven.speak("Hi", VOICE)
        self.assertEqual(got.exception.kind, "decode")
        self.assertTrue(got.exception.sent)
        self.assertEqual(decode.call_args.kwargs["timeout"], 0.5)

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
             mock.patch.object(eleven.shutil, "which", return_value=None), \
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

    def test_reserve_recovers_from_nonobject_usage(self):
        eleven._write(eleven.DATA_DIR / "eleven-usage.json", [])
        self.assertEqual(eleven.reserve(5, 10), 5)
        self.assertEqual(eleven.today()["reserved"], 5)

    def test_preview_rejections_and_success(self):
        mp3, seen = b"ID3\x04" + b"\0" * 40, []
        def fake(req, timeout):
            seen.append(req)
            return Response(mp3, content_type="text/plain")   # (what Google really sends for these MP3s)
        self.voice_cache()
        eleven.urlopen = fake
        self.assertEqual(eleven.preview(VOICE), mp3)
        self.voice_cache(f"https://api.us.elevenlabs.io/v1/voices/{VOICE}/previews/audio?payload=abc")   # (ElevenLabs' signed links)
        self.assertEqual(eleven.preview(VOICE), mp3)
        self.assertTrue(all(r.get_header("Xi-api-key") is None for r in seen))   # a preview never carries the key
        for url in ("http://storage.googleapis.com/eleven-public-prod/a", "https://127.0.0.1/a",
                    "https://storage.googleapis.com.evil/eleven-public-prod/a", "https://storage.googleapis.com:444/eleven-public-prod/a",
                    "https://storage.googleapis.com:bad/a", "https://storage.googleapis.com/someone-else/a",
                    "https://storage.googleapis.com/eleven-public-prod/a?x=1",
                    "https://api.us.elevenlabs.io/v1/user", f"https://api.us.elevenlabs.io/v1/voices/{VOICE}/previews/audio#x",
                    "https://u:p@api.elevenlabs.io/v1/voices/" + VOICE + "/previews/audio"):
            self.voice_cache(url)
            with self.assertRaises(eleven.ElevenError, msg=url):
                eleven.preview(VOICE)
        self.voice_cache()
        for response in (Response(status=302), Response(b"ID3" + b"x" * (1024 * 1024), content_type="audio/mpeg"),
                         Response(b"<html>not audio</html>", content_type="audio/mpeg")):   # (the bytes decide, not the header)
            eleven.urlopen = lambda req, timeout, response=response: response
            with self.assertRaises(eleven.ElevenError):
                eleven.preview(VOICE)
        with self.assertRaises(eleven.ElevenError) as got:
            eleven.preview("deletedvoice99")
        self.assertEqual(got.exception.kind, "bad_voice")


if __name__ == "__main__":
    unittest.main()


from test_speakable import _ServerEnv   # noqa: E402  (server.py must only ever be imported under a throwaway HOME)


class ElevenWavTimingTest(_ServerEnv):
    def test_speak_wav_is_timed_by_tidy_full(self):
        import wave as _w
        out = io.BytesIO()
        with _w.open(out, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050); w.writeframes(b"\x88\x13" * 4410)
        self.assertIsNotNone(self.server.tidy_full(out.getvalue(), "Hello.")[1])
