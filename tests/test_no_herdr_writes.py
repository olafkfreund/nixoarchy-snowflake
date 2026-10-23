"""The companion never writes to a herdr session itself (#95): every send is nixi's agent's call, behind the bridge's card.
Fails on a herdr write verb anywhere in app/ or bin/ except in comments and in session_send's prompt to nixi's agent."""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRITE = re.compile(r"agent\s+prompt|send-keys|send-text|pane\s+send")


def _allowed_span():
    tree = ast.parse((ROOT / "app" / "server.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "session_send")
    return fn.lineno, fn.end_lineno


class NoHerdrWritesTest(unittest.TestCase):
    def test_no_write_verbs_outside_the_one_prompt(self):
        lo, hi = _allowed_span()
        hits = []
        for base in ("app", "bin"):
            for f in sorted((ROOT / base).rglob("*")):
                if not f.is_file() or f.suffix in (".png", ".svg", ".ogg", ".wav", ".woff2", ".onnx", ".pyc"):
                    continue
                try:
                    lines = f.read_text(encoding="utf-8").splitlines()
                except (UnicodeDecodeError, OSError):
                    continue
                for n, line in enumerate(lines, 1):
                    if not WRITE.search(line) or line.lstrip().startswith(("#", "//")):
                        continue
                    if f == ROOT / "app" / "server.py" and lo <= n <= hi:
                        continue
                    hits.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()[:100]}")
        self.assertEqual(hits, [], "the companion must not write to herdr sessions")

    def test_the_scan_sees_the_allowed_prompt(self):   # guards against the scan silently matching nothing
        lo, hi = _allowed_span()
        text = "\n".join((ROOT / "app" / "server.py").read_text(encoding="utf-8").splitlines()[lo - 1:hi])
        self.assertRegex(text, WRITE)


if __name__ == "__main__":
    unittest.main()
