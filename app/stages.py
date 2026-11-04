"""Answer stages: cut the typed block out of a reply, validate it, hold it behind tokens.

The agent ends a reply with one line `<<stage>>{"v":1,"kind":...}`. Nothing here trusts it:
unknown kinds, long fields and control characters drop the whole block (the answer stays a
caption). The page only ever sees tokens; the server alone builds URLs and looks up commands.
"""
import datetime
import json
import math
import re
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import quote_plus

MARK = "<<stage"
MODES = ("driving", "walking", "bicycling", "transit")
_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
SERVER_KINDS = ("weather", "calendar", "status")
CAL_URL = "https://calendar.google.com"


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


def _finite(v):
    try:
        return type(v) in (int, float) and math.isfinite(v)
    except OverflowError:
        return False


def _gauges_text(stage):
    lines = [stage["title"]]
    for host in stage["hosts"]:
        lines.append(f'{host["name"]} ({host["state"]})')
        lines.extend(f'{b["k"]}: {b["v"]}' for b in host["badges"])
        for meter in host["meters"]:
            value = "—" if meter["pct"] is None else f'{meter["pct"]}%'
            parts = [f'{meter["label"]}: {value}']
            if "v" in meter:
                parts.append(str(meter["v"]))
            if "text" in meter:
                parts.append(meter["text"])
            lines.append(" ".join(parts))
        lines.extend(f'{item["title"]}: {", ".join(item["items"])}' for item in host["lists"])
    return "\n".join(lines)


PLUGIN_ONLY = ("gauges", "headlines")   # kinds only a stage plugin may return: never from the agent's own <<stage>> block (#166 review)


def validate(obj, plugin_ok=None):
    """-> a clean stage dict built from known keys only, or None. kind "plugin" (the agent asks for a stage plugin; the
    server runs it, the page never sees it) passes only for an id plugin_ok() accepts: none when plugin_ok is not given."""
    if not isinstance(obj, dict) or obj.get("v") != 1:
        return None
    kind = obj.get("kind")
    if kind in PLUGIN_ONLY and plugin_ok is not None:   # (plugin_ok is given only for the agent's block)
        return None
    if kind == "plugin":
        pid = obj.get("id")
        return {"v": 1, "kind": "plugin", "id": pid} if isinstance(pid, str) and plugin_ok and plugin_ok(pid) else None
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
        if "say" in obj:
            say = _str(obj["say"], 200)
            if say is None:
                return None
            out["say"] = say
        return out
    if kind == "headlines":
        title, items = _str(obj.get("title"), 80), obj.get("items")
        if title is None or not isinstance(items, list) or not 1 <= len(items) <= 5:
            return None
        out = {"v": 1, "kind": "headlines", "title": title, "items": []}
        for key, limit in (("source", 120), ("say", 200)):
            if key in obj:
                value = _str(obj[key], limit)
                if value is None:
                    return None
                out[key] = value
        for item in items:
            if not isinstance(item, dict) or "at" not in item:
                return None
            headline, source, at = _str(item.get("title"), 160), _str(item.get("source"), 40), item["at"]
            if headline is None or source is None or (at is not None and (type(at) is not int or at <= 0)):
                return None
            clean = {"title": headline, "source": source, "at": None if at is not None and at > time.time() + 600 else at}
            if news_url_ok(item.get("url")):
                clean["url"] = item["url"]
            out["items"].append(clean)
        return out
    if kind == "gauges":
        title, src = _str(obj.get("title"), 80), obj.get("source")
        hosts = obj.get("hosts")
        if title is None or ("source" in obj and _str(src, 120) is None) or not isinstance(hosts, list) or not 1 <= len(hosts) <= 6:
            return None
        if "live" in obj and type(obj["live"]) is not bool:
            return None
        out = {"v": 1, "kind": "gauges", "title": title, "hosts": []}
        if "source" in obj:
            out["source"] = _str(src, 120)
        if "live" in obj:
            out["live"] = obj["live"]
        if "say" in obj:
            say = _str(obj["say"], 200)
            if say is None:
                return None
            out["say"] = say
        for host in hosts:
            if not isinstance(host, dict) or not isinstance(host.get("name"), str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,32}", host["name"]):
                return None
            if host.get("state", "up") not in ("up", "down", "stale"):
                return None
            h = {"name": host["name"], "state": host.get("state", "up")}
            for key, limit in (("badges", 6), ("meters", 8), ("lists", 2)):
                items = host.get(key, [])
                if not isinstance(items, list) or len(items) > limit:
                    return None
                h[key] = []
                for item in items:
                    if not isinstance(item, dict) or ("tone" in item and item["tone"] not in ("ok", "warn", "bad")):
                        return None
                    if key == "badges":
                        k, v = _str(item.get("k"), 16), _str(item.get("v"), 60)
                        if k is None or v is None:
                            return None
                        clean = {"k": k, "v": v}
                    elif key == "meters":
                        label, pct = _str(item.get("label"), 12), item.get("pct")
                        if label is None or "pct" not in item or (pct is not None and (not _finite(pct) or not 0 <= pct <= 100)):
                            return None
                        clean = {"label": label, "pct": pct}
                        if "v" in item:
                            v = item["v"]
                            if not _finite(v) or v < 0:
                                return None
                            clean["v"] = v
                        if "text" in item:
                            value = _str(item["text"], 40)
                            if value is None:
                                return None
                            clean["text"] = value
                    else:
                        heading, values = _str(item.get("title"), 24), item.get("items")
                        if heading is None or not isinstance(values, list) or len(values) > 5:
                            return None
                        values = [_str(v, 80) for v in values]
                        if None in values:
                            return None
                        clean = {"title": heading, "items": values}
                    if "tone" in item:
                        clean["tone"] = item["tone"]
                    h[key].append(clean)
            out["hosts"].append(h)
        return out
    if kind == "place":
        dest, mode = _str(obj.get("dest"), 160), obj.get("mode")
        if dest is None or (mode is not None and mode not in MODES):
            return None
        return {"v": 1, "kind": "place", "dest": dest, **({"mode": mode} if mode else {})}
    if kind == "day":  # server-made, off the turn: day.snapshot() runs in a thread, see server.day_stage()
        return {"v": 1, "kind": "day"}
    if kind in SERVER_KINDS:  # the agent only asks; desk_stage() fills them from what the server already has cached
        return {"v": 1, "kind": kind}
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
        r = run(["yt-dlp", "--ignore-config", "--flat-playlist", "-J", "ytsearch3:" + query], capture_output=True, timeout=8, check=False)
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


_DIRS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def sky_stage(source, sky, heavy, feel, temp, wind, deg, at, day, off=False):
    """The weather stage from a cached reading (Ambient.reading()); at = 'HH:MM' of that reading. No source: nothing cached.
    There is no forecast: neither source returns one, so the stage never shows one."""
    if source is None:
        return {"v": 1, "kind": "weather", "empty": True, "off": bool(off)}
    r = lambda v: None if v is None else round(v)
    return {"v": 1, "kind": "weather", "source": source, "sky": sky, "heavy": bool(heavy), "temp": r(temp), "feel": r(feel),
            "wind": r(wind), "dir": None if deg is None else _DIRS[round(deg / 45) % 8], "at": at, "day": bool(day)}


_HOSTS = ("meet.google.com", "zoom.us", "teams.microsoft.com", "teams.live.com")
_SUFFIX = (".zoom.us", ".webex.com")


def _meeting_ok(u):
    if not isinstance(u, str) or len(u) > 300 or re.search(r"[\s\x00-\x1f\x7f-\x9f]", u):
        return False
    try:
        p = urllib.parse.urlsplit(u)
        host = (p.hostname or "").lower()
    except ValueError:
        return False
    return p.scheme == "https" and not p.username and (host in _HOSTS or host.endswith(_SUFFIX))


_ITEM_HOSTS = ("github.com", "calendar.google.com", "meet.google.com")
BIRTHDAY = re.compile(r"birthday|bursdag", re.I)         # a calendar item that is a birthday: never shown, never summarised


def item_url_ok(u):
    """A day-desk item URL: https, no user-info, and exactly github.com, calendar.google.com, meet.google.com, or www.google.com/calendar/."""
    if not isinstance(u, str) or len(u) > 300 or re.search(r"[\s\x00-\x1f\x7f-\x9f]", u):
        return False
    try:
        p = urllib.parse.urlsplit(u)
        host = (p.hostname or "").lower()
        return p.scheme == "https" and not p.username and (host in _ITEM_HOSTS or (host == "www.google.com" and p.path.startswith("/calendar/")))   # (Google's own event link)
    except ValueError:
        return False


def news_url_ok(u):
    """HTTPS news link on a public-looking DNS name; the browser handles DNS and redirects."""
    if not isinstance(u, str) or len(u) > 400 or re.search(r"[\s\x00-\x1f\x7f-\x9f]", u):
        return False
    try:
        p = urllib.parse.urlsplit(u)
        host = (p.hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    labels = host.split(".")
    return (p.scheme == "https" and bool(p.netloc) and not any(c in p.netloc for c in ":@")
            and len(labels) >= 2 and all(re.fullmatch(r"[a-z0-9-]{1,63}", x) for x in labels)
            and bool(re.fullmatch(r"[a-z]{2,63}", labels[-1]))
            and host != "localhost" and not host.endswith((".localhost", ".local", ".lan", ".home", ".internal", ".home.arpa", ".ts.net")))


def meeting_link(event):
    """A calendar event's join link: a video conferenceData entry point, else hangoutLink; https on a known meeting host only.
    Never from the title or notes."""
    cd, cands = event.get("conferenceData"), []
    if isinstance(cd, dict):
        cands += [ep.get("uri") for ep in cd.get("entryPoints") or [] if isinstance(ep, dict) and ep.get("entryPointType") == "video"]
    cands.append(event.get("hangoutLink"))
    return next((u for u in cands if _meeting_ok(u)), None)


def calendar_rows(items, now, n=4):
    """The next n events from [{start (aware datetime or None for all-day), end (aware datetime or None), end_day (exclusive
    'YYYY-MM-DD' of an all-day event, or None), day 'YYYY-MM-DD', title, link}] -> [{when,title,link}]. A timed event stays
    until it ends; a multi-day all-day one stays through its last day. Local zone rules, so a DST change cannot shift a time."""
    now = now.astimezone()
    today = now.date().isoformat()
    rows = []
    for e in items:
        st = e["start"].astimezone() if e["start"] else None
        if st:
            end = e.get("end")
            keep = (end.astimezone() > now) if end else st >= now
        else:
            keep = e["day"] >= today or (e.get("end_day") or "") > today
        if keep:
            d = st.date().isoformat() if st else max(e["day"], today)
            hm = st.strftime("%H:%M") if st else ""
            rows.append(((d, hm), {"when": (hm or "all day") if d == today else datetime.date.fromisoformat(d).strftime("%a") + (" " + hm if hm else ""),
                                   "title": e["title"], "link": e.get("link")}))
    return [r for _, r in sorted(rows, key=lambda x: x[0])[:n]]


def calendar_stage(events, at):
    """events None = the calendar cue is off (nothing cached); at = 'HH:MM' of the fetch, or None."""
    return {"v": 1, "kind": "calendar", "events": events or [], "off": events is None, "unread": events is not None and at is None, "at": at}


def status_stage(sessions, failed, sys_on):
    """sessions [{title,status,pane}], failed = unit names, sys_on = the system list is being kept (else 'not checked')."""
    return {"v": 1, "kind": "status", "sessions": sessions[:5], "failed": failed[:5], "failed_n": len(failed), "sys_on": bool(sys_on)}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def fetch_thumb(vid, limit=200_000, timeout=5):
    """-> (bytes, content-type) of a video's poster from i.ytimg.com only (no redirects, <= limit), else None."""
    if not _VID.fullmatch(vid or ""):
        return None
    url = "https://i.ytimg.com/vi/%s/mqdefault.jpg" % vid
    try:
        with urllib.request.build_opener(_NoRedirect).open(urllib.request.Request(url, headers={"User-Agent": "nixi"}), timeout=timeout) as r:
            ct = r.headers.get("Content-Type", "")
            data = r.read(limit + 1)
    except (OSError, urllib.error.URLError, ValueError):
        return None
    return (data, ct) if len(data) <= limit and ct in ("image/jpeg", "image/webp", "image/png") else None


class Store:
    """The current stage and the one before it; tokens are only valid for the current one."""

    def __init__(self, ttl=600, now=time.monotonic, on_new=None, where=None):
        self.ttl, self.now, self.lock, self.on_new = ttl, now, threading.Lock(), on_new
        self.where = where           # -> {"now", "chosen", "home", "work"}: the user's places (server.location), or None
        self.cur = self.prev = None  # (page_stage, {token: (kind, item)}, born)
        self.vis = False             # the page really drew the current stage (it may decline: fullscreen, dictation...)

    def _live(self, e):
        return e if e and self.now() - e[2] < self.ttl else None

    def put(self, stage, refresh=None):
        """-> the stage for the page: items (or the stage) carry a token, nothing else added."""
        toks, page = {}, dict(stage)
        page.pop("say", None)
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
            toks[page["search"]] = ("link", {"url": search_url(stage["query"])})
        elif stage["kind"] == "place":  # the page gets two tokens, never the URL
            self._place(stage, page, toks)
        elif stage["kind"] == "day":        # every item URL becomes a token (allowlisted hosts only); the page never sees a URL
            self._day(stage, page, toks)
        elif stage["kind"] == "weather":    # read-only: nothing to press
            pass
        elif stage["kind"] == "calendar":   # Join per event with a link, and Open calendar; URLs held here, the page gets tokens
            page["events"], page["open"] = [], secrets.token_urlsafe(12)
            toks[page["open"]] = ("link", {"url": CAL_URL})
            for e in stage["events"]:
                d = {"when": e["when"], "title": e["title"]}
                if e.get("link"):
                    d["join"] = secrets.token_urlsafe(12)
                    toks[d["join"]] = ("link", {"url": e["link"]})
                page["events"].append(d)
        elif stage["kind"] == "status":     # Open session by pane id (so two sessions with one name stay apart) and Open terminal
            page["sessions"], page["term"] = [], secrets.token_urlsafe(12)
            toks[page["term"]] = ("terminal", {})
            for x in stage["sessions"]:
                t = secrets.token_urlsafe(12)
                toks[t] = ("session", {"pane": x["pane"]})
                page["sessions"].append({"title": x["title"], "status": x["status"], "open": t})
        elif stage["kind"] == "gauges":
            page["token"] = secrets.token_urlsafe(12)
            toks[page["token"]] = ("facts", {"text": _gauges_text(stage)})
            if stage.get("live") and refresh is not None:
                page["refresh"] = secrets.token_urlsafe(12)
                toks[page["refresh"]] = ("refresh", {"pid": refresh[0], "query": refresh[1]})
        elif stage["kind"] == "headlines":
            page["items"] = []
            page["copy"] = secrets.token_urlsafe(12)
            toks[page["copy"]] = ("facts", {"text": "\n".join(f'{it["title"]} — {it["source"]}' for it in stage["items"])})
            for it in stage["items"]:
                row = {k: v for k, v in it.items() if k != "url"}
                if "url" in it:
                    row["open"] = secrets.token_urlsafe(12)
                    toks[row["open"]] = ("link", {"url": it["url"]})
                page["items"].append(row)
        else:  # facts: one token, Copy takes the whole text
            t = secrets.token_urlsafe(12)
            toks[t] = ("facts", {"text": "\n".join([stage["title"], *stage["points"]])})
            page["token"] = t
        with self.lock:
            self.prev, self.cur, self.vis = self.cur, (page, toks, self.now()), False
        if self.on_new:
            self.on_new()
        return page

    def replace(self, refresh_token, stage):
        """Update the current gauges page while preserving its tokens and age."""
        if stage.get("kind") != "gauges":
            return None
        with self.lock:
            e = self._live(self.cur)
            if not e or e[0].get("refresh") != refresh_token or e[1].get(refresh_token, (None,))[0] != "refresh":
                return None
            page, toks = dict(stage), dict(e[1])
            page.pop("say", None)
            page["token"], page["refresh"] = e[0]["token"], refresh_token
            toks[page["token"]] = ("facts", {"text": _gauges_text(stage)})
            self.cur = (page, toks, e[2])
            return page

    def _day(self, stage, page, toks):
        def tok(url, ok):
            if not ok(url):
                return None
            t = secrets.token_urlsafe(12)
            toks[t] = ("link", {"url": url})
            return t
        n = stage.get("next")
        if n:
            page["next"] = {"when": n["when"], "title": n["title"], "in": n["in"], "open": tok(n.get("url"), item_url_ok), "join": tok(n.get("link"), _meeting_ok)}
        page["rows"] = [{**r, "items": [{"when": i["when"], "title": i["title"], "bad": bool(i.get("overdue")), "open": tok(i.get("url"), item_url_ok)}
                                       for i in r["items"][:8]]} for r in stage["rows"]]

    def _place(self, stage, page, toks):
        """@home / @work become the stored place (the agent never sees the address); a place the user chose is where
        directions start. An unset Home or Work gets no token at all: there is nothing to open or copy."""
        try:
            loc = (self.where() if self.where else None) or {}
        except Exception:                                  # (a broken lookup is "no location", never a lost card)
            loc = {}
        dest = stage["dest"]
        if dest.strip().lower() in ("@home", "@work"):
            p = loc.get(dest.strip().lower()[1:])
            if not p:
                page["unset"] = dest.strip().lower()[1:]
                return
            page["dest"], dest = p["name"], _coords(p)
        origin = None
        if stage.get("mode") and loc.get("chosen") and loc.get("now"):      # (a plain place search has no start)
            origin, page["from"] = _coords(loc["now"]), loc["now"]["name"]
        page["open"], page["copy"] = secrets.token_urlsafe(12), secrets.token_urlsafe(12)
        toks[page["open"]] = ("place", {"url": maps_url(dest, stage.get("mode"), origin)})
        toks[page["copy"]] = ("place", {"text": page["dest"]})

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


def _coords(p):
    """"lat,lon" when the place has them, else its name: Maps takes either."""
    return "%s,%s" % (p["latitude"], p["longitude"]) if "latitude" in p and "longitude" in p else p["name"]


def maps_url(dest, mode=None, origin=None):
    """Directions to dest, or a place search when mode is None. An origin only when given (and only for directions); no key."""
    dest = (dest or "").strip()
    if not dest or _CTRL.search(dest):
        raise ValueError("bad destination")
    if mode is None:
        return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(dest)
    if mode not in MODES:
        raise ValueError("bad mode")
    if origin is not None and (not origin.strip() or _CTRL.search(origin)):
        raise ValueError("bad origin")
    return "https://www.google.com/maps/dir/?api=1&destination=%s&travelmode=%s%s" % (
        quote_plus(dest), mode, "&origin=" + quote_plus(origin.strip()) if origin else "")


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
    if not m or not stage or stage.get("kind") == "day":  # (the day desk is clicked in v1: no voice-numbered opening)
        return None
    n = len(stage.get("items") or stage.get("sessions") or [None])  # facts: one target; a status stage: its sessions
    if stage.get("kind") == "headlines" and m.group(1) == "copy":
        return "copy", 0
    if stage.get("kind") == "status" and not stage.get("sessions"):
        return None
    if m.group(2):
        i = _ORD[m.group(2)]
        return (m.group(1), i) if i < n else None
    return (m.group(1), 0) if n == 1 else ("ask", None)
