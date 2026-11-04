"""Nixi's languages (#177): the table, the word/line files, t(). Everything reads `active`, which only the switcher changes."""
import json
import re
from pathlib import Path

DIR = Path(__file__).resolve().parent
LANGS = {
    "en": {"name": "English", "whisper": "en", "locale": "en", "date": "en-GB", "clause": ""},
    "nb": {"name": "Norsk", "whisper": "no", "locale": "nb", "date": "nb-NO", "clause": "Reply in Norwegian (Bokmål)."},
    "pl": {"name": "Polski", "whisper": "pl", "locale": "pl", "date": "pl-PL", "clause": "Reply in Polish."},
}
active = "en"
_cache = {}


def norm(code):
    return code if code in LANGS else "en"


def load(code):
    """The language's json (words, lines); {} if the file is missing or broken."""
    code = norm(code)
    if code not in _cache:
        try:
            d = json.loads((DIR / f"{code}.json").read_text(encoding="utf-8"))
            _cache[code] = d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            _cache[code] = {}
    return _cache[code]


def lines(code=None):
    """English lines overlaid with the language's own."""
    code = norm(code or active)
    return {**load("en").get("lines", {}), **load(code).get("lines", {})}


def t(key, **slots):
    s = lines().get(key, key)
    try:
        return s.format(**slots)
    except (KeyError, IndexError, ValueError):
        return s


def clause(code=None):
    return LANGS[norm(code or active)]["clause"]


def detect(env):
    """First-run language from LC_ALL, then LC_MESSAGES, then LANG (the first one set wins)."""
    for k in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = (env.get(k) or "").strip()
        if v:
            head = re.split(r"[.@]", v)[0].lower()
            return {"nb_no": "nb", "no_no": "nb", "nn_no": "nb", "pl_pl": "pl"}.get(head, "en")
    return "en"
