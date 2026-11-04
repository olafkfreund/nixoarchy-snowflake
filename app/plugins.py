"""Companion plugins (#149): find them, check their manifests, remember which are on. Standard library only."""
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections import namedtuple
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "nixi-companion"

Plugin = namedtuple("Plugin", "id dir manifest source error")

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
REQUIRED = {"api", "id", "name", "version"}
OPTIONAL = {"description", "quips", "prop", "notifications", "stage"}
PROP_KEYS = {"file", "anchor", "layer"}
STAGE_KEYS = {"phrases", "hint", "argv", "network", "cache_seconds", "reads"}
CATEGORIES = {"mail", "chat", "feed"}
APP_RE = re.compile(r"^[a-z0-9._-]+$")
HOST_RE = re.compile(r"^(\*\.)?[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")


def norm(said):
    """What you said, the way stages.fast_path reads it: lowercase, punctuation dropped, one space, no leading please/nixi."""
    t = " ".join(re.sub(r"[^a-z0-9 ]", " ", (said or "").lower()).split())
    return re.sub(r"(?:\s+please)+$", "", re.sub(r"^(?:(?:please|nixi)\s+)+", "", t))


def reserved(phrase):
    """True for a phrase Nixi answers itself: empty, close / go back / show it / what's next, guide / mechanic, the run/copy/play/open
    verbs, and anything the quick matcher handles."""
    import quick
    import stages
    t = norm(phrase)
    if not t or t in ("close", "go back", "show it", "what s next", "what is next", "guide", "mechanic") or stages.fast_path(t, {"items": [0] * 5}) is not None:
        return True
    try:
        return quick.handle(phrase) is not None
    except Exception:                                  # (the matcher needs the server's config for some phrases: those are Nixi's own)
        return True


def plugin_dirs():
    """The package's plugin folder (store or git checkout, both next to app/), then the user's."""
    return [APP_DIR.parent / "plugins", DATA_DIR / "plugins"]


def _inside(base, rel):
    """True if base/rel is a regular file (not a symlink) that really lives inside base (no `..`)."""
    if not isinstance(rel, str) or not rel or os.path.isabs(rel):
        return False
    q = os.path.join(base, rel)
    p = os.path.realpath(q)
    return not os.path.islink(q) and os.path.isfile(p) and os.path.commonpath([os.path.realpath(base), p]) == os.path.realpath(base)


def _raise(e):
    raise e


def _in_store(d):
    return os.path.realpath(d).startswith("/nix/store/")


def _symlink(d):
    """The first symlink anywhere inside the folder (a plugin may not contain any), or None."""
    for dirpath, dirs, files in os.walk(d, onerror=_raise):   # (an unlistable folder is an error, not "nothing in it")
        for n in dirs + files:
            if os.path.islink(os.path.join(dirpath, n)):
                return os.path.relpath(os.path.join(dirpath, n), d)
    return None


def _in(v, allowed):
    return isinstance(v, str) and v in allowed


def _strs(v, n=None):
    return isinstance(v, list) and bool(v) and all(isinstance(x, str) and x for x in v) and (n is None or len(v) <= n)


def _check(m, d):
    """Return the reason the manifest is bad, or None."""
    import stages
    if not isinstance(m, dict):
        return "plugin.json is not an object"
    if "api" not in m:
        return "missing key: api"
    if type(m["api"]) is not int or m["api"] != 1:
        return "needs a newer Nixi"  # before the other checks: a newer api may use other keys
    for k in sorted(REQUIRED - m.keys()):
        return f"missing key: {k}"
    for k in sorted(m.keys() - REQUIRED - OPTIONAL):
        return f"unknown key: {k}"
    if not isinstance(m["id"], str) or not ID_RE.fullmatch(m["id"]):
        return "bad id"
    for k, n in (("name", 60), ("version", 1000), ("description", 200)):
        if k in m and not (isinstance(m[k], str) and 0 < len(m[k]) <= n and not stages._CTRL.search(m[k])):
            return f"bad {k}"
    if "quips" in m and not _inside(d, m["quips"]):
        return "quips file missing or outside the folder"
    if "prop" in m:
        p = m["prop"]
        if not isinstance(p, dict) or p.keys() - PROP_KEYS or not {"file", "anchor"} <= p.keys():
            return "bad prop"
        if not _in(p["anchor"], ("head", "left", "right", "base")) or not _in(p.get("layer", "front"), ("front", "back")):
            return "bad prop anchor or layer"
        if not _inside(d, p["file"]):
            return "prop file missing or outside the folder"
    if "notifications" in m:
        if not isinstance(m["notifications"], list):
            return "bad notifications"
        for n in m["notifications"]:
            if not isinstance(n, dict) or n.keys() not in ({"app", "category"}, {"host", "category"}):
                return "bad notifications entry"
            if not _in(n["category"], CATEGORIES):
                return "bad notification category"
            if "app" in n and not (isinstance(n["app"], str) and APP_RE.fullmatch(n["app"])):
                return "notification app must be a literal lowercase id"
            if "host" in n and not (isinstance(n["host"], str) and HOST_RE.fullmatch(n["host"])):
                return "notification host must be a name or *.suffix"
    if "stage" in m:
        s = m["stage"]
        if not isinstance(s, dict) or s.keys() - STAGE_KEYS or not {"phrases", "argv"} <= s.keys():
            return "bad stage"
        if not _strs(s["phrases"]) or not _strs(s["argv"]):
            return "bad stage phrases or argv"
        if "hint" in s and not (isinstance(s["hint"], str) and len(s["hint"]) <= 79 and not stages._CTRL.search(s["hint"])):
            return "bad stage hint"
        if "network" in s and not isinstance(s["network"], bool):
            return "bad stage network"
        c = s.get("cache_seconds", 60)
        if type(c) is not int or not 0 <= c <= 600:
            return "bad stage cache_seconds"
        if "reads" in s and not (isinstance(s["reads"], list) and all(_in(x, ("system-status",)) for x in s["reads"])):
            return "bad stage reads"
        if not _inside(d, s["argv"][0]):
            return "stage argv[0] missing or outside the folder"
        if any(a.startswith("/") or "=/" in a or ".." in re.split(r"[/=]", a) for a in s["argv"][1:]):
            return "stage argv may not point outside the folder"
        for ph in s["phrases"]:
            if reserved(ph):
                return f"stage phrase {ph!r} clashes with one of Nixi's own"
    return None


def scan(dirs):
    """Every plugin folder under dirs (the first dir counts as Nix, the rest as Folder). Never raises for one plugin."""
    out, valid = [], []
    for i, base in enumerate(dirs):
        try:   # symlinked plugin folders are skipped, except in the first (package) dir, whose entries are store links
            subs = sorted(p for p in Path(base).iterdir() if p.is_dir() and p.name != "examples" and not (i and p.is_symlink()))
        except OSError:
            continue
        for d in subs:
            m, err, vid = None, None, None
            try:
                err = f"contains a symlink: {_symlink(d)}" if _symlink(d) else None
                if not err:
                    m = json.loads((d / "plugin.json").read_text(encoding="utf-8"))
                    err = _check(m, d)
            except FileNotFoundError:
                err = "plugin.json missing"
            except (OSError, ValueError) as e:  # ValueError covers bad JSON and bad UTF-8
                err = f"plugin.json unreadable: {e}"
            except Exception as e:  # one odd manifest must never stop the scan
                err = f"plugin.json not understood: {type(e).__name__}"
            if isinstance(m, dict) and isinstance(m.get("id"), str) and ID_RE.fullmatch(m["id"]):
                vid = m["id"]
            out.append(Plugin(vid or d.name, d, m if isinstance(m, dict) else None, "nix" if i == 0 and _in_store(d) else "folder", err))
            valid.append(vid is not None)
    groups = {}
    for p, ok in zip(out, valid):
        if ok:                                     # (a plugin without a valid id can't clash with anything)
            groups.setdefault(p.id, []).append(p)
    dup = set()
    for g in groups.values():
        nix = [p for p in g if p.source == "nix"]
        if len(g) > 1:                             # a Nix plugin beats a Folder one; otherwise every one of them is marked
            dup.update(id(p) for p in (g if len(nix) != 1 else [p for p in g if p.source != "nix"]))
    return [p._replace(error=p.error or "duplicate id") if id(p) in dup else p for p in out]


def sha256_of(d):
    """Hash of every file's relative path and content, sorted. Raises ValueError if the folder holds any symlink."""
    if _symlink(d):
        raise ValueError(f"contains a symlink: {_symlink(d)}")
    root, h = os.path.realpath(d), hashlib.sha256()
    found = []
    for dirpath, _, files in os.walk(root, onerror=_raise):
        for f in files:
            p = os.path.join(dirpath, f)
            r = os.path.realpath(p)
            if os.path.commonpath([root, r]) == root and os.path.isfile(r):
                found.append((os.path.relpath(p, root).encode(), r))
    for rel, r in sorted(found):
        data = Path(r).read_bytes()
        h.update(b"%d:%s%d:" % (len(rel), rel, len(data)) + data)
    return h.hexdigest()


class State:
    """plugins-state.json: {id: {enabled, sha256}}, written atomically."""

    def __init__(self, path=None):
        self.path = Path(path or DATA_DIR / "plugins-state.json")
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        self.data = d if isinstance(d, dict) else {}

    def get(self, pid):
        v = self.data.get(pid)
        return v if isinstance(v, dict) else {"enabled": False, "sha256": None}

    def set(self, pid, enabled, sha256=None):
        self.data[pid] = {"enabled": bool(enabled), "sha256": sha256}
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".plugins-state-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


# ---- props: one SVG, default-deny. Anything not listed here drops the whole prop. ----
NUM = r"-?(?:\d+(?:\.\d*)?|\.\d+)"
NUM_RE = re.compile(NUM)
COLOR_RE = re.compile(r"none|acc|text|dim|#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6}")
TRANSFORM_RE = re.compile(r"\s*(?:(?:translate|scale|rotate)\(\s*" + NUM + r"(?:(?:\s*,\s*|\s+)" + NUM + r"){0,2}\s*\)\s*)+")
TRANSFORM_ONE = re.compile(r"(translate|scale|rotate)\(\s*([^)]*)\)")
SVG_NS = "{http://www.w3.org/2000/svg}"
GEOMETRY = {"svg": {"viewBox"}, "g": set(), "path": {"d"}, "circle": {"cx", "cy", "r"}, "ellipse": {"cx", "cy", "rx", "ry"},
            "rect": {"x", "y", "width", "height", "rx", "ry"}, "line": {"x1", "y1", "x2", "y2"}, "polyline": {"points"}, "polygon": {"points"}}
STYLE = {"fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "fill-opacity", "stroke-opacity", "opacity", "fill-rule", "transform"}
ENUMS = {"stroke-linecap": {"butt", "round", "square"}, "stroke-linejoin": {"miter", "round", "bevel"}, "fill-rule": {"nonzero", "evenodd"}}
MAX_BYTES, MAX_ELEMENTS, MAX_DEPTH, MAX_D, MAX_NUM, MAX_VALUE, MAX_SCALE = 16 * 1024, 200, 8, 4000, 1000, 64, 10


def _nums(s):
    ns = [float(x) for x in NUM_RE.findall(s)]
    if any(abs(n) > MAX_NUM for n in ns):
        raise ValueError("a number is outside ±1000")
    return ns


def _scale(v):
    """The biggest scale() factor in a transform (1 if none); every factor must lie between 0.01 and 10."""
    top = 1.0
    for f, a in TRANSFORM_ONE.findall(v):
        if f == "scale":
            for n in _nums(a):
                if not 0.01 <= n <= MAX_SCALE:
                    raise ValueError("scale must be between 0.01 and 10")
                top = max(top, n)
    return top


def _attr(tag, k, v):
    if len(v) > (MAX_D if k in ("d", "points") else MAX_VALUE):   # (before any regex runs on it)
        raise ValueError(f"{k} is too long")
    if k in GEOMETRY[tag]:
        if tag == "path":
            if not re.fullmatch(r"[MmLlHhVvCcSsQqTtAaZz0-9.,\s-]*", v):
                raise ValueError("bad path data")
            _nums(v)
        elif k in ("points", "viewBox"):
            if not re.fullmatch(r"[0-9.,\s-]*", v):
                raise ValueError(f"bad {k}")
            ns = _nums(v)
            if k == "viewBox" and (len(ns) != 4 or ns[2] < 1 or ns[3] < 1):
                raise ValueError("bad viewBox")
        elif not re.fullmatch(NUM, v) or abs(float(v)) > MAX_NUM:
            raise ValueError(f"bad number in {k}")
    elif k in STYLE and tag != "svg":
        if k in ("fill", "stroke"):
            ok = COLOR_RE.fullmatch(v)
        elif k == "transform":
            ok = TRANSFORM_RE.fullmatch(v) and all(
                len(NUM_RE.findall(a)) in {"translate": (1, 2), "scale": (1, 2), "rotate": (1, 3)}[f] for f, a in TRANSFORM_ONE.findall(v))
            ok = ok and _nums(v) is not None
        elif k in ENUMS:
            ok = v in ENUMS[k]
        elif k.endswith("opacity") or k == "opacity":
            ok = re.fullmatch(NUM, v) and 0 <= float(v) <= 1
        else:  # stroke-width
            ok = re.fullmatch(NUM, v) and 0 <= float(v) <= MAX_NUM
        if not ok:
            raise ValueError(f"bad {k}")
    else:
        raise ValueError(f"attribute not allowed: {k}")


def sanitize_svg(data):
    """Bytes of an SVG -> [{tag, a, p}]: node 0 is the root svg (viewBox = four numbers, at least 1 wide and high), p is the
    parent's index (-1 for the root).
    Raises ValueError with the reason. The result is the only thing the page ever draws from."""
    import xml.etree.ElementTree as ET
    if len(data) > MAX_BYTES:
        raise ValueError("over 16 KB")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("not UTF-8")
    low = text.lower()
    if "<!doctype" in low or "<!entity" in low or "<?" in text:
        raise ValueError("DOCTYPE, ENTITY or <? not allowed")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError(f"not valid SVG: {e}")
    nodes = []

    def walk(e, parent, depth, scale):
        if depth > MAX_DEPTH:
            raise ValueError("nested deeper than 8")
        if len(nodes) >= MAX_ELEMENTS:
            raise ValueError("more than 200 elements")
        if not isinstance(e.tag, str):
            raise ValueError("unexpected node")
        tag = e.tag[len(SVG_NS):] if e.tag.startswith(SVG_NS) else e.tag
        if tag not in GEOMETRY or "{" in tag or (tag == "svg") != (parent == -1):
            raise ValueError(f"element not allowed: {tag}")
        if (e.text or "").strip() or (e.tail or "").strip():
            raise ValueError("text not allowed")
        for k, v in e.attrib.items():
            _attr(tag, k, v)
        if "transform" in e.attrib:   # (a transform is checked before this, so _scale only sees numeric scale() calls)
            scale *= _scale(e.attrib["transform"])
            if scale > MAX_SCALE:
                raise ValueError("scales multiply to more than 10")
        a = dict(e.attrib)
        if tag == "svg":              # the page gets four numbers, not a string to split
            vb = [float(x) for x in NUM_RE.findall(a.get("viewBox", "0 0 100 100"))]
            a["viewBox"] = [int(x) if x == int(x) else x for x in vb]
        nodes.append({"tag": tag, "a": a, "p": parent})
        me = len(nodes) - 1
        for c in e:
            walk(c, me, depth + 1, scale)

    walk(root, -1, 1, 1.0)
    return nodes


# ---- stage programs: a plugin's `run`, in a bwrap sandbox, never a shell ----
OUT_CAP, ERR_CAP, TIME_DEFAULT, TIME_MAX, TMP_SIZE = 64 * 1024, 8 * 1024, 3, 8, 64 * 1024 * 1024
CHANGED = "Changed \u2014 check it again"


class StageError(Exception):
    """A stage run that gave nothing: the message is what to tell the user."""


class Busy(StageError):
    pass


_bwrap = [None]


def bwrap_ok():
    """True if bwrap exists and a throwaway sandbox starts (one test run, remembered)."""
    if _bwrap[0] is None:
        exe = shutil.which("bwrap")
        try:
            _bwrap[0] = bool(exe) and subprocess.run([exe, "--unshare-all", "--die-with-parent", "--new-session", "--ro-bind", "/", "/", "--dev", "/dev",
                                                      "--proc", "/proc", "true"], capture_output=True, timeout=5).returncode == 0
        except (OSError, subprocess.SubprocessError):
            _bwrap[0] = False
    return _bwrap[0]


def sandbox_argv(d, stage):
    """The bwrap command line for a plugin folder d and its manifest's stage block (argv list; the program is /plugin/<argv>)."""
    py = os.path.dirname(os.path.realpath(sys.executable))        # the interpreter Nixi runs on lives in the store: scripts may use it
    path = ":".join(["/plugin", *([os.environ["PATH"]] if os.environ.get("PATH") else []), *([py] if py.startswith("/nix/store/") else [])])
    a = ["bwrap", "--clearenv", "--unshare-all", *(["--share-net"] if stage.get("network") else []), "--die-with-parent", "--new-session",
         "--ro-bind", "/nix/store", "/nix/store", "--ro-bind", str(d), "/plugin", "--chdir", "/plugin", "--size", str(TMP_SIZE), "--tmpfs", "/tmp", "--proc", "/proc", "--dev", "/dev"]
    ro = (["/usr/bin/env"] +                                       # (so `#!/usr/bin/env python3` finds PATH inside)
          (["/etc/resolv.conf", "/etc/ssl", "/etc/static/ssl"] if stage.get("network") else []))   # (system-status is passed in on stdin, never bound)
    for x in ro:
        if os.path.exists(x):
            a += ["--ro-bind", x, x]
    a += ["--setenv", "PATH", path, "--setenv", "LANG", os.environ.get("LANG") or "C.UTF-8", "--setenv", "HOME", "/tmp"]
    return a + ["/plugin/" + stage["argv"][0], *stage["argv"][1:]]


def _drain(f, cap, box, fatal=True):
    while True:
        try:
            b = os.read(f.fileno(), 65536)
        except OSError:
            return                                                 # (closed under us after the run ended)
        if not b:
            return
        if len(box[0]) + len(b) > cap:
            box[1] = True                                          # over the cap: stdout refuses and kills the run; stderr keeps reading, keeping nothing
            if fatal:
                return
            continue
        box[0] += b


_cache, _cache_lock, _running, _now = {}, threading.Lock(), set(), time.monotonic


def _ago(s):
    return f"{int(s)} s ago" if s < 90 else f"{int(s // 60)} min ago"


def forget():
    """Drop every remembered result (a plugin was switched off, changed or reloaded)."""
    with _cache_lock:
        _cache.clear()


def system_status():
    """What a plugin with reads: [system-status] gets on stdin, collected here, outside its sandbox: the running generation
    (null if unknown) and the failed user units (null if the query failed: never an empty list on failure)."""
    try:
        gen = os.path.basename(os.readlink("/run/current-system")) or None
    except OSError:
        gen = None
    try:
        r = subprocess.run(["systemctl", "--user", "--failed", "--plain", "--no-legend"], capture_output=True, text=True, timeout=2)
        failed = [ln.split()[0][:80] for ln in r.stdout.splitlines() if ln.strip()][:20] if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        failed = None
    return {"generation": gen, "failed": failed}


def _consented(p):
    """A folder plugin runs only if its files are still the ones the user allowed; otherwise it is switched off here and now."""
    if p.source != "folder":
        return
    st = State()
    rec = st.get(p.id)
    try:
        h = sha256_of(p.dir)
    except (OSError, ValueError):
        h = None
    if not rec["enabled"]:
        raise StageError("that plugin is off")
    if not h or h != rec["sha256"]:
        st.set(p.id, False, rec["sha256"])
        forget()
        raise StageError(CHANGED)


def run_stage(p, query, locale="en", timeout=TIME_DEFAULT):
    """Run a stage plugin on a query -> a `facts` stage (stages.validate'd, nothing else accepted). Raises StageError / Busy.
    Cached per plugin and query for stage.cache_seconds; if a run fails the last good result is shown with its age."""
    import stages
    stg, key, now = p.manifest["stage"], (p.id, norm(query)), _now()
    _consented(p)                                                  # (before the cache too: a changed plugin shows nothing, old or new)
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < stg.get("cache_seconds", 60):
            return hit[1]
        if p.id in _running:
            raise Busy("still fetching\u2026")
        _running.add(p.id)
    try:
        try:
            out = _launch(p, query, locale, min(timeout, TIME_MAX), stages)
        except StageError as e:
            if hit:
                old = dict(hit[1])
                old["source"] = ((old.get("source") + " \u00b7 ") if old.get("source") else "")[:60] + "couldn't refresh, " + _ago(now - hit[0])
                return old
            raise e
        with _cache_lock:
            _cache[key] = (_now(), out)
        return out
    finally:
        with _cache_lock:
            _running.discard(p.id)


def _limits():
    """In the child, before bwrap starts: 1 GiB of memory, files of at most 64 MiB."""
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))
    resource.setrlimit(resource.RLIMIT_FSIZE, (TMP_SIZE, TMP_SIZE))


def _launch(p, query, locale, timeout, stages):
    stg = p.manifest["stage"]
    if not bwrap_ok():
        raise StageError("bubblewrap isn't working here")
    try:
        feed = {"v": 1, "query": query, "locale": locale}
        if "system-status" in stg.get("reads", []):
            feed["system_status"] = system_status()
        proc = subprocess.Popen(sandbox_argv(p.dir, stg), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True, bufsize=0, preexec_fn=_limits)
    except OSError as e:
        raise StageError(f"couldn't start it: {e.strerror}")
    out, err = [b"", False], [b"", False]
    ts = [threading.Thread(target=_drain, args=(f, c, b, fatal), daemon=True) for f, c, b, fatal in ((proc.stdout, OUT_CAP, out, True), (proc.stderr, ERR_CAP, err, False))]
    for t in ts:
        t.start()

    def feed_it():                                                 # (a thread: a plugin that never reads stdin must not hold us past the deadline)
        try:
            proc.stdin.write(json.dumps(feed).encode())
            proc.stdin.close()
        except (OSError, ValueError):
            pass
    threading.Thread(target=feed_it, daemon=True).start()

    def kill():
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.kill()
    try:
        end = time.monotonic() + timeout
        while proc.poll() is None and time.monotonic() < end and not out[1]:
            time.sleep(0.02)
        late = proc.poll() is None
        if late or out[1]:
            kill()
        for t in ts:
            t.join(1)
        proc.wait(2)
    finally:
        kill()
        for f in (proc.stdout, proc.stderr):
            f.close()
    if out[1]:
        raise StageError("it said too much")
    if late:
        raise StageError("it took too long")
    if err[0]:
        sys.stderr.write("plugin %s: %s\n" % (p.id, stages._CTRL.sub(" ", err[0].decode("utf-8", "replace")[:ERR_CAP])))
    if proc.returncode != 0:
        raise StageError("it failed")
    try:
        got = stages.validate(json.loads(out[0].decode("utf-8")))
    except (ValueError, RecursionError):
        got = None
    if not got or got["kind"] != "facts":
        raise StageError("it gave something Nixi can't show")
    return got


def review(found, st):
    """Hash check of the stage plugins found. A folder one whose files differ from what was allowed is turned off
    (CHANGED); a Nix one is re-recorded ("Updated"). -> {id: note}. Writes st."""
    notes = {}
    for p in found:
        rec = st.get(p.id)
        if p.error and rec["enabled"] and rec["sha256"]:           # a stage plugin that no longer loads (broken, duplicate): off
            st.set(p.id, False, rec["sha256"])
            notes[p.id] = CHANGED
            continue
        if p.error or "stage" not in (p.manifest or {}) or not (rec["enabled"] or (p.source == "folder" and rec["sha256"])):
            continue
        try:
            h = sha256_of(p.dir)
        except (OSError, ValueError):
            h = None
        if h and h == rec["sha256"]:
            continue
        if p.source == "nix":
            if h:
                st.set(p.id, True, h)
                if rec["sha256"]:
                    notes[p.id] = "Updated"
            continue
        if rec["enabled"]:
            st.set(p.id, False, rec["sha256"])
        notes[p.id] = CHANGED
    here = {p.id for p in found}
    for pid, rec in list(st.data.items()):                         # one that vanished (deleted, or its folder became a symlink): off
        if pid not in here and isinstance(rec, dict) and rec.get("enabled") and rec.get("sha256"):
            st.set(pid, False, rec["sha256"])
            notes[pid] = CHANGED
    return notes


def check_dir(d):
    """Build-time check (`plugins.py --check <dir>`): the reason a plugin folder is bad, or None."""
    d = Path(d)
    try:
        m = json.loads((d / "plugin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return f"plugin.json unreadable: {e}"
    try:
        err = f"contains a symlink: {_symlink(d)}" if _symlink(d) else _check(m, d)
    except OSError as e:
        err = f"couldn't read it: {e}"
    if not err and "prop" in m:
        try:
            sanitize_svg((d / m["prop"]["file"]).read_bytes())
        except (OSError, ValueError) as e:
            err = f"prop: {e}"
    return err


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3 or sys.argv[1] != "--check":
        sys.exit("usage: plugins.py --check <plugin folder>")
    bad = check_dir(sys.argv[2])
    if bad:
        sys.exit(f"{sys.argv[2]}: {bad}")
    print("ok")
