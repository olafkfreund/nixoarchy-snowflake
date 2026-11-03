"""Answer stages: cut the typed block out of a reply, validate it, hold it behind tokens.

The agent ends a reply with one line `<<stage>>{"v":1,"kind":...}`. Nothing here trusts it:
unknown kinds, long fields and control characters drop the whole block (the answer stays a
caption). The page only ever sees tokens; the server alone builds URLs and looks up commands.
"""
import json
import re
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote_plus, urlparse

MARK = "<<stage"
MODES = ("driving", "walking", "bicycling", "transit")
_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class Cutter:
    """Streaming filter: feed() returns only text that is safe to show and speak."""

    def __init__(self):
        self.buf = ""      # tail that might be the start of the marker
        self.blk = None    # the marker line being swallowed, or None
        self.blocks = []

    def feed(self, delta):
        s, self.buf, out = self.buf + delta, "", []
        while True:
            if self.blk is not None:
                i = s.find("\n")
                if i < 0:
                    self.blk += s
                    return "".join(out)
                self.blocks.append(self.blk + s[:i])
                self.blk, s = None, s[i + 1:]
                continue
            i = s.find(MARK)
            if i >= 0:
                out.append(s[:i])
                self.blk, s = "", s[i + len(MARK):]
                continue
            for k in range(min(len(MARK) - 1, len(s)), 0, -1):  # marker split across deltas
                if MARK.startswith(s[-k:]):
                    self.buf, s = s[-k:], s[:-k]
                    break
            out.append(s)
            return "".join(out)

    def close(self):
        """-> (leftover safe text, the last block parsed, or None)."""
        text, self.buf = self.buf, ""
        if self.blk is not None:
            self.blocks.append(self.blk)
            self.blk = None
        raw = self.blocks[-1] if self.blocks else None
        if raw is None or not raw.startswith(">>"):
            return text, None
        try:
            return text, json.loads(raw[2:])
        except ValueError:
            return text, None


def _str(v, n):
    return v.strip() if isinstance(v, str) and 0 < len(v.strip()) <= n and not _CTRL.search(v) else None


def validate(obj):
    """-> a clean stage dict built from known keys only, or None."""
    if not isinstance(obj, dict) or obj.get("v") != 1:
        return None
    kind = obj.get("kind")
    if kind == "commands":
        items = obj.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 5:
            return None
        out = []
        for it in items:
            if not isinstance(it, dict):
                return None
            label, cmd = _str(it.get("label"), 120), _str(it.get("cmd"), 500)
            if label is None or cmd is None:
                return None
            out.append({"label": label, "cmd": cmd})
        out = {"v": 1, "kind": "commands", "items": out}
        if obj.get("title") is not None:
            if _str(obj["title"], 120) is None:
                return None
            out["title"] = _str(obj["title"], 120)
        return out
    if kind == "facts":
        title, pts = _str(obj.get("title"), 120), obj.get("points")
        if title is None or not isinstance(pts, list) or not 1 <= len(pts) <= 5:
            return None
        pts = [_str(p, 120) for p in pts]
        src = obj.get("source")
        if None in pts or (src is not None and _str(src, 120) is None):
            return None
        out = {"v": 1, "kind": "facts", "title": title, "points": pts}
        if src is not None:
            out["source"] = _str(src, 120)
        return out
    if kind == "place":
        dest, mode = _str(obj.get("dest"), 160), obj.get("mode")
        if dest is None or (mode is not None and mode not in MODES):
            return None
        return {"v": 1, "kind": "place", "dest": dest, **({"mode": mode} if mode else {})}
    if kind == "video":  # server-made: the agent says only what to look for; results are added by video_stage()
        q = _str(obj.get("query"), 120)
        return None if q is None else {"v": 1, "kind": "video", "query": q}
    return None


_VID = re.compile(r"[A-Za-z0-9_-]{11}")


def search_url(query):
    return "https://www.youtube.com/results?search_query=" + quote_plus(query)


def video_search(query, run=subprocess.run):
    """-> up to 3 {id,title,channel,duration} from yt-dlp, or [] on any failure. argv list, one query argument, 8 s."""
    try:
        r = run(["yt-dlp", "--flat-playlist", "-J", "ytsearch3:" + query], capture_output=True, timeout=8, check=False)
        entries = json.loads(r.stdout.decode("utf-8", "replace")).get("entries") or []
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return []
    out = []
    for e in entries[:3]:
        if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not _VID.fullmatch(e["id"]):
            continue
        d = e.get("duration")
        d = int(d) if isinstance(d, (int, float)) and not isinstance(d, bool) and d >= 0 else None
        title = _CTRL.sub(" ", str(e.get("title") or "Untitled"))[:120].strip()
        chan = _CTRL.sub(" ", str(e.get("channel") or e.get("uploader") or ""))[:80].strip()
        out.append({"id": e["id"], "title": title or "Untitled", "channel": chan,
                    "duration": "" if d is None else "%d:%02d" % divmod(d, 60) if d < 3600 else "%d:%02d:%02d" % (d // 3600, d % 3600 // 60, d % 60)})
    return out


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def fetch_thumb(vid, limit=200_000, timeout=5):
    """-> (bytes, content-type) of a video's poster from i.ytimg.com only (no redirects, <= limit), else None."""
    if not _VID.fullmatch(vid or ""):
        return None
    url = "https://i.ytimg.com/vi/%s/mqdefault.jpg" % vid
    if urlparse(url).hostname != "i.ytimg.com":
        return None
    try:
        with urllib.request.build_opener(_NoRedirect).open(urllib.request.Request(url, headers={"User-Agent": "nixi"}), timeout=timeout) as r:
            ct = r.headers.get("Content-Type", "")
            data = r.read(limit + 1)
    except (OSError, urllib.error.URLError, ValueError):
        return None
    return (data, ct) if len(data) <= limit and ct in ("image/jpeg", "image/webp", "image/png") else None


class Store:
    """The current stage and the one before it; tokens are only valid for the current one."""

    def __init__(self, ttl=600, now=time.monotonic, on_new=None):
        self.ttl, self.now, self.lock, self.on_new = ttl, now, threading.Lock(), on_new
        self.cur = self.prev = None  # (page_stage, {token: (kind, item)}, born)
        self.vis = False             # the page really drew the current stage (it may decline: fullscreen, dictation...)

    def _live(self, e):
        return e if e and self.now() - e[2] < self.ttl else None

    def put(self, stage):
        """-> the stage for the page: items (or the stage) carry a token, nothing else added."""
        toks, page = {}, dict(stage)
        if stage["kind"] == "commands":
            page["items"] = []
            for it in stage["items"]:
                t = secrets.token_urlsafe(12)
                toks[t] = ("command", it)
                page["items"].append({**it, "token": t})
        elif stage["kind"] == "video":  # play + poster tokens per result, and one to search in the browser
            page["items"] = []
            for it in stage.get("items", []):
                pt, tt = secrets.token_urlsafe(12), secrets.token_urlsafe(12)
                toks[pt] = ("video", {"url": "https://www.youtube.com/watch?v=" + it["id"]})
                toks[tt] = ("thumb", {"id": it["id"]})
                page["items"].append({"title": it["title"], "channel": it["channel"], "duration": it["duration"], "play": pt, "thumb": tt})
            page["search"] = secrets.token_urlsafe(12)
            toks[page["search"]] = ("video", {"url": search_url(stage["query"])})
        elif stage["kind"] == "place":  # the page gets two tokens, never the URL
            page["open"], page["copy"] = secrets.token_urlsafe(12), secrets.token_urlsafe(12)
            toks[page["open"]] = ("place", {"url": maps_url(stage["dest"], stage.get("mode"))})
            toks[page["copy"]] = ("place", {"text": stage["dest"]})
        else:  # facts: one token, Copy takes the whole text
            t = secrets.token_urlsafe(12)
            toks[t] = ("facts", {"text": "\n".join([stage["title"], *stage["points"]])})
            page["token"] = t
        with self.lock:
            self.prev, self.cur, self.vis = self.cur, (page, toks, self.now()), False
        if self.on_new:
            self.on_new()
        return page

    def get(self, token):
        """-> (kind, item) for a token of the current stage, else None."""
        with self.lock:
            e = self._live(self.cur)
            return e[1].get(token) if e else None

    def current(self):
        with self.lock:
            e = self._live(self.cur)
            return e[0] if e else None

    def back(self):
        """Swap in the previous stage; -> it, or None when there is none (or it expired)."""
        with self.lock:
            e = self._live(self.prev)
            if not e:
                return None
            self.cur, self.prev, self.vis = e, self.cur, False
            return e[0]

    def has_prev(self):
        with self.lock:
            return bool(self._live(self.prev))

    def visible(self):
        with self.lock:
            return bool(self.vis and self._live(self.cur))

    def set_visible(self, v):
        with self.lock:
            self.vis = bool(v and self._live(self.cur))

    def close(self):
        with self.lock:
            self.prev, self.cur, self.vis = self.cur, None, False

    def clear(self):
        """Forget both stages (Answer stages was turned off): nothing can be restored."""
        with self.lock:
            self.prev = self.cur = None
            self.vis = False


def maps_url(dest, mode=None):
    """Directions to dest, or a place search when mode is None. No origin, no key."""
    dest = (dest or "").strip()
    if not dest or _CTRL.search(dest):
        raise ValueError("bad destination")
    if mode is None:
        return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(dest)
    if mode not in MODES:
        raise ValueError("bad mode")
    return "https://www.google.com/maps/dir/?api=1&destination=%s&travelmode=%s" % (quote_plus(dest), mode)


_ORD = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4,
        "one": 0, "two": 1, "three": 2, "four": 3, "five": 4,
        "1": 0, "2": 1, "3": 2, "4": 3, "5": 4}
_N = "|".join(_ORD)
_ACT = re.compile(r"(run|copy|play|open)\s+(?:(?:the|number|option|item)\s+)*(?:(%s)(?:\s+one)?|(it|that|this)(?:\s+one)?)" % _N)
_PLAIN = {"close": "close", "go back": "back", "show it": "show"}


def fast_path(said, stage):
    """-> (action, index) for a phrase the server can handle without an agent turn, else None.

    index is 0-based; None for close/back/show; ("ask", None) when "it" is ambiguous.
    """
    t = re.sub(r"[^a-z0-9 ]", " ", (said or "").lower())
    t = re.sub(r"^(?:please|nixi)\s+", "", " ".join(t.split()))
    t = re.sub(r"\s+please$", "", t)
    if t in _PLAIN:
        return _PLAIN[t], None
    m = _ACT.fullmatch(t)
    if not m or not stage:
        return None
    n = len(stage.get("items") or [None])  # facts: one target
    if m.group(2):
        i = _ORD[m.group(2)]
        return (m.group(1), i) if i < n else None
    return (m.group(1), 0) if n == 1 else ("ask", None)
