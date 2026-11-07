"""Catch stale setting names, launcher commands, and local links in the docs."""

import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

import nixi_env


ROOT = Path(__file__).resolve().parent.parent
DOCS = ("README.md", "docs/GETTING-STARTED.md", "docs/GUIDE.md")


class DocsNamesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_env = os.environ.copy()
        cls.tmp = tempfile.mkdtemp(prefix="nixi-docs-test-")
        for key, folder in (("HOME", ""), ("XDG_CONFIG_HOME", ".config"),
                            ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
            os.environ[key] = os.path.join(cls.tmp, folder)
            os.makedirs(os.environ[key], exist_ok=True)
        os.environ["XDG_RUNTIME_DIR"] = nixi_env.run_dir()
        sys.path.insert(0, str(ROOT / "app"))
        import server
        if not str(server.CONF_PATH).startswith(tempfile.gettempdir()):
            raise RuntimeError(f"server.py was imported outside a throwaway HOME; CONF_PATH={server.CONF_PATH}")
        nixi_env.check_floor_path(server.FLOOR.path)
        cls.defaults = server.DEFAULTS

        launcher = (ROOT / "bin/nixi-companion").read_text()
        cls.commands = set(re.findall(r'if \[ "\$\{1:-\}" = ([\w-]+) \]', launcher))
        for case in re.finditer(r'case (?:"\$\{1:-\}"|"\$CMD") in(.*?)^esac\b',
                                launcher, re.MULTILINE | re.DOTALL):
            for pattern in re.findall(r'^ {0,2}([\w-]+(?:\|[\w-]+)*)\)',
                                      '\n' + case.group(1), re.MULTILINE):
                cls.commands.update(pattern.split('|'))
        cmd_case = re.search(r'^case "\$CMD" in ([\w|-]+)\)', launcher, re.MULTILINE)
        cls.commands.update(cmd_case.group(1).split('|'))

    @classmethod
    def tearDownClass(cls):
        os.environ.clear()
        os.environ.update(cls._orig_env)
        sys.path.remove(str(ROOT / "app"))
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def check_settings(self, path):
        text = path.read_text()
        heading = re.search(r'^#{1,6}\s+Settings reference\b', text, re.I | re.M)
        if not heading:
            if os.environ.get("NIXI_DOCS_ALL") == "1":
                self.fail(f"{path}: missing Settings reference heading")
            return
        section = re.split(r'^#{1,6}\s+', text[heading.end():], maxsplit=1, flags=re.M)[0]
        keys = re.findall(r'^\|\s*`([^`]+)`\s*\|', section, re.M)
        self.assertTrue(keys, f"{path}: Settings reference has no key rows")
        for key in keys:
            self.assertIn(key, self.defaults, f"{path}: unknown setting {key}")

    def check_commands(self, path):
        fenced = False
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if re.match(r'^\s*```', line):
                fenced = not fenced
                continue
            snippets = [line] if fenced else re.findall(r'(?<!`)`([^`]+)`(?!`)', line)
            for snippet in snippets:
                for command in re.findall(r'\bnixi-companion[ \t]+([\w-]+)', snippet):
                    self.assertIn(command, self.commands, f"{path}:{number}: unknown command {command}")

    def check_links(self, path):
        for target in re.findall(r'!?\[[^\]]*\]\((<[^>]+>|[^)\s]+)', path.read_text()):
            target = target.strip('<>')
            parts = urlsplit(target)
            if parts.scheme or parts.netloc or not parts.path or parts.path.startswith('/'):
                continue
            linked = path.parent / unquote(parts.path)
            if (os.environ.get("NIXI_DOCS_ALL") != "1" and not linked.exists()
                    and linked.resolve() in (ROOT / name for name in DOCS)):
                continue
            self.assertTrue(linked.exists(), f"{path}: broken link {target}")

    def check_doc(self, name):
        path = ROOT / name
        if not path.exists():
            if os.environ.get("NIXI_DOCS_ALL") == "1":
                self.fail(f"missing doc: {name}")
            self.skipTest(f"missing doc: {name}")
        self.check_commands(path)
        self.check_links(path)
        if name == "docs/GUIDE.md":
            self.check_settings(path)

    def test_readme(self):
        self.check_doc(DOCS[0])

    def test_getting_started(self):
        self.check_doc(DOCS[1])

    def test_guide(self):
        self.check_doc(DOCS[2])

    def test_wrong_setting_fails(self):
        path = Path(self.tmp) / "wrong-setting.md"
        path.write_text("## Settings reference\n\n| Key | Default |\n| --- | --- |\n| `not_a_setting` | `1` |\n")
        with self.assertRaises(AssertionError):
            self.check_settings(path)

    def test_unknown_command_fails(self):
        path = Path(self.tmp) / "wrong-command.md"
        for text in ("Run `nixi-companion invented`.\n",
                     "```bash\nnixi-companion invented\n```\n"):
            path.write_text(text)
            with self.assertRaises(AssertionError):
                self.check_commands(path)

    def test_broken_link_fails(self):
        path = Path(self.tmp) / "broken-link.md"
        path.write_text("[Missing](nowhere.md#section)\n")
        with self.assertRaises(AssertionError):
            self.check_links(path)

    def test_launcher_special_commands_pass(self):
        path = Path(self.tmp) / "commands.md"
        path.write_text("`nixi-companion attention` `nixi-companion monitor` "
                        "`nixi-companion setup` `nixi-companion ptt-down`\n")
        self.check_commands(path)


if __name__ == "__main__":
    unittest.main()
