"""update skills/nixi-plugin/reference when the plugin API changes"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "app"))
import plugins  # noqa: E402

SKILL = REPO / "skills/nixi-plugin"
TEMPLATE = SKILL / "template"


def setUpModule():
    if os.environ.get("NIXI_SANDBOX_TESTS") == "require" and not plugins.bwrap_ok():
        raise RuntimeError("NIXI_SANDBOX_TESTS=require, but bwrap doesn't work here")


class PluginSkillTest(unittest.TestCase):
    def test_template_is_valid_and_executable(self):
        self.assertIsNone(plugins.check_dir(TEMPLATE))
        self.assertTrue(os.access(TEMPLATE / "run", os.X_OK))

    @unittest.skipUnless(plugins.bwrap_ok(), "needs a working bwrap")
    def test_template_runs_in_sandbox(self):
        manifest = json.loads((TEMPLATE / "plugin.json").read_text())
        with tempfile.TemporaryDirectory() as root:
            state = plugins.State(Path(root) / "st.json")
            state.set(manifest["id"], True, plugins.sha256_of(TEMPLATE))
            p = plugins.Plugin(manifest["id"], TEMPLATE, manifest, "folder", None)
            with mock.patch.object(plugins, "State", return_value=state):
                got = plugins.run_stage(p, manifest["stage"]["phrases"][0], fresh=True)
        self.assertEqual(got["points"], ["First fact from my-plugin.", "Second fact from my-plugin."])

    def test_reference_tables_match_api(self):
        tables = {
            "manifest keys": ("manifest.md", plugins.REQUIRED | plugins.OPTIONAL),
            "prop keys": ("manifest.md", plugins.PROP_KEYS),
            "character keys": ("manifest.md", plugins.CHARACTER_KEYS),
            "round fits": ("manifest.md", plugins.ROUND_FITS),
            "categories": ("manifest.md", plugins.CATEGORIES),
            "reactions": ("manifest.md", plugins.REACTIONS),
            "stage keys": ("stage.md", plugins.STAGE_KEYS),
            "reads": ("stage.md", {"system-status", "peer-status", "phone-status"}),
        }
        found = {}
        for filename in ("manifest.md", "stage.md"):
            lines = (SKILL / "reference" / filename).read_text().splitlines()
            for i, line in enumerate(lines):
                if not line.startswith("### Table: "):
                    continue
                heading = line.removeprefix("### Table: ")
                self.assertNotIn(heading, found)
                # Tables end at the first non-table line after their header.
                start = next(j for j, row in enumerate(lines[i + 1:]) if row.startswith("|")) + i + 1
                self.assertTrue(all(not row.strip() for row in lines[i + 1:start]))
                rows = []
                for row in lines[start + 2:]:
                    if not row.startswith("|"):
                        break
                    rows.append(row)
                found[heading] = (filename, [row.split("|")[1].strip().strip("`") for row in rows])
        self.assertEqual(set(found), set(tables))
        for heading, (filename, allowed) in tables.items():
            with self.subTest(table=heading):
                actual_file, entries = found[heading]
                self.assertEqual(actual_file, filename)
                self.assertTrue(entries)
                for entry in entries:
                    self.assertIn(entry, allowed)
        manifest = json.loads((TEMPLATE / "plugin.json").read_text())
        for read in found["reads"][1]:
            with self.subTest(read=read):
                sample = {**manifest, "stage": {**manifest["stage"], "reads": [read]}}
                self.assertIsNone(plugins._check(sample, TEMPLATE))

    def test_skill_has_no_symlinks_or_private_template(self):
        for root, dirs, files in os.walk(SKILL):
            for name in dirs + files:
                path = Path(root) / name
                self.assertFalse(path.is_symlink(), str(path))
        manifest = json.loads((TEMPLATE / "plugin.json").read_text())
        self.assertNotIn("private", manifest)


if __name__ == "__main__":
    unittest.main()
