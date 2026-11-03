"""Companion plugins (#149): find them, check their manifests, remember which are on. Standard library only."""
import hashlib
import json
import os
import re
import tempfile
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


def plugin_dirs():
    """The package's plugin folder (store or git checkout, both next to app/), then the user's."""
    return [APP_DIR.parent / "plugins", DATA_DIR / "plugins"]


def _inside(base, rel):
    """True if base/rel is an existing file that really lives inside base (no `..`, no symlink out)."""
    if not isinstance(rel, str) or not rel or os.path.isabs(rel):
        return False
    p = os.path.realpath(os.path.join(base, rel))
    return os.path.isfile(p) and os.path.commonpath([os.path.realpath(base), p]) == os.path.realpath(base)


def _strs(v, n=None):
    return isinstance(v, list) and bool(v) and all(isinstance(x, str) and x for x in v) and (n is None or len(v) <= n)


def _check(m, d):
    """Return the reason the manifest is bad, or None."""
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
    if not isinstance(m["id"], str) or not ID_RE.match(m["id"]):
        return "bad id"
    for k in ("name", "version", "description"):
        if k in m and not (isinstance(m[k], str) and m[k]):
            return f"bad {k}"
    if "quips" in m and not _inside(d, m["quips"]):
        return "quips file missing or outside the folder"
    if "prop" in m:
        p = m["prop"]
        if not isinstance(p, dict) or p.keys() - PROP_KEYS or not {"file", "anchor"} <= p.keys():
            return "bad prop"
        if p["anchor"] not in ("head", "left", "right", "base") or p.get("layer", "front") not in ("front", "back"):
            return "bad prop anchor or layer"
        if not _inside(d, p["file"]):
            return "prop file missing or outside the folder"
    if "notifications" in m:
        if not isinstance(m["notifications"], list):
            return "bad notifications"
        for n in m["notifications"]:
            if not isinstance(n, dict) or n.keys() not in ({"app", "category"}, {"host", "category"}):
                return "bad notifications entry"
            if n["category"] not in CATEGORIES:
                return "bad notification category"
            if "app" in n and not (isinstance(n["app"], str) and APP_RE.match(n["app"])):
                return "notification app must be a literal lowercase id"
            if "host" in n and not (isinstance(n["host"], str) and HOST_RE.match(n["host"])):
                return "notification host must be a name or *.suffix"
    if "stage" in m:
        s = m["stage"]
        if not isinstance(s, dict) or s.keys() - STAGE_KEYS or not {"phrases", "argv"} <= s.keys():
            return "bad stage"
        if not _strs(s["phrases"]) or not _strs(s["argv"]):
            return "bad stage phrases or argv"
        if "hint" in s and not isinstance(s["hint"], str):
            return "bad stage hint"
        if "network" in s and not isinstance(s["network"], bool):
            return "bad stage network"
        c = s.get("cache_seconds", 60)
        if type(c) is not int or not 0 <= c <= 600:
            return "bad stage cache_seconds"
        if "reads" in s and not (isinstance(s["reads"], list) and set(s["reads"]) <= {"system-status"}):
            return "bad stage reads"
        if not _inside(d, s["argv"][0]):
            return "stage argv[0] missing or outside the folder"
    return None


def scan(dirs):
    """Every plugin folder under dirs (the first dir counts as Nix, the rest as Folder). Never raises per plugin."""
    out = []
    for i, base in enumerate(dirs):
        try:
            subs = sorted(p for p in Path(base).iterdir() if p.is_dir() and p.name != "examples")
        except OSError:
            continue
        for d in subs:
            m, err = None, None
            try:
                m = json.loads((d / "plugin.json").read_text(encoding="utf-8"))
                err = _check(m, d)
            except FileNotFoundError:
                err = "plugin.json missing"
            except (OSError, ValueError) as e:  # ValueError covers bad JSON and bad UTF-8
                err = f"plugin.json unreadable: {e}"
            pid = m["id"] if err in (None, "needs a newer Nixi") and isinstance(m, dict) and isinstance(m.get("id"), str) else d.name
            out.append(Plugin(pid, d, m if isinstance(m, dict) else None, "nix" if i == 0 else "folder", err))
    seen = {}
    for p in out:
        seen.setdefault(p.id, []).append(p)
    return [p._replace(error=p.error or "duplicate id") if len(seen[p.id]) > 1 else p for p in out]


def sha256_of(d):
    """Hash of every file's relative path and content, sorted. Symlinks that point outside the folder are ignored."""
    root, h = os.path.realpath(d), hashlib.sha256()
    found = []
    for dirpath, _, files in os.walk(root):
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
NUM = r"-?(?:\d+\.?\d*|\.\d+)"
NUM_RE = re.compile(NUM)
COLOR_RE = re.compile(r"^(none|acc|text|dim|#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6})$")
TRANSFORM_RE = re.compile(r"^\s*(?:(translate|scale|rotate)\(\s*(" + NUM + r"(?:\s*[, ]\s*" + NUM + r"){0,2})\s*\)\s*)+$")
TRANSFORM_ONE = re.compile(r"(translate|scale|rotate)\(\s*([^)]*)\)")
SVG_NS = "{http://www.w3.org/2000/svg}"
GEOMETRY = {"svg": {"viewBox"}, "g": set(), "path": {"d"}, "circle": {"cx", "cy", "r"}, "ellipse": {"cx", "cy", "rx", "ry"},
            "rect": {"x", "y", "width", "height", "rx", "ry"}, "line": {"x1", "y1", "x2", "y2"}, "polyline": {"points"}, "polygon": {"points"}}
STYLE = {"fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "fill-opacity", "stroke-opacity", "opacity", "fill-rule", "transform"}
ENUMS = {"stroke-linecap": {"butt", "round", "square"}, "stroke-linejoin": {"miter", "round", "bevel"}, "fill-rule": {"nonzero", "evenodd"}}
MAX_BYTES, MAX_ELEMENTS, MAX_DEPTH, MAX_D, MAX_NUM = 16 * 1024, 200, 8, 4000, 1000


def _nums(s):
    ns = [float(x) for x in NUM_RE.findall(s)]
    if any(abs(n) > MAX_NUM for n in ns):
        raise ValueError("a number is outside ±1000")
    return ns


def _attr(tag, k, v):
    if k in GEOMETRY[tag]:
        if tag == "path":
            if len(v) > MAX_D or not re.fullmatch(r"[MmLlHhVvCcSsQqTtAaZz0-9.,\s-]*", v):
                raise ValueError("bad path data")
            _nums(v)
        elif k in ("points", "viewBox"):
            if len(v) > MAX_D or not re.fullmatch(r"[0-9.,\s-]*", v):
                raise ValueError(f"bad {k}")
            ns = _nums(v)
            if k == "viewBox" and (len(ns) != 4 or ns[2] <= 0 or ns[3] <= 0):
                raise ValueError("bad viewBox")
        elif not re.fullmatch(NUM, v) or abs(float(v)) > MAX_NUM:
            raise ValueError(f"bad number in {k}")
    elif k in STYLE and tag != "svg":
        if k in ("fill", "stroke"):
            ok = COLOR_RE.match(v)
        elif k == "transform":
            ok = TRANSFORM_RE.match(v) and all(
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
    """Bytes of an SVG -> [{tag, a, p}]: node 0 is the root svg (its viewBox), p is the parent's index (-1 for the root).
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

    def walk(e, parent, depth):
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
        nodes.append({"tag": tag, "a": dict(e.attrib), "p": parent})
        me = len(nodes) - 1
        for c in e:
            walk(c, me, depth + 1)

    walk(root, -1, 1)
    return nodes
