"""The day desk's data (#144 slice 4): today's calendar, tasks and GitHub, fetched off the answer thread.

Each source runs as an argv list with an 8 s budget and a 5 min cache keyed by the local date, so yesterday's data can
never serve today. A failure keeps the last good data of the same day, marked stale. Titles stay in memory: this module
never logs. Standard library only; nothing here uses a shell.
"""
import datetime
import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import stages

TTL = 300
BUDGET = 8
TASKS_URL = "https://calendar.google.com/calendar/u/0/r/tasks"
_cache = {}                 # (source, 'YYYY-MM-DD') -> (monotonic, items, 'HH:MM')
_lock = threading.Lock()


class _Off(Exception):      # not set up (tool missing, nothing to read, signed out)
    pass


class _Fail(Exception):     # set up, but this fetch didn't work
    pass


def _json(argv, deadline, run):
    """-> the parsed stdout of argv. Success is the exit code plus valid JSON; stderr is ignored (gog chats on it)."""
    left = deadline - time.monotonic()
    if left <= 0:
        raise _Fail()
    try:
        r = run(argv, capture_output=True, timeout=min(BUDGET, left), check=False, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise _Off()
    except (OSError, subprocess.SubprocessError):
        raise _Fail()
    if r.returncode != 0:
        raise _Fail()
    try:
        return json.loads(r.stdout.decode("utf-8", "replace"))
    except ValueError:
        raise _Fail()


def _txt(v, n=120):
    return stages._CTRL.sub(" ", str(v or "")).strip()[:n]


def _loc(v):
    return datetime.datetime.fromisoformat(v).astimezone()      # (a naive time is local time)


def window(now):
    """-> (local midnight today, next local midnight) as aware datetimes; built from the date so a DST day is 23 or 25 h."""
    d = now.astimezone().date()
    at = lambda x: datetime.datetime.combine(x, datetime.time.min).astimezone()
    return at(d), at(d + datetime.timedelta(days=1))


def _cal(ids, start, end, deadline, run):
    if not ids:
        raise _Off()
    out = _json(["gog", "--readonly", "--json", "calendar", "events", *ids, "--from", start.isoformat(), "--to", end.isoformat(),
                 "--sort", "start", "--max", "50"], deadline, run)
    items = []
    for e in (out.get("events") if isinstance(out, dict) else None) or []:
        try:
            s, f = e.get("start") or {}, e.get("end") or {}
            st = _loc(s["dateTime"]) if s.get("dateTime") else None
            day = str(s.get("dateTime") or s.get("date") or "")[:10]
            if not day:
                continue
            url = e.get("htmlLink")
            items.append({"allDay": st is None, "start": st, "end": _loc(f["dateTime"]) if f.get("dateTime") else None, "day": day,
                          "end_day": str(f.get("date") or "")[:10] or None, "title": _txt(e.get("summary")) or "(busy)",
                          "link": stages.meeting_link(e), "url": url if stages.item_url_ok(url) else stages.CAL_URL})
        except (ValueError, AttributeError, TypeError, KeyError):
            continue                                       # one bad event never drops the day
    return items


def _tasks(due_max, deadline, run):
    out = _json(["gog", "--readonly", "--json", "tasks", "lists"], deadline, run)
    lists = [x["id"] for x in (out.get("tasklists") if isinstance(out, dict) else None) or [] if isinstance(x, dict) and isinstance(x.get("id"), str)]
    items = []
    for lid in lists[:3]:
        got = _json(["gog", "--readonly", "--json", "tasks", "list", lid, "--due-max", due_max.isoformat()], deadline, run)
        for t in (got.get("tasks") if isinstance(got, dict) else None) or []:
            if isinstance(t, dict) and t.get("status") != "completed" and str(t.get("due") or "")[:10]:
                items.append({"title": _txt(t.get("title")) or "(untitled)", "due": str(t["due"])[:10], "url": TASKS_URL})
    return items


def _github(deadline, run):
    try:                                                     # (signed out is "off", not "failed")
        _json_rc(["gh", "auth", "status"], deadline, run)
    except _Fail:
        raise _Off()
    items = []
    for kind, flag, pr in (("prs", "--review-requested=@me", True), ("issues", "--assignee=@me", False)):
        for x in _json(["gh", "search", kind, flag, "--state=open", "--json", "repository,number,title,url", "-L", "8"], deadline, run) or []:
            try:
                repo = x["repository"].get("name") or x["repository"]["nameWithOwner"].split("/")[-1]
                items.append({"repo": _txt(repo, 60), "number": int(x["number"]), "title": _txt(x.get("title")) or "(untitled)", "pr": pr,
                              "url": x["url"] if stages.item_url_ok(x.get("url")) else None})
            except (KeyError, AttributeError, TypeError, ValueError):
                continue
    return items


def _json_rc(argv, deadline, run):
    """Like _json, for a command whose output isn't JSON (gh auth status): only the exit code counts."""
    left = deadline - time.monotonic()
    try:
        r = run(argv, capture_output=True, timeout=max(0.1, min(BUDGET, left)), check=False, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise _Off()
    except (OSError, subprocess.SubprocessError):
        raise _Fail()
    if r.returncode != 0:
        raise _Fail()


def _source(name, date, now, fetch, cache_only=False):
    """-> (items, status): 'ok', 'off' or 'stale@HH:MM'. Fresh cache first; a failed fetch falls back to the same day's last good data."""
    key, hm = (name, date), now.strftime("%H:%M")
    with _lock:
        for k in [k for k in _cache if k[1] != date]:      # (yesterday's entries are dropped, not kept for a fallback)
            del _cache[k]
        e = _cache.get(key)
    if e and time.monotonic() - e[0] < TTL:
        return e[1], "ok"
    if cache_only:
        return None, "none"
    try:
        items = fetch(time.monotonic() + BUDGET)
    except _Off:
        return [], "off"
    except _Fail:
        return (e[1], "stale@" + e[2]) if e else ([], "stale@" + hm)
    with _lock:
        _cache[key] = (time.monotonic(), items, hm)
    return items, "ok"


def _in(secs):
    m = max(1, -(-int(secs) // 60))
    return "in %d min" % m if m < 60 else "in %d h" % (m // 60) + (" %d min" % (m % 60) if m % 60 else "")


def build(now, cal, tasks, gh, status):
    """Raw items -> the snapshot. Called with the current time every time, so a cached calendar never shows a finished event."""
    now = now.astimezone()
    today = now.date().isoformat()
    timed = sorted((e for e in cal if not e["allDay"] and ((e["end"] > now) if e["end"] else e["start"] >= now)), key=lambda e: e["start"])
    nextday = lambda e: e["end_day"] or (datetime.date.fromisoformat(e["day"]) + datetime.timedelta(days=1)).isoformat()   # (an all-day end date is exclusive)
    allday = [e for e in cal if e["allDay"] and e["day"] <= today < nextday(e)]
    row = lambda e: {"when": "all day" if e["allDay"] else "now" if e["start"] <= now else e["start"].strftime("%H:%M"),
                     "title": e["title"], "link": e["link"], "url": e["url"]}
    nxt = None
    if timed:
        e = timed[0]
        nxt = {**row(e), "in": "now" if e["start"] <= now else _in((e["start"] - now).total_seconds())}
    rest = [row(e) for e in allday] + [row(e) for e in timed[1:]]
    tk = sorted(tasks, key=lambda t: t["due"])
    tk = [{"when": "overdue" if t["due"] < today else "today", "title": t["title"], "overdue": t["due"] < today, "url": t["url"]} for t in tk if t["due"] <= today]
    gl = [{"when": "%s#%d" % (g["repo"], g["number"]), "title": g["title"], "url": g["url"], "pr": g["pr"]} for g in gh]
    return {"date": today, "at": now.strftime("%H:%M"), "next": nxt, "today": rest[:8], "tasks": tk[:8], "github": gl[:8],
            "count": {"today": len(rest), "tasks": len(tk), "github": len(gl)}, "status": status}


def snapshot(now, cal_ids, run=subprocess.run, cache_only=False):
    """-> the day's snapshot, fetching the three sources at once (or, with cache_only, None unless all three are cached for today)."""
    now = now.astimezone()
    date = now.date().isoformat()
    start, end = window(now)
    fetch = {"cal": lambda d: _cal(cal_ids, start, end, d, run), "tasks": lambda d: _tasks(end, d, run), "gh": lambda d: _github(d, run)}
    with ThreadPoolExecutor(3) as ex:
        got = dict(zip(fetch, ex.map(lambda k: _source(k, date, now, fetch[k], cache_only), fetch)))
    if cache_only and any(s == "none" for _, s in got.values()):
        return None
    return build(now, got["cal"][0], got["tasks"][0], got["gh"][0], {k: v[1] for k, v in got.items()})


def stage(snap):
    """The snapshot as a stage dict for stages.Store (urls still raw: the store swaps them for tokens)."""
    d = datetime.date.fromisoformat(snap["date"])
    st = snap["status"]
    rows = [{"key": k, "label": lab, "n": snap["count"][k], "st": st[s], "items": snap[k]} for k, lab, s in
            (("today", "Today", "cal"), ("tasks", "Tasks", "tasks"), ("github", "GitHub", "gh"))]
    return {"v": 1, "kind": "day", "wd": d.strftime("%A"), "md": "%d %s" % (d.day, d.strftime("%b")), "at": snap["at"], "next": snap["next"],
            "cal": st["cal"], "rows": rows}


def whats_next(snap):
    """The one spoken line for 'what's next?'."""
    c = snap["status"]["cal"]
    if c == "off":
        return "Your calendar isn't set up."
    stale = " That might be out of date." if c.startswith("stale") else ""
    n = snap["next"]
    if not n:
        return "Nothing else timed today." + stale
    if n["in"] == "now":
        return "%s is on now.%s" % (n["title"], stale)
    return "%s %s.%s" % (n["title"], n["in"].replace(" min", " minutes", 1), stale)


def summary(snap):
    """About 150 tokens for an agent question while the desk is open: counts and the top two titles per row."""
    c, s = snap["count"], snap["status"]
    src = {"today": "cal", "tasks": "tasks", "github": "gh"}
    why = lambda k: " (not set up)" if s[src[k]] == "off" else " (may be out of date)" if s[src[k]].startswith("stale") else ""
    top = lambda k, xs: "%d%s%s" % (c[k], why(k), " \u2014 " + "; ".join(_txt(x["title"], 60) for x in xs[:2]) if xs else "")
    n = snap["next"]
    return ("(today, from Nixi's desk, at %s) Next: %s. Today: %s. Tasks: %s. GitHub: %s."
            % (snap["at"], "%s %s (%s)" % (n["when"], _txt(n["title"], 60), n["in"]) if n else "nothing timed",
               top("today", snap["today"]), top("tasks", snap["tasks"]) + (" (%d overdue)" % sum(1 for t in snap["tasks"] if t["overdue"]) if snap["tasks"] else ""), top("github", snap["github"])))
