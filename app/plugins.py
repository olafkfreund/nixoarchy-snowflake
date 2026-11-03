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
    """True if base/rel is a regular file (not a symlink) that really lives inside base (no `..`)."""
    if not isinstance(rel, str) or not rel or os.path.isabs(rel):
        return False
    q = os.path.join(base, rel)
    p = os.path.realpath(q)
    return not os.path.islink(q) and os.path.isfile(p) and os.path.commonpath([os.path.realpath(base), p]) == os.path.realpath(base)


def _symlink(d):
    """The first symlink anywhere inside the folder (a plugin may not contain any), or None."""
    for dirpath, dirs, files in os.walk(d):
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
    for k in ("name", "version", "description"):
        if k in m and not (isinstance(m[k], str) and m[k]):
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
        if "hint" in s and not isinstance(s["hint"], str):
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
        # TODO(slice B): argv[1:] must be checked for paths outside the folder before run_stage launches anything
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
            out.append(Plugin(vid or d.name, d, m if isinstance(m, dict) else None, "nix" if i == 0 else "folder", err))
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


def check_dir(d):
    """Build-time check (`plugins.py --check <dir>`): the reason a plugin folder is bad, or None."""
    d = Path(d)
    try:
        m = json.loads((d / "plugin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return f"plugin.json unreadable: {e}"
    err = _check(m, d)
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
