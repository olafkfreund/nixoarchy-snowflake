"""Local HTTP client for the WhatsApp bridge."""

import http.client
import json
import os
import re
import secrets
import shutil
import socket
import stat
import struct
from pathlib import Path
from urllib.parse import urlencode
import lang


def mentions(text, locale=None):
    t = " ".join((text or "").lower().replace("’", "'").split())
    if not t:
        return False
    words = []
    for code in dict.fromkeys((lang.norm(locale or lang.active), "en")):
        words.extend(lang.load(code).get("phrases", {}).get("wa_words", []))
    if not words:
        return False
    pat = r"\b(?:" + "|".join(re.escape(w.lower()).replace(r"\ ", r"\s+") for w in sorted(set(words), key=len, reverse=True)) + r")\b"
    return bool(re.search(pat, t))


class NotSent(ConnectionError):
    def __init__(self, message, boot=None):
        super().__init__(message)
        self.boot = boot


class Unknown(ConnectionError):
    def __init__(self, message, boot=None):
        super().__init__(message)
        self.boot = boot


class Unavailable(NotSent):
    """The bridge could not be reached before any request bytes were sent."""


class BridgeError(RuntimeError):
    def __init__(self, message, boot=None):
        super().__init__(message)
        self.boot = boot


class Unauthorized(BridgeError):
    pass


class _UnixHTTP(http.client.HTTPConnection):
    def __init__(self, run):
        super().__init__("localhost", timeout=30)
        self.run = run
        self.written = False

    def connect(self):
        try:
            parent = os.lstat(self.run)
            sock = os.lstat(os.path.join(self.run, "sock"))
            if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or
                    parent.st_mode & 0o077 or not stat.S_ISSOCK(sock.st_mode) or
                    sock.st_uid != os.getuid()):
                raise Unavailable("WhatsApp bridge has an unsafe socket")
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect(os.path.join(self.run, "sock"))
            uid = struct.unpack("3i", self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
            if uid != os.getuid():
                self.close()
                raise Unavailable("WhatsApp bridge has the wrong peer")
        except OSError as exc:
            self.close()
            raise Unavailable("WhatsApp bridge is unavailable") from exc

    def send(self, data):
        if self.sock is None:
            self.connect()
        # A failed sendall may have written a prefix; treat its outcome as unknown.
        self.written = True
        self.sock.sendall(data)


class WhatsApp:
    def __init__(self, run_dir=None, max_file=100 * 1024 * 1024):
        self.run = os.fspath(run_dir) if run_dir is not None else os.path.join(
            os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}", "nixi-whatsapp")
        self.max_file = max_file

    def _request(self, method, path, data=None, boot=None):
        conn = _UnixHTTP(self.run)
        write = path in ("/send", "/send-file", "/forget")
        try:
            parent = os.lstat(self.run)
            if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or parent.st_mode & 0o077:
                raise Unavailable("WhatsApp bridge has an unsafe run directory")
            fd = os.open(os.path.join(self.run, "token"), os.O_RDONLY | os.O_NOFOLLOW)
            try:
                token = os.read(fd, 4096).decode("ascii")
            finally:
                os.close(fd)
            headers = {"Authorization": "Bearer " + token}
            if write:
                headers["If-Boot"] = boot
            if data is not None:
                headers["Content-Type"] = "application/json"
            conn.request(method, path, body=json.dumps(data) if data is not None else None, headers=headers)
            response = conn.getresponse()
            seen = response.getheader("X-Boot")
            payload = json.loads(response.read())
            if response.status == 401:
                raise Unauthorized("WhatsApp bridge rejected its token", seen)
            if isinstance(payload, dict) and payload.get("result") == "not_sent":
                raise NotSent("WhatsApp message was not sent", seen)
            if isinstance(payload, dict) and payload.get("result") == "unknown":
                raise Unknown("WhatsApp message may have been sent", seen)
            if response.status >= 400:
                raise BridgeError(payload.get("error", "WhatsApp bridge error") if isinstance(payload, dict)
                                  else "WhatsApp bridge error", seen)
            return payload, seen
        except (NotSent, Unknown, BridgeError):
            raise
        except (OSError, http.client.HTTPException, ValueError) as exc:
            if write and conn.written:
                raise Unknown("WhatsApp bridge reply was lost") from exc
            raise Unavailable("WhatsApp bridge is unavailable") from exc
        finally:
            conn.close()

    def status(self):
        return self._request("GET", "/status")

    def pair(self):
        return self._request("POST", "/pair", {})

    def pair_cancel(self):
        return self._request("POST", "/pair/cancel", {})

    def forget(self, boot):
        return self._request("POST", "/forget", {}, boot)

    def chats(self, q="", limit=20):
        return self._request("GET", "/chats?" + urlencode({"q": q, "limit": limit}))

    def contacts(self, q=""):
        return self._request("GET", "/contacts?" + urlencode({"q": q}))

    def thread(self, jid, limit=50, before=0):
        return self._request("GET", "/thread?" + urlencode({"jid": jid, "limit": limit, "before": before}))

    def new(self, after=0):
        return self._request("GET", "/new?" + urlencode({"after": after}))

    def send(self, jid, text, boot):
        return self._request("POST", "/send", {"jid": jid, "text": text}, boot)

    def send_file(self, jid, staged, caption, file_name, boot):
        return self._request("POST", "/send-file", {"jid": jid, "staged": staged,
                                                  "caption": caption, "file_name": file_name}, boot)

    def download(self, jid, id):
        return self._request("POST", "/download", {"jid": jid, "id": id})

    def stage(self, stream, n):
        if n < 0 or n > self.max_file:
            raise ValueError("WhatsApp file is too large")
        directory = os.open(os.path.join(self.run, "stage"), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        name = secrets.token_urlsafe(24)
        try:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                with os.fdopen(fd, "wb") as out:
                    remaining = n
                    while remaining:
                        chunk = stream.read(min(65536, remaining))
                        if not chunk:
                            raise ValueError("WhatsApp file ended early")
                        if len(chunk) > remaining:
                            raise ValueError("WhatsApp file exceeded its declared size")
                        out.write(chunk)
                        remaining -= len(chunk)
            except BaseException:
                os.unlink(name, dir_fd=directory)
                raise
            return name
        finally:
            os.close(directory)

    def fetch(self, file, dest_dir=None, name=None):
        if not re.fullmatch(r"[0-9]+-[0-9a-f]{16}\.[a-z0-9]{1,8}", file):
            raise ValueError("Invalid WhatsApp download name")
        directory = os.open(os.path.join(self.run, "dl"), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                source = os.open(file, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                with os.fdopen(source, "rb") as src:
                    if not stat.S_ISREG(os.fstat(src.fileno()).st_mode):
                        raise ValueError("Invalid WhatsApp download")
                    dest = Path(dest_dir) if dest_dir is not None else Path.home() / "Downloads" / "WhatsApp"
                    dest.mkdir(mode=0o700, parents=True, exist_ok=True)
                    display = os.path.basename((name or file).replace("\\", "/"))
                    display = "".join(c for c in display if ord(c) >= 32 and ord(c) != 127)
                    if display in ("", ".", ".."):
                        display = file
                    stem, ext = os.path.splitext(display)
                    for index in range(10000):
                        candidate = display if index == 0 else f"{stem}-{index}{ext}"
                        path = dest / candidate
                        try:
                            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                            break
                        except FileExistsError:
                            continue
                    else:
                        raise FileExistsError("Too many WhatsApp downloads with the same name")
                    try:
                        with os.fdopen(fd, "wb") as out:
                            shutil.copyfileobj(src, out)
                    except BaseException:
                        os.unlink(path)
                        raise
                    return path
            finally:
                os.unlink(file, dir_fd=directory)
        finally:
            os.close(directory)
