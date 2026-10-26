import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent


class NixiAskTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_env = os.environ.copy()
        cls.tmp = tempfile.mkdtemp(prefix="nixi-ask-test-")
        for k, d in (("HOME", ""), ("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
            os.environ[k] = os.path.join(cls.tmp, d)
            os.makedirs(os.environ[k], exist_ok=True)
        sys.path.insert(0, str(REPO_ROOT / "app"))
        import quick
        import server
        cls.server, cls.quick = server, quick

    @classmethod
    def tearDownClass(cls):
        os.environ.clear()
        os.environ.update(cls._orig_env)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_triggers(self):
        h = self.quick.handle
        for s in ("continue in nixi", "Continue this in Nixi.", "open this in nixi", "open that in nixi",
                  "hand this to nixi", "hand it over to nixi", "nixi, continue in nixi", "continue in nixie",
                  "Ok Nixi. Continue in Nixi"):
            self.assertEqual(h(s), {"nixi_ask": None}, s)
        self.assertEqual(h("Open Nixi and ask How do I undo a commit?"), {"nixi_ask": "How do I undo a commit?"})
        self.assertEqual(h("ok nixi, open nixie and ask him what a flake is"), {"nixi_ask": "what a flake is"})
        with mock.patch.object(self.quick, "projects", return_value={}):    # these fall through to "open <project>"
            for s in ("open nixi and ask him", "open nixi and ask it."):
                self.assertNotIn("nixi_ask", h(s) or {}, s)
        for s in ("continue", "continue the music"):
            self.assertNotIn("nixi_ask", h(s) or {}, s)

    def test_open_in_nixi(self):
        s = self.server
        only_nixi = lambda n: "/bin/nixi" if n == "nixi" else None
        for ret, exc, want in ((0, None, "Over to Nixi."), (1, None, "Nixi's card is off. Turn it on in Setup → Plugins."),
                               (None, subprocess.TimeoutExpired("nixi", 3), "Over to Nixi.")):
            p = mock.Mock()
            p.wait.side_effect = exc or None
            p.wait.return_value = ret
            with mock.patch.object(s.ST, "last_you", "  what is a flake?  "), mock.patch.object(s, "stop_proc") as stop, \
                    mock.patch.object(s.shutil, "which", side_effect=only_nixi), \
                    mock.patch.object(s.subprocess, "Popen", return_value=p) as pop:
                self.assertEqual(s.open_in_nixi(None), want)       # falls back to the last request
                self.assertEqual(pop.call_args[0][0], ["/bin/nixi", "--ask", "what is a flake?"])
                self.assertEqual(stop.call_count, 0 if ret == 1 else 1)    # card off: the turn is kept
        with mock.patch.object(s.shutil, "which", side_effect=only_nixi), mock.patch.object(s, "stop_proc"), \
                mock.patch.object(s.subprocess, "Popen", return_value=mock.Mock(wait=mock.Mock(return_value=0))) as pop:
            s.open_in_nixi("x" * 3000)
            self.assertEqual(len(pop.call_args[0][0][2]), 2000)    # capped

    def test_real_exit_codes(self):
        """A real process, no Popen mock: the card-off exit code must reach us."""
        s = self.server
        for body, want in (("exit 1", "card is off"), ("exit 0", "Over to Nixi."), ("sleep 5", "Over to Nixi.")):
            stub = os.path.join(self.tmp, "nixi")
            with open(stub, "w") as f:
                f.write("#!/bin/sh\n" + body + "\n")
            os.chmod(stub, 0o755)
            with mock.patch.object(s.shutil, "which", side_effect=lambda n: stub if n == "nixi" else "/bin/" + n), \
                    mock.patch.object(s, "stop_proc"):
                self.assertIn(want, s.open_in_nixi("hi"), body)

    def test_empty_and_missing(self):
        s = self.server
        with mock.patch.object(s.ST, "last_you", ""), mock.patch.object(s, "stop_proc") as stop:
            self.assertEqual(s.open_in_nixi(""), "What should I ask Nixi?")
            stop.assert_not_called()
        with mock.patch.object(s.shutil, "which", return_value=None), mock.patch.object(s, "stop_proc") as stop:
            self.assertIn("card is off", s.open_in_nixi("hi"))
            stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
