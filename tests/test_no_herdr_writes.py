"""The companion never writes to a herdr session itself (#95): every send is nixi's agent's call, behind the bridge's card.
Fails on a herdr write verb anywhere in app/ or bin/ (as text, or as an argv list next to "herdr") except in comments and
in the one prompt string session_send hands to nixi's agent."""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRITE = re.compile(r"agent\s+prompt|send-keys|send-text|pane\s+send")
VERBS = {"prompt", "send-keys", "send-text", "send", "run", "start"}      # argv words that act on a session
SERVER = ROOT / "app" / "server.py"


def _files():
    for base in ("app", "bin"):
        for f in sorted((ROOT / base).rglob("*")):
            if f.is_file() and f.suffix not in (".png", ".svg", ".ogg", ".wav", ".woff2", ".onnx", ".pyc"):
                try:
                    yield f, f.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue


def _prompt_span():
    """The one statement that builds the prompt asking nixi's agent to send: session_send's last return."""
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "session_send")
    ret = [n for n in ast.walk(fn) if isinstance(n, ast.Return) and any(isinstance(x, ast.JoinedStr) for x in ast.walk(n))]
    ret = max(ret, key=lambda n: n.lineno)
    return ret.lineno, ret.end_lineno


class NoHerdrWritesTest(unittest.TestCase):
    def test_no_write_verbs_in_text(self):
        lo, hi = _prompt_span()
        hits = []
        for f, text in _files():
            for n, line in enumerate(text.splitlines(), 1):
                if not WRITE.search(line) or line.lstrip().startswith(("#", "//")):
                    continue
                if f == SERVER and lo <= n <= hi:
                    continue
                hits.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()[:100]}")
        self.assertEqual(hits, [], "the companion must not write to herdr sessions")

    def test_no_write_verbs_in_herdr_argv_lists(self):
        hits = []
        for f, text in _files():
            if f.suffix != ".py" and "python" not in text.splitlines()[:1].__str__():
                continue
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.List, ast.Tuple)):
                    words = {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
                    if any(w == "herdr" or w.endswith("/herdr") for w in words) and words & VERBS:
                        hits.append(f"{f.relative_to(ROOT)}:{node.lineno}: {sorted(words & VERBS)}")
        self.assertEqual(hits, [], "a herdr argv with a write verb")

    def test_the_scans_see_what_they_should(self):   # guards against a scan that silently matches nothing
        lo, hi = _prompt_span()
        body = "\n".join(SERVER.read_text(encoding="utf-8").splitlines()[lo - 1:hi])
        self.assertRegex(body, WRITE)
        tree = ast.parse("subprocess.run(['herdr', 'agent', 'prompt', 'w1:p1', 'x'])")
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.List))
        self.assertTrue({e.value for e in node.elts} & VERBS)


if __name__ == "__main__":
    unittest.main()
