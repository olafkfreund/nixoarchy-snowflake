"""The user's terminal font size in CSS px, read from the terminal's own main config (#109). Stdlib only."""
import math
import os
try:
    import tomllib
except ImportError:   # Python < 3.11 (a distro's /usr/bin/python3): Alacritty falls back to 16 px
    tomllib = None
from pathlib import Path

_IDS = {"kitty": "kitty", "alacritty": "alacritty", "com.mitchellh.ghostty": "ghostty", "ghostty": "ghostty",
        "foot": "foot", "footclient": "foot"}


def _terminal(env, config_home):
    t = os.path.basename(env.get("TERMINAL") or "")
    if t and t != "xdg-terminal-exec":
        return _IDS.get(t.removesuffix("client") if t.endswith("client") else t)
    names = [d.lower() for d in (env.get("XDG_CURRENT_DESKTOP") or "").split(":") if d]
    for f in [f"{d}-xdg-terminals.list" for d in names] + ["xdg-terminals.list"]:
        try:
            lines = (config_home / f).read_text().splitlines()
        except OSError:
            continue
        for ln in lines:
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                return _IDS.get(ln.split(":")[0].removesuffix(".desktop").lower())
    return None


def _last(path, key, sep):
    """Last `key<sep>value` line of a flat config, as text."""
    val = None
    for ln in path.read_text().splitlines():
        ln = ln.strip()
        if sep:
            k, s, v = ln.partition(sep)
        else:
            k, _, v = ln.replace("\t", " ").partition(" ")   # kitty: any whitespace between key and value
            s = v.strip()
        if s and not ln.startswith("#") and k.strip() == key:
            val = v.strip()
    return float(val) if val else None


def _foot(path):
    font, section = None, "main"
    for ln in path.read_text().splitlines():
        ln = ln.strip()
        if ln.startswith("["):
            section = ln.strip("[]")
        elif section == "main" and not ln.startswith("#"):
            k, s, v = ln.partition("=")
            if s and k.strip() == "font":
                font = v
    if font is None:
        return None
    pt = px = None
    for f in font.split(",")[0].split(":")[1:]:
        k, _, v = f.partition("=")
        if k.strip() == "size":
            pt, px = float(v), None
        elif k.strip() == "pixelsize":
            px, pt = float(v), None
    return px if px is not None else pt * 96 / 72 if pt is not None else None


def term_px(env, config_home):
    """Font size in px of the terminal chosen by `env`, or None when unknown, unreadable or implausible."""
    config_home = Path(config_home)
    try:
        t = _terminal(env, config_home)
        if t == "kitty":
            pt = _last(config_home / "kitty/kitty.conf", "font_size", None)
        elif t == "ghostty":
            pt = _last(config_home / "ghostty/config", "font-size", "=")
        elif t == "alacritty" and tomllib:
            size = tomllib.loads((config_home / "alacritty/alacritty.toml").read_text())["font"]["size"]
            pt = None if isinstance(size, bool) else float(size)
        elif t == "foot":
            px = _foot(config_home / "foot/foot.ini")
            return px if px is not None and math.isfinite(px) and 5 <= px <= 96 else None
        else:
            return None
        px = pt * 96 / 72 if pt is not None else None
    except (OSError, ValueError, KeyError, TypeError):   # (TOMLDecodeError is a ValueError)
        return None
    return px if px is not None and math.isfinite(px) and 5 <= px <= 96 else None
