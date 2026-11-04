"""ElevenLabs speech, voice previews, and the local daily character cap."""

import datetime
import io
import json
import os
import re
import stat
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path
from urllib.parse import urlsplit

CFG = {}
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "nixi-companion"
urlopen = urllib.request.urlopen
_lock = threading.Lock()
_VOICE_ID = re.compile(r"[A-Za-z0-9]{10,40}\Z")


class ElevenError(Exception):
    def __init__(self, kind, status=None, sent=False):
        self.kind = kind
        self.status = status
        self.sent = sent
        message = "voice no longer on your account" if kind == "bad_voice" else f"ElevenLabs {kind}"
        super().__init__(message + (f" ({status})" if status else ""))


def _key():
    path = os.path.realpath(CFG.get("eleven_key_file", "/run/agenix/api-elevenlabs"))
    roots = ["/run/agenix", "/run/agenix.d", "/run/secrets"]
    if os.environ.get("CREDENTIALS_DIRECTORY"):
        roots.append(os.path.realpath(os.environ["CREDENTIALS_DIRECTORY"]))
    if not any(path.startswith(root.rstrip("/") + "/") for root in roots):
        raise ElevenError("key")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            meta = os.fstat(fd)
            if not stat.S_ISREG(meta.st_mode) or not 0 < meta.st_size <= 256 or meta.st_uid not in (0, os.getuid()):
                raise ElevenError("key")
            value = os.read(fd, 257).strip()
            if not re.fullmatch(rb"[A-Za-z0-9_-]{16,128}", value):
                raise ElevenError("key")
            return value.decode("ascii")
        finally:
            os.close(fd)
    except (OSError, UnicodeError) as exc:
        raise ElevenError("key") from None


def has_key():
    try:
        _key()
        return True
    except ElevenError:
        return False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ElevenError("network", code)


_opener = urllib.request.build_opener(_NoRedirect)


def _open(request, timeout):
    # A substituted urlopen is only used by tests; the real opener refuses redirects.
    return (urlopen if urlopen is not urllib.request.urlopen else _opener.open)(request, timeout=timeout)


def _kind(status):
    if status in (401, 403):
        return "auth"
    if status in (402, 429):
        return "quota"
    if status in (404, 422):
        return "bad_voice"
    return "network"


def _read(response, deadline, limit=None):
    data = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ElevenError("network")
        # urllib's socket keeps the initial timeout during reads unless it is updated.
        sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        if sock is not None:
            sock.settimeout(remaining)
        size = min(4096, limit + 1 - len(data)) if limit is not None else 4096
        try:
            chunk = (response.read1(size) if hasattr(response, "read1") else response.read(size))
        except (OSError, TimeoutError):
            raise ElevenError("network") from None
        data.extend(chunk)
        if limit is not None and len(data) > limit:
            raise ElevenError("preview")
        if not chunk:
            return bytes(data)


def _request(request, deadline, limit=None, retry=False, still_ok=None):
    ever_sent = False
    for attempt in range(2 if retry else 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ElevenError("network", sent=ever_sent)
        sent = False
        try:
            if still_ok is not None:
                opened = still_ok(lambda: _open(request, min(1.5, remaining)))
                if opened is None:
                    raise ElevenError("network")
            else:
                opened = _open(request, min(1.5, remaining))
            with opened as response:
                sent = request.data is not None
                status = response.getcode()
                if status != 200:
                    raise urllib.error.HTTPError(request.full_url, status, "", response.headers, None)
                body = _read(response, deadline, limit)
                if time.monotonic() > deadline:
                    raise ElevenError("network", sent=sent)
                return body, response.headers
        except urllib.error.HTTPError as exc:
            sent = request.data is not None
            ever_sent |= sent
            exc.close()
            if exc.code == 429 and retry and attempt == 0:
                try:
                    delay = float(exc.headers.get("Retry-After", ""))
                except (TypeError, ValueError):
                    delay = -1
                if 0 <= delay <= 2 and deadline - time.monotonic() >= delay + 1.5:
                    time.sleep(delay)
                    continue
            raise ElevenError(_kind(exc.code), exc.code, sent=sent) from None
        except ElevenError as exc:
            if sent or ever_sent:
                exc.sent = True
            raise
        except Exception as exc:
            reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
            # urllib wraps connect/send failures in URLError; an OSError/timeout raised bare comes from waiting for the
            # response, i.e. after the POST left the machine and may be billed (Codex review on PR #40)
            after_send = (isinstance(exc, OSError) and not isinstance(exc, urllib.error.URLError)) or \
                isinstance(reason, (ConnectionResetError, BrokenPipeError))
            raise ElevenError("network", sent=ever_sent or request.data is not None and (sent or after_send)) from None


def _api(path, data=None):
    headers = {"xi-api-key": _key()}
    if data is not None:
        headers["Content-Type"] = "application/json"
    return urllib.request.Request("https://api.elevenlabs.io" + path, data=data, headers=headers)


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(data, out)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def voices(deadline=None):
    path = DATA_DIR / "eleven-voices.json"
    try:
        if time.time() - path.stat().st_mtime < 86400:
            return json.loads(path.read_text())
    except (OSError, ValueError):
        pass
    raw, _ = _request(_api("/v1/voices"), deadline or time.monotonic() + 4)
    try:
        items = json.loads(raw)["voices"]
        result = []
        for item in items:
            if not _VOICE_ID.fullmatch(item["voice_id"]):
                continue
            labels = item.get("labels") or {}
            result.append({"id": item["voice_id"], "name": str(item.get("name") or ""),
                           "category": str(item.get("category") or ""),
                           "description": str(item.get("description") or "")[:120],
                           "accent": str(labels.get("accent") or ""),
                           "languages": sorted({str(l.get("language") or "")[:8] for l in item.get("verified_languages") or []
                                                if isinstance(l, dict) and l.get("language")}),
                           "preview_url": str(item.get("preview_url") or "")})
    except (ValueError, KeyError, TypeError):
        raise ElevenError("network") from None
    _write(path, result)
    return result


def speak(text, voice_id, still_ok=None, checked=False):
    deadline = time.monotonic() + 4
    if not _VOICE_ID.fullmatch(voice_id):
        raise ElevenError("bad_voice")
    # A deleted voice is a configuration error even if the API would return another status.
    if not checked and not any(v["id"] == voice_id for v in voices(deadline)):
        raise ElevenError("bad_voice")
    body = json.dumps({"text": text, "model_id": "eleven_flash_v2_5"}).encode()
    pcm, _ = _request(_api(f"/v1/text-to-speech/{voice_id}?output_format=pcm_22050", body), deadline, retry=True, still_ok=still_ok)
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22050)
        wav.writeframes(pcm)
    return out.getvalue()


def preview(voice_id):
    if not _VOICE_ID.fullmatch(voice_id):
        raise ElevenError("bad_voice")
    voice = next((v for v in voices() if v["id"] == voice_id), None)
    if voice is None:
        raise ElevenError("bad_voice")
    url = voice["preview_url"]
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        raise ElevenError("preview") from None
    if parts.scheme != "https" or parts.hostname != "storage.googleapis.com" or port not in (None, 443) or not parts.path.startswith("/") or parts.username or parts.password or parts.query or parts.fragment:
        raise ElevenError("preview")
    data, headers = _request(urllib.request.Request(url), time.monotonic() + 5, limit=1024 * 1024)
    if headers.get_content_type() not in ("audio/mpeg", "audio/wav"):
        raise ElevenError("preview")
    return data


def today():
    with _lock:
        path = DATA_DIR / "eleven-usage.json"
        date = datetime.date.today().isoformat()
        try:
            data = json.loads(path.read_text())
            if data.get("date") == date:
                return data
        except (OSError, ValueError, AttributeError):
            pass
        data = {"date": date, "used": 0, "reserved": 0}
        _write(path, data)
        return data


def reserve(n, cap):
    with _lock:
        path = DATA_DIR / "eleven-usage.json"
        date = datetime.date.today().isoformat()
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError, AttributeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        if data.get("date") != date:
            data = {"date": date, "used": 0, "reserved": 0}
        if data["used"] + data["reserved"] + n > cap:
            raise ElevenError("cap")
        data["reserved"] += n
        _write(path, data)
    return n


def settle(n, ok, sent):
    with _lock:
        path = DATA_DIR / "eleven-usage.json"
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return
        if data.get("date") != datetime.date.today().isoformat():
            return
        data["reserved"] = max(0, data["reserved"] - n)
        if ok or sent:
            data["used"] += n
        _write(path, data)
