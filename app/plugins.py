"""Companion plugins (#149): find them, check their manifests, remember which are on. Standard library only."""
import hashlib
import json
import os
import resource
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "nixi-companion"
peers_allowed = lambda: False

Plugin = namedtuple("Plugin", "id dir manifest source error")

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
REQUIRED = {"api", "id", "name", "version"}
OPTIONAL = {"description", "quips", "prop", "notifications", "stage", "character"}
PROP_KEYS = {"file", "anchor", "layer"}
CHARACTER_KEYS = {"label", "template", "fill", "back", "front", "fits", "private"}
ROUND_FITS = {"none", "halo", "crown", "sprout", "bow", "nightcap", "beanie", "party", "scarf", "tie",
              "headphones", "shades", "glasses", "chat", "feed", "plug"}
PRIVATE_ART_ERROR = "the character art was refused"
PRIVATE_MODE_ERROR = "the folder is readable by other users: run chmod -R go= <folder>"
PRIVATE_STORE_ERROR = "a private character can't come from the Nix store"
STAGE_KEYS = {"phrases", "hint", "argv", "network", "cache_seconds", "reads", "config", "videos"}
CATEGORIES = {"mail", "chat", "feed"}
APP_RE = re.compile(r"^[a-z0-9._-]+$")
HOST_RE = re.compile(r"^(\*\.)?[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")


def norm(said):
    """What you said, the way stages.fast_path reads it."""
    import stages
    return stages.normalize(said)


def reserved(phrase):
    """True for a phrase Nixi answers itself: empty, close / go back / show it / what's next, guide / mechanic, the run/copy/play/open
    verbs, and anything the quick matcher handles."""
    import quick
    import stages
    t = norm(phrase)
    if not t or t in ("close", "go back", "show it", "what s next", "what is next", "guide", "mechanic") or any(stages.fast_path(t, stage, lang) is not None for lang in ("en", "nb", "pl") for stage in ({"items": [0] * 5}, {"kind": "headlines", "items": [0] * 5, "clips": [0] * 5})):
        return True
    try:
        return quick.matches(phrase)
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


_FORMAT = re.compile("[\u2028\u2029\u200b-\u200f\u202a-\u202e\u2066-\u2069]")   # (line separators and invisible direction marks: they could fake the consent card)


def _bad(s):
    """True if s holds a control character or a Unicode format / line separator."""
    import stages
    return bool(stages._CTRL.search(s) or _FORMAT.search(s))


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
        if k in m and not (isinstance(m[k], str) and 0 < len(m[k]) <= n and not _bad(m[k])):
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
    if "character" in m:
        c = m["character"]
        if not isinstance(c, dict) or not c.keys() <= CHARACTER_KEYS or not CHARACTER_KEYS - {"private"} <= c.keys():   # (private is optional)
            return "bad character"
        if not isinstance(c["label"], str) or not 0 < len(c["label"]) <= 20 or _bad(c["label"]):
            return "bad character label"
        if c["template"] != "round":
            return "bad character template"
        if not isinstance(c["fill"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", c["fill"]):
            return "bad character fill"
        if not isinstance(c["fits"], list) or any(not isinstance(f, str) or f not in ROUND_FITS for f in c["fits"]):
            return "bad character fits"
        if type(c.get("private", False)) is not bool:
            return "bad character private"
        for side in ("back", "front"):
            rel = c[side]
            if not isinstance(rel, str) or not rel.lower().endswith(".svg") or not _inside(d, rel):
                return "character art missing or outside the folder"
            try:
                sanitize_svg((Path(d) / rel).read_bytes())
            except (OSError, ValueError) as e:
                return f"character art: {e}"
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
        if len(s["argv"]) > 8 or any(len(a) > 80 or _bad(a) for a in s["argv"]):
            return "bad stage argv (at most 8 words of 80 plain characters)"
        if "hint" in s and not (isinstance(s["hint"], str) and len(s["hint"]) <= 79 and not _bad(s["hint"])):
            return "bad stage hint"
        if "network" in s and not isinstance(s["network"], bool):
            return "bad stage network"
        if "videos" in s:
            if not isinstance(s["videos"], bool):
                return "bad stage videos"
            if s["videos"] and m["id"] != "news":
                return "only the news plugin can search YouTube"
        if "config" in s:
            if not isinstance(s["config"], bool):
                return "bad stage config"
            if s["config"]:
                try:
                    if not isinstance(json.loads(_read_small(os.path.join(d, "defaults.json"))), dict):
                        raise ValueError
                except (OSError, ValueError):
                    return "stage config needs a defaults.json (a JSON object of at most 16 KiB)"
        c = s.get("cache_seconds", 60)
        if type(c) is not int or not 0 <= c <= 600:
            return "bad stage cache_seconds"
        if "reads" in s and not (isinstance(s["reads"], list) and all(_in(x, ("system-status", "peer-status")) for x in s["reads"])):
            return "bad stage reads"
        if s.get("network") is True and "peer-status" in s.get("reads", []):
            return "a plugin that reads your other machines' status can't use the network"
        if s.get("network") is True and "system-status" in s.get("reads", []):
            return "a plugin that reads your system status can't use the network"
        if not _inside(d, s["argv"][0]):
            return "stage argv[0] missing or outside the folder"
        if any(a.startswith("/") or "=/" in a or ".." in re.split(r"[/=]", a) for a in s["argv"][1:]):
            return "stage argv may not point outside the folder"
        for ph in s["phrases"]:
            if reserved(ph):
                return f"stage phrase {ph!r} clashes with one of Nixi's own"
    return None


def _read_small(p, cap=16 * 1024):
    """A plain file of at most cap bytes, opened without following a link or blocking on a FIFO."""
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > cap:
            raise ValueError("not a plain file of at most 16 KiB")
        return os.read(fd, cap + 1).decode("utf-8")
    finally:
        os.close(fd)


def config_path(pid):
    """A plugin's settings file. XDG_CONFIG_HOME is read now, not at import."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "nixi-companion" / "plugin-config" / (pid + ".json")


def read_user_config(pid):
    """-> (the user's settings dict or None, note). Only the user's file is opened."""
    try:
        c = json.loads(_read_small(config_path(pid)))
        if isinstance(c, dict):
            return c, None
        return None, "settings file unreadable"
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError):
        return None, "settings file unreadable"


def read_config(pid, snap_dir, user=None):
    """-> (settings, note): the snapshot's defaults (the hashed bytes) with a good user file over them. user: a read_user_config result already in hand."""
    c, note = user or read_user_config(pid)
    d = json.loads(_read_small(os.path.join(snap_dir, "defaults.json")))
    return ({**d, **c} if c is not None else d), note


def edit_config(pid, d):
    """Create the settings file from the plugin's defaults.json if it is missing (never through a link); -> its path."""
    p, text = config_path(pid), _read_small(os.path.join(d, "defaults.json"))   # (read first: a failed read leaves no empty file)
    os.makedirs(p.parent, mode=0o700, exist_ok=True)
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        if not stat.S_ISREG(os.lstat(p).st_mode):          # (a planted link or special file: never hand it to xdg-open)
            raise
        return p
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return p


def _manifest(p):
    """plugin.json's text, opened like _snap opens files: never blocks on a FIFO, never follows a link, a plain file of at most 64 KiB."""
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > 64 * 1024:
            raise ValueError("not a plain file of at most 64 KiB")
        return os.read(fd, 64 * 1024 + 1).decode("utf-8")
    finally:
        os.close(fd)


def _private_permissions(d):
    """Private plugins require user-owned, user-only folders and files; stat failures refuse them."""
    try:
        owner = os.getuid()
        root_stat = os.lstat(d)
        if root_stat.st_uid != owner or root_stat.st_mode & 0o077:
            return False
        for root, dirs, files in os.walk(d, onerror=_raise):
            for p in (os.path.join(root, n) for n in dirs + files):
                st = os.lstat(p)
                if st.st_uid != owner or st.st_mode & 0o077:
                    return False
        return True
    except OSError:
        return False


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
                link = _symlink(d)
                err = (f"contains a symlink: {link}" if i == 0 else "contains a symlink") if link else None
                if link:   # (read anyway: a private one's error must not name its files)
                    try:
                        m = json.loads(_manifest(d / "plugin.json"))
                    except (OSError, ValueError):
                        pass  # the generic folder error remains free of paths and parser details
                if not err:
                    m = json.loads(_manifest(d / "plugin.json"))
                    private = isinstance(m, dict) and isinstance(m.get("character"), dict) and m["character"].get("private") is True
                    if private and i == 0:
                        err = PRIVATE_STORE_ERROR
                    elif private and not _private_permissions(d):
                        err = PRIVATE_MODE_ERROR
                    else:
                        err = _check(m, d)
            except FileNotFoundError:
                err = "plugin.json missing" if i == 0 else "plugin.json unreadable"
            except (OSError, ValueError) as e:  # ValueError covers bad JSON and bad UTF-8
                err = f"plugin.json unreadable: {e}" if i == 0 else "plugin.json unreadable"
            except Exception as e:  # one odd manifest must never stop the scan
                err = f"plugin.json not understood: {type(e).__name__}" if i == 0 else "plugin.json unreadable"
            if isinstance(m, dict) and isinstance(m.get("character"), dict) and m["character"].get("private") is True and err not in (None, PRIVATE_STORE_ERROR, PRIVATE_MODE_ERROR):
                err = PRIVATE_STORE_ERROR if i == 0 else PRIVATE_ART_ERROR
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
    return [p._replace(error=p.error or "duplicate id") if id(p) in dup else p for p in out]   # (a fixed string: it names nothing)


SNAP_MAX = 64 * 1024 * 1024                          # a plugin folder bigger than this is refused (hashing never holds it in memory)


def _snap(d, dest=None):
    """Hash of every file's relative path and content, sorted. With dest, the same bytes that were hashed are written there (a copy
    for the sandbox to mount: what runs is what was hashed). One file at a time, in chunks, so a big folder never sits in memory.
    Raises ValueError for a symlink or a special file anywhere inside, a file that changes while it is read, or a folder over SNAP_MAX."""
    if _symlink(d):
        raise ValueError(f"contains a symlink: {_symlink(d)}")
    root, h, total, paths = os.path.realpath(d), hashlib.sha256(), 0, []
    store = _in_store(root)                          # (the store is read-only; nix-store --optimise hard-links identical files there)
    for dirpath, dirs, files in os.walk(root, onerror=_raise):
        for n in dirs:
            if dest:
                os.makedirs(os.path.join(dest, os.path.relpath(os.path.join(dirpath, n), root)), mode=0o700, exist_ok=True)
        paths += [os.path.join(dirpath, f) for f in files]
    for p in sorted(paths, key=lambda q: os.path.relpath(q, root).encode()):
        rel = os.path.relpath(p, root).encode()
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)   # (never follows a link swapped in since the walk)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise ValueError(f"not a plain file: {rel.decode(errors='replace')}")
            if st.st_nlink > 1 and not store:        # (in a folder plugin a hardlink may point at a file outside it)
                raise ValueError(f"hard link: {rel.decode(errors='replace')}")
            total += st.st_size
            if total > SNAP_MAX:
                raise ValueError("the plugin folder is too big")
            h.update(b"%d:%s%d:" % (len(rel), rel, st.st_size))
            out, left = None, st.st_size
            if dest:
                q = os.path.join(dest, os.fsdecode(rel))
                os.makedirs(os.path.dirname(q), mode=0o700, exist_ok=True)
                out = open(q, "wb")
            try:
                while left:
                    chunk = os.read(fd, min(left, 1 << 20))
                    if not chunk:
                        break
                    h.update(chunk)
                    if out:
                        out.write(chunk)
                    left -= len(chunk)
                if left or os.read(fd, 1):           # (shorter or longer than when we looked: it changed under us)
                    raise ValueError(f"changed while being read: {rel.decode(errors='replace')}")
            finally:
                if out:
                    out.close()
                    os.chmod(q, 0o500 if st.st_mode & 0o111 else 0o400)
        finally:
            os.close(fd)
    return h.hexdigest()


def sha256_of(d):
    return _snap(d)


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


DNS_ADDR, SHM_SIZE, NPROC = "192.0.2.53", 16 * 1024 * 1024, 64
PASTA_EXTRA = []                                                   # (tests only: extra pasta flags; empty in production)
LAUNCHER = ("import os, resource, sys\nresource.setrlimit(resource.RLIMIT_NPROC, (%d, %d))\nresource.setrlimit(resource.RLIMIT_CORE, (0, 0))\n"
            "os.execv(sys.argv[1], sys.argv[1:])") % (NPROC, NPROC)  # (runs inside the sandbox's user namespace: only the plugin's own processes count)
# Runs inside pasta's namespace (full capabilities there; the plugin gets none): every address this computer owns becomes unreachable,
# so pasta cannot forward to this computer's own services; then bwrap takes over. A route that cannot be added stops the run.
ROUTER = ("import os, subprocess, sys\ni = sys.argv.index('--')\nfor a in sys.argv[1:i]:\n"
          "    v6 = ':' in a\n    r = subprocess.run(['ip', '-6' if v6 else '-4', 'route', 'replace', 'unreachable', a if '/' in a else a + ('/128' if v6 else '/32')],"
          " capture_output=True)\n    if r.returncode:\n        sys.exit('route: ' + r.stderr.decode(errors='replace'))\nos.execvp(sys.argv[i + 1], sys.argv[i + 1:])")
_pasta = [None]


# Tailscale's own resolver and web page live inside tailscaled on this computer but aren't one of its addresses
HOST_EXTRA = ["100.100.100.100", "fd7a:115c:a1e0::53"]


def _host_addrs():
    """Everything this computer delivers to itself (the kernel's local tables, so ranges and scope-host addresses too), except loopback,
    plus HOST_EXTRA. Read before each run: an address that appears mid-run is open for at most that run (capped at TIME_MAX)."""
    import ipaddress
    found = set(HOST_EXTRA)
    try:
        for fam in ("-4", "-6"):
            r = subprocess.run(["ip", fam, "-j", "route", "show", "table", "local", "type", "local"], capture_output=True, timeout=5, check=True)
            for e in json.loads(r.stdout or b"[]"):
                dst = e["dst"]
                net = ipaddress.ip_network(dst if "/" in dst else dst + ("/128" if ":" in dst else "/32"), strict=False)
                if not net.is_loopback:
                    found.add(str(net) if net.num_addresses > 1 else str(net.network_address))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        raise StageError("can't tell which addresses this computer has, so a plugin that uses the internet can't run safely")
    return sorted(found)


def pasta_ok():
    """True if pasta exists and starts a throwaway network namespace (one test run, remembered)."""
    if _pasta[0] is None:
        exe = shutil.which("pasta")
        try:
            _pasta[0] = bool(exe) and subprocess.run([exe, "--quiet", "--foreground", "--", "true"], capture_output=True, timeout=5).returncode == 0
        except (OSError, subprocess.SubprocessError):
            _pasta[0] = False
    return _pasta[0]


def sandbox_argv(d, stage, resolv=None):
    """The command line for a plugin folder d (a private copy) and its manifest's stage block (argv list; the program is /plugin/<argv>).
    A network plugin runs in a network namespace of its own, joined to the internet by pasta; resolv is the resolv.conf it gets."""
    py = os.path.dirname(os.path.realpath(sys.executable))        # the interpreter Nixi runs on lives in the store: scripts may use it
    store = [x for x in os.environ.get("PATH", "").split(":") if x.startswith("/nix/store/")]   # (never the host's /home or /etc/profiles entries)
    path = ":".join(["/plugin", *store, *([py] if py.startswith("/nix/store/") else [])])
    net = bool(stage.get("network"))
    a = ["bwrap", "--clearenv", "--unshare-all", "--unshare-user", "--disable-userns", "--cap-drop", "ALL", *(["--share-net"] if net else []), "--die-with-parent", "--new-session",
         "--ro-bind", "/nix/store", "/nix/store", "--ro-bind", str(d), "/plugin", "--chdir", "/plugin", "--size", str(TMP_SIZE), "--tmpfs", "/tmp",
         "--proc", "/proc", "--dev", "/dev", "--size", str(SHM_SIZE), "--tmpfs", "/dev/shm"]
    ro = ["/usr/bin/env"] + (["/etc/ssl", "/etc/static/ssl"] if net else [])   # (system-status is passed in on stdin, never bound)
    for x in ro:
        if os.path.exists(x):
            a += ["--ro-bind", x, x]
    if net and resolv:
        a += ["--ro-bind", str(resolv), "/etc/resolv.conf"]
    a += ["--setenv", "PATH", path, "--setenv", "LANG", os.environ.get("LANG") or "C.UTF-8", "--setenv", "HOME", "/tmp"]
    a += [os.path.realpath(sys.executable), "-I", "-c", LAUNCHER, "/plugin/" + stage["argv"][0], *stage["argv"][1:]]
    if net:      # no host loopback or gateway mapping and no port forwarding: it reaches the internet and the LAN, not localhost-only services
        a = [shutil.which("pasta") or "pasta", "--config-net", "--quiet", "--foreground", "--no-map-gw", "-t", "none", "-u", "none", "-T", "none", "-U", "none",
             "--dns-forward", DNS_ADDR, *PASTA_EXTRA, "--", os.path.realpath(sys.executable), "-I", "-c", ROUTER, *_host_addrs(), "--"] + a
    return a


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


PROC_STAT, PROC_NET, PROC_MEM, PROC_UP, PROC_HOST = "/proc/stat", "/proc/net/dev", "/proc/meminfo", "/proc/uptime", "/proc/sys/kernel/hostname"
_last = {}                      # the previous counters and computed rates
_last_lock = threading.Lock()
_generation_details = {}
_generation_lock = threading.Lock()


def _read(path):
    try:
        return Path(path).read_text()
    except OSError:
        return None


def _cpu():
    """(busy, total) jiffies from /proc/stat, or None."""
    try:
        v = [int(x) for x in _read(PROC_STAT).splitlines()[0].split()[1:9]]
        return v[0] + v[1] + v[2] + v[5] + v[6] + v[7], sum(v)
    except (AttributeError, ValueError, IndexError):
        return None


def _net():
    """(rx, tx) bytes summed over every interface but lo, or None."""
    try:
        rx = tx = 0
        for ln in _read(PROC_NET).splitlines()[2:]:
            name, _, rest = ln.partition(":")
            if name.strip() != "lo":
                f = rest.split()
                rx, tx = rx + int(f[0]), tx + int(f[8])
        return rx, tx
    except (AttributeError, ValueError, IndexError):
        return None


def prime():
    """Take a first reading of the counters (cheap: two small /proc files, no sleep) so the first system_status() has a rate."""
    with _last_lock:
        _last.update(cpu=_cpu(), net=_net(), t=time.monotonic())
        _last.pop("rates", None)


def _rates():
    """(cpu_pct, rx_bps, tx_bps) since the last reading; null for what can't be known (unreadable, or a counter that went back)."""
    with _last_lock:
        now = time.monotonic()
        if "rates" in _last and now - _last["t"] < 1:
            return _last["rates"]
        if "t" not in _last or now - _last["t"] > 30:
            _last.update(cpu=_cpu(), net=_net(), t=time.monotonic())
            time.sleep(0.25)                           # shortcut: no earlier reading, so wait a moment once
        c, n, t = _cpu(), _net(), time.monotonic()
        c0, n0, dt = _last.get("cpu"), _last.get("net"), t - _last["t"]
        _last.update(cpu=c, net=n, t=t)
        cpu = rx = tx = None
        if c and c0 and c[1] > c0[1] and c[0] >= c0[0]:
            cpu = round(100 * (c[0] - c0[0]) / (c[1] - c0[1]), 1)
        if n and n0 and dt > 0 and n[0] >= n0[0] and n[1] >= n0[1]:
            rx, tx = round((n[0] - n0[0]) / dt), round((n[1] - n0[1]) / dt)
        _last["rates"] = (cpu, rx, tx)
        return _last["rates"]


def _rev_built(target):
    if target is None:
        return None, None
    with _generation_lock:
        if target not in _generation_details:
            rev = built = None
            try:
                r = subprocess.run(["/run/current-system/sw/bin/nixos-version", "--json"],
                                   capture_output=True, text=True, timeout=1)
                if r.returncode == 0:
                    value = json.loads(r.stdout).get("configurationRevision")
                    rev = value if isinstance(value, str) and value else None
            except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
                pass
            try:
                prof = "/nix/var/nix/profiles/system"   # lstat the system-N-link it names: following on into the store gives mtime 1
                built = datetime.fromtimestamp(os.lstat(os.path.join(os.path.dirname(prof), os.readlink(prof))).st_mtime, timezone.utc).isoformat()
            except (OSError, OverflowError, ValueError):
                pass
            _generation_details[target] = rev, built
        return _generation_details[target]


def _failed(cmd, out, i):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1)
        out[i] = [ln.split()[0][:80] for ln in r.stdout.splitlines() if ln.strip()][:20] if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        out[i] = None


def system_status(user=True):
    """What a plugin with reads: [system-status] gets on stdin, collected here, outside its sandbox: the running generation,
    the failed user and system units, and the host's readings. Anything that can't be read is null, never 0 or an empty list."""
    try:
        target = os.readlink("/run/current-system")
        gen = os.path.basename(target) or None
    except OSError:
        target = gen = None
    out = [None, None]
    ts = [threading.Thread(target=_failed, args=(["systemctl", *u, "--failed", "--plain", "--no-legend"], out, i))
          for i, u in enumerate((["--user"], [])) if user or i == 1]
    for t in ts:
        t.start()
    rev, built = _rev_built(target)
    cpu, rx, tx = _rates()
    mem = None
    try:
        mi = {ln.split(":")[0]: int(ln.split()[1]) * 1024 for ln in _read(PROC_MEM).splitlines()}
        mem = {"total": mi["MemTotal"], "available": mi["MemAvailable"]}
    except (AttributeError, ValueError, IndexError, KeyError):
        pass
    disks = []
    for path in ("/", "/nix/store"):
        try:
            v = os.statvfs(path)
            disks.append({"path": path, "total": v.f_blocks * v.f_frsize, "used": (v.f_blocks - v.f_bfree) * v.f_frsize})
        except OSError:
            pass
    try:
        up = round(float(_read(PROC_UP).split()[0]))
    except (AttributeError, ValueError, IndexError):
        up = None
    host = (_read(PROC_HOST) or "").strip()[:32] or None
    for t in ts:
        t.join()
    return {"generation": gen, "rev": rev, "built": built, "failed": out[0], "failed_system": out[1], "cpu_pct": cpu, "mem": mem, "disks": disks or None,
            "net": {"rx_bps": rx, "tx_bps": tx}, "uptime_s": up, "host": host}


def _consented(p, h=None):
    """A folder plugin runs only if its files (h: the hash of the very bytes about to run) are still the ones the user allowed; otherwise it is switched off here and now."""
    if p.source != "folder":
        return
    st = State()
    rec = st.get(p.id)
    try:
        h = h or sha256_of(p.dir)
    except (OSError, ValueError):
        h = None
    if not rec["enabled"]:
        raise StageError("that plugin is off")
    if not h or h != rec["sha256"]:
        st.set(p.id, False, rec["sha256"])
        forget()
        raise StageError(CHANGED)


def run_stage(p, query, locale="en", timeout=TIME_DEFAULT, fresh=False):
    """Run a stage plugin on a query -> a `facts` stage (stages.validate'd, nothing else accepted). Raises StageError / Busy.
    Cached per plugin and query for stage.cache_seconds; if a run fails the last good result is shown with its age."""
    import stages
    stg, now = p.manifest["stage"], _now()
    key = (p.id, norm(query), "peer-status" in stg.get("reads", []) and peers_allowed(), locale)   # (a board with peers is never served once they're off)
    _consented(p)                                                  # (before the cache too: a changed plugin shows nothing, old or new)
    user = None
    if stg.get("config"):                                          # (one read of the settings: the key and the plugin's stdin both come from it)
        user = read_user_config(p.id)
        key += (hashlib.sha256(json.dumps(user[0], sort_keys=True).encode()).hexdigest(),)
    with _cache_lock:
        hit = _cache.get(key)
        if not fresh and hit and now - hit[0] < stg.get("cache_seconds", 60):
            return hit[1]
        if p.id in _running:
            raise Busy("still fetching\u2026")
        _running.add(p.id)
    try:
        try:
            out = _launch(p, query, locale, min(timeout, TIME_MAX), stages, user)
        except StageError as e:
            if not fresh and hit and str(e) != CHANGED:
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
    resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))
    resource.setrlimit(resource.RLIMIT_FSIZE, (TMP_SIZE, TMP_SIZE))


def _launch(p, query, locale, timeout, stages, user=None):
    stg = p.manifest["stage"]
    if not bwrap_ok():
        raise StageError("bubblewrap isn't working here")
    if stg.get("network") and not pasta_ok():                       # (never fall back to sharing this computer's network)
        raise StageError("plugins that use the internet need pasta (passt), and it doesn't work here")
    if p.source == "folder" and os.path.islink(p.dir):
        raise StageError(CHANGED)
    tmp = tempfile.mkdtemp(prefix="nixi-plugin-")
    try:
        return _run_copy(p, query, locale, timeout, stages, tmp, user)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_copy(p, query, locale, timeout, stages, tmp, user=None):
    stg = p.manifest["stage"]
    try:
        try:
            h = _snap(p.dir, os.path.join(tmp, "plugin"))           # (the copy is what runs, and these are the bytes that were hashed)
        except (OSError, ValueError):
            h = None
        _consented(p, h or "-")
        if not h:
            raise StageError(CHANGED)
        with open(os.path.join(tmp, "resolv.conf"), "w") as f:
            f.write(f"nameserver {DNS_ADDR}\n")
        feed = {"v": 1, "query": query, "locale": locale}
        if "system-status" in stg.get("reads", []):
            feed["system_status"] = system_status()
        if stg.get("config"):
            feed["config"] = read_config(p.id, os.path.join(tmp, "plugin"), user)[0]
        if "peer-status" in stg.get("reads", []) and peers_allowed():
            import peers
            feed["peers"] = peers.snapshot()
        proc = subprocess.Popen(sandbox_argv(os.path.join(tmp, "plugin"), stg, os.path.join(tmp, "resolv.conf")), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
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
        message = f"{len(err[0])} bytes of stderr" if stg.get("reads") else stages._CTRL.sub(" ", err[0].decode("utf-8", "replace")[:ERR_CAP])
        sys.stderr.write(f"plugin {p.id}: {message}\n")
    if proc.returncode != 0:
        raise StageError("it failed")
    try:
        got = stages.validate(json.loads(out[0].decode("utf-8")))
    except (ValueError, RecursionError):
        got = None
    if not got or got["kind"] not in ("facts", "gauges", "headlines"):
        raise StageError("it gave something Nixi can't show")
    return got


def review(found, st):
    """Hash check of the stage plugins found. A folder one whose files differ from what was allowed is turned off
    (CHANGED); a Nix one is re-recorded ("Updated"). -> {id: note}. Writes st."""
    notes = {}
    for p in found:
        rec = st.get(p.id)
        if p.error and rec["enabled"] and rec["sha256"] and not any(q.id == p.id and not q.error for q in found):   # no longer loads (broken, or a duplicate nobody won): off
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
        m = json.loads(_manifest(d / "plugin.json"))
    except (OSError, ValueError) as e:
        return f"plugin.json unreadable: {e}"
    if isinstance(m, dict) and isinstance(m.get("character"), dict) and m["character"].get("private") is True:
        return PRIVATE_STORE_ERROR
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
