"""#149 slice B: the real bwrap sandbox (skipped without bwrap), and the two example stage plugins running in it."""
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "app"))
import plugins  # noqa: E402

EX = REPO / "plugins/examples"
RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Feed</title>
%s</channel></rss>""" % b"".join(b"<item><title>Headline %d &amp; more</title></item>" % i for i in range(1, 8))


STATE = plugins.State(Path(tempfile.mkdtemp()) / "st.json")        # what these tests have "allowed"


def load(d):
    m = json.loads((Path(d) / "plugin.json").read_text())
    STATE.set(m["id"], True, plugins.sha256_of(d))
    return plugins.Plugin(m["id"], Path(d), m, "folder", None)


@unittest.skipUnless(shutil.which("bwrap") and plugins.bwrap_ok(), "needs a working bwrap")
class SandboxTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        plugins._cache.clear()
        mock.patch.object(plugins, "State", lambda *a: STATE).start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(shutil.rmtree, self.root, True)

    def mk(self, body, network=False, files=None, **stage):
        d = Path(tempfile.mkdtemp(dir=self.root))
        (d / "run").write_text("#!/usr/bin/env python3\n" + body)
        (d / "run").chmod(0o755)
        for n, c in (files or {}).items():
            (d / n).write_text(c)
        (d / "plugin.json").write_text(json.dumps({"api": 1, "id": "sb-test", "name": "T", "version": "1", "stage": {
            "phrases": ["zz top"], "argv": ["run"], "network": network, "cache_seconds": 0, **stage}}))
        return load(d)

    def facts(self, p, **kw):
        return plugins.run_stage(p, "q", **kw)["points"]

    def test_argv_shape(self):
        p = self.mk("", network=True, reads=["system-status"])
        a = plugins.sandbox_argv(p.dir, p.manifest["stage"])
        self.assertEqual(a[:4], ["bwrap", "--clearenv", "--unshare-all", "--share-net"])
        for flag in ("--die-with-parent", "--new-session", "--tmpfs", "--proc", "--dev", "--chdir"):
            self.assertIn(flag, a)
        self.assertEqual(a[a.index("--ro-bind") + 1:a.index("--ro-bind") + 3], ["/nix/store", "/nix/store"])
        self.assertEqual(a[a.index(str(p.dir)):a.index(str(p.dir)) + 2], [str(p.dir), "/plugin"])
        self.assertEqual(a[-1], "/plugin/run")
        self.assertEqual(a[a.index("HOME") + 1], "/tmp")
        self.assertTrue(a[a.index("PATH") + 1].startswith("/plugin:"))
        self.assertNotIn("--share-net", plugins.sandbox_argv(p.dir, {**p.manifest["stage"], "network": False}))
        self.assertNotIn("/run/current-system", plugins.sandbox_argv(p.dir, {"argv": ["run"]}))

    def test_cannot_read_home_or_the_host(self):
        secret = Path(os.path.expanduser("~")) / ".nixi-sandbox-probe"
        try:
            secret.write_text("x")
        except OSError:
            secret = None
        p = self.mk("import json, os\nr = lambda f: str(os.path.exists(f))\n"
                    "print(json.dumps({'v':1,'kind':'facts','title':'t','points':[r(open('probe').read()), r('/home'), r('/etc/passwd'), r('/run/user')]}))",
                    files={"probe": str(secret or "/nonexistent")})
        self.assertEqual(self.facts(p), ["False", "False", "False", "False"])
        if secret:
            secret.unlink()

    def test_only_the_declared_environment(self):
        os.environ["NIXI_PROBE_SECRET"] = "s3"
        self.addCleanup(os.environ.pop, "NIXI_PROBE_SECRET", None)
        p = self.mk("import json, os\nprint(json.dumps({'v':1,'kind':'facts','title':'t','points':[','.join(sorted(os.environ)), os.environ['HOME'], os.getcwd()]}))")
        keys, home, cwd = self.facts(p)
        self.assertEqual((home, cwd), ("/tmp", "/plugin"))
        self.assertEqual(set(keys.split(",")) - {"LC_CTYPE", "PWD", "PYTHONNOUSERSITE"}, {"HOME", "LANG", "PATH"})      # (the rest is the interpreter's own)

    def serve(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(5)
        self.addCleanup(srv.close)
        return srv.getsockname()[1]

    PROBE = ("import json, socket\ns = socket.socket()\ns.settimeout(2)\n"
             "try:\n    s.connect(('127.0.0.1', int(open('port').read())))\n    r = 'connected'\nexcept OSError as e:\n    r = 'refused'\n"
             "print(json.dumps({'v':1,'kind':'facts','title':'t','points':[r]}))")

    def test_no_network_unless_the_manifest_says_so(self):
        port = str(self.serve())                      # a listener on the host's loopback
        self.assertEqual(self.facts(self.mk(self.PROBE, network=False, files={"port": port})), ["refused"])
        self.assertEqual(self.facts(self.mk(self.PROBE, network=True, files={"port": port})), ["connected"])

    def test_cannot_write_the_plugin_folder(self):
        p = self.mk("import json\ntry:\n    open('x', 'w'); r = 'wrote'\nexcept OSError:\n    r = 'read-only'\n"
                    "print(json.dumps({'v':1,'kind':'facts','title':'t','points':[r]}))")
        self.assertEqual(self.facts(p), ["read-only"])

    def test_killed_at_the_time_limit(self):
        t = time.monotonic()
        with self.assertRaisesRegex(plugins.StageError, "too long"):
            self.facts(self.mk("import time\ntime.sleep(60)"), timeout=1)
        self.assertLess(time.monotonic() - t, 4)

    def test_no_systemd_socket_even_with_system_status(self):
        uid = os.getuid()
        body = ("import json, os, socket\nr = []\n"
                "for q in ('/run/user/%d/systemd/private', '/run/user/%d/systemd', '/run/current-system'):\n    r.append(str(os.path.exists(q)))\n"
                "s = socket.socket(socket.AF_UNIX)\ntry:\n    s.connect('/run/user/%d/systemd/private'); r.append('connected')\nexcept OSError:\n    r.append('refused')\n"
                "print(json.dumps({'v':1,'kind':'facts','title':'t','points':r}))") % (uid, uid, uid)
        p = self.mk(body, reads=["system-status"])
        self.assertNotIn(f"/run/user/{uid}", " ".join(plugins.sandbox_argv(p.dir, p.manifest["stage"])))
        self.assertEqual(self.facts(p), ["False", "False", "False", "refused"])

    def test_system_status_arrives_on_stdin(self):
        p = self.mk("import json, sys\nq = json.load(sys.stdin)['system_status']\n"
                    "print(json.dumps({'v':1,'kind':'facts','title':'t','points':[json.dumps(q)]}))", reads=["system-status"])
        with mock.patch.object(plugins, "system_status", return_value={"generation": "g-1", "failed": ["a.service"]}):
            self.assertEqual(json.loads(self.facts(p)[0]), {"generation": "g-1", "failed": ["a.service"]})

    def test_nix_status_says_unavailable_when_the_query_failed(self):
        with mock.patch.object(plugins, "system_status", return_value={"generation": "nixos-system-h-1", "failed": None}):
            pts = plugins.run_stage(load(EX / "nix-status"), "nixi status")["points"]
        self.assertEqual(pts[:2], ["System: system-h-1", "Failed user services: unavailable"])

    def test_a_file_over_64_mib_cannot_be_written(self):
        p = self.mk("import json\ntry:\n    with open('/tmp/big', 'wb') as f:\n        for _ in range(80):\n            f.write(b'x' * (1 << 20))\n    r = 'wrote'\n"
                    "except OSError:\n    r = 'refused'\nprint(json.dumps({'v':1,'kind':'facts','title':'t','points':[r]}))")
        try:
            self.assertEqual(self.facts(p), ["refused"])
        except plugins.StageError:                                 # (or the limit's signal ended it: also no file)
            pass
        self.assertIn(str(plugins.TMP_SIZE), plugins.sandbox_argv(p.dir, p.manifest["stage"]))

    def test_stdin_and_stderr_cannot_hold_it_past_the_limit(self):
        t = time.monotonic()
        with self.assertRaisesRegex(plugins.StageError, "too long"):
            plugins.run_stage(self.mk("import time\ntime.sleep(60)"), "x" * 200_000, timeout=1)
        self.assertLess(time.monotonic() - t, 4)
        got = self.facts(self.mk("import sys, json\nsys.stderr.write('e' * 100_000)\nprint(json.dumps({'v':1,'kind':'facts','title':'t','points':['ok']}))"))
        self.assertEqual(got, ["ok"])

    def test_oversized_output_refused(self):
        with self.assertRaisesRegex(plugins.StageError, "too much"):
            self.facts(self.mk("import sys\nsys.stdout.write('x' * 70000)"))

    # ---- the two examples, as shipped
    def test_nix_status_example(self):
        self.assertIsNone(plugins.check_dir(EX / "nix-status"))
        got = plugins.run_stage(load(EX / "nix-status"), "nixi status")
        self.assertEqual((got["kind"], got["title"], len(got["points"])), ("facts", "Nix status", 3))
        self.assertTrue(got["points"][0].startswith("System: "))
        self.assertTrue(got["points"][2].startswith("Store: "))

    def test_rss_headlines_example_against_a_local_feed(self):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(RSS)

            def log_message(self, *a):
                pass
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        d = self.root / "rss-headlines"
        shutil.copytree(EX / "rss-headlines", d)
        (d / "config.json").write_text(json.dumps({"url": "http://127.0.0.1:%d/feed.xml" % srv.server_port}))
        self.assertIsNone(plugins.check_dir(d))
        got = plugins.run_stage(load(d), "headlines")
        self.assertEqual(got["points"], ["Headline %d & more" % i for i in range(1, 6)])
        d2 = self.root / "rss-off"
        shutil.copytree(d, d2)
        m = json.loads((d2 / "plugin.json").read_text())
        m["stage"]["network"] = False
        (d2 / "plugin.json").write_text(json.dumps(m))
        plugins._cache.clear()
        with self.assertRaises(plugins.StageError):             # the same program with the network off: nothing to show
            plugins.run_stage(load(d2), "headlines")


class ExamplesCheckTest(unittest.TestCase):
    def test_check_cli_passes(self):
        for n in ("nix-status", "rss-headlines"):
            r = subprocess.run([sys.executable, str(REPO / "app/plugins.py"), "--check", str(EX / n)], capture_output=True, text=True)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, "ok"), r.stderr)


if __name__ == "__main__":
    unittest.main()
