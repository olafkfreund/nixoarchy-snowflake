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


def setUpModule():
    if os.environ.get("NIXI_SANDBOX_TESTS") != "require":
        return
    missing = [n for n, ok in (("bwrap", shutil.which("bwrap") and plugins.bwrap_ok()), ("pasta", plugins.pasta_ok()), ("ip", shutil.which("ip"))) if not ok]
    if missing:
        raise RuntimeError("NIXI_SANDBOX_TESTS=require, but these don't work here: " + ", ".join(missing))


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
        self.assertEqual(a[0].rsplit("/", 1)[-1], "pasta")
        self.assertIn("--no-map-gw", a)
        self.assertNotIn("--map-host-loopback", a)
        a = a[a.index("bwrap"):]
        self.assertEqual(a[:8], ["bwrap", "--clearenv", "--unshare-all", "--unshare-user", "--disable-userns", "--cap-drop", "ALL", "--share-net"])
        self.assertEqual(a[a.index("/dev/shm") - 3:a.index("/dev/shm") + 1], ["--size", str(plugins.SHM_SIZE), "--tmpfs", "/dev/shm"])
        self.assertIn("RLIMIT_NPROC", a[-2])
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

    @unittest.skipUnless(plugins.pasta_ok(), "needs pasta")
    def test_network_plugins_cannot_reach_this_computers_own_services(self):
        port = str(self.serve())                      # the host's loopback: a TCP service like adb
        self.assertEqual(self.facts(self.mk(self.PROBE, network=True, files={"port": port})), ["refused"])
        name = "\0nixi-probe-%d" % os.getpid()       # an abstract socket in the host's namespace (like 1Password's, X11's)
        srv = socket.socket(socket.AF_UNIX)
        srv.bind(name)
        srv.listen(5)
        self.addCleanup(srv.close)
        body = ("import json, socket\ns = socket.socket(socket.AF_UNIX)\n"
                "try:\n    s.connect(open('name').read().replace('@', '\\0'))\n    r = 'connected'\nexcept OSError:\n    r = 'refused'\n"
                "print(json.dumps({'v':1,'kind':'facts','title':'t','points':[r]}))")
        self.assertEqual(self.facts(self.mk(body, network=True, files={"name": name.replace("\0", "@")})), ["refused"])

    @unittest.skipUnless(plugins.pasta_ok() and shutil.which("ip"), "needs pasta and ip")
    def test_network_plugins_cannot_reach_this_computers_other_addresses(self):
        addrs = [a for a in plugins._host_addrs() if not a.startswith("fe80") and "/" not in a]
        self.assertTrue(addrs)
        srv = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        srv.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        srv.bind(("::", 0))                           # every address, v4 and v6
        srv.listen(5)
        self.addCleanup(srv.close)
        body = ("import json, socket\nr = []\nfor a in open('addrs').read().split():\n    s = socket.socket(socket.AF_INET6 if ':' in a else socket.AF_INET)\n"
                "    s.settimeout(0.2)\n    try:\n        s.connect((a, int(open('port').read())))\n        r.append('connected ' + a)\n"
                "    except OSError:\n        pass\nprint(json.dumps({'v':1,'kind':'facts','title':'t','points':['none'] if not r else ['connected to %d, e.g. %s' % (len(r), r[0])]}))")
        self.assertEqual(self.facts(self.mk(body, network=True, files={"addrs": "\n".join(addrs), "port": str(srv.getsockname()[1])})), ["none"])

    @unittest.skipUnless(plugins.pasta_ok() and shutil.which("ip"), "needs pasta and ip")
    def test_the_routes_cannot_be_removed_from_inside(self):
        a = [x for x in plugins._host_addrs() if "/" not in x][0]          # one of the blocking routes itself, not the default route
        body = ("import json, subprocess\nr = subprocess.run([%r, 'route', 'del', 'unreachable', %r], capture_output=True)\n"
                "print(json.dumps({'v':1,'kind':'facts','title':'t','points':['removed' if r.returncode == 0 else 'refused']}))") % (
                    os.path.realpath(shutil.which("ip")), a + ("/128" if ":" in a else "/32"))
        self.assertEqual(self.facts(self.mk(body, network=True)), ["refused"])

    def test_a_network_plugin_will_not_run_without_the_address_list(self):
        p = self.mk("print(1)", network=True)
        with mock.patch.object(plugins.subprocess, "run", side_effect=OSError):
            with self.assertRaisesRegex(plugins.StageError, "addresses"):
                plugins.sandbox_argv(p.dir, p.manifest["stage"])

    HARD = ("import ctypes, json, os\nlibc = ctypes.CDLL(None, use_errno=True)\nr = []\n"
            "r.append('userns' if libc.unshare(0x10000000) == 0 else 'no-userns')\n"
            "r.append('mount' if libc.mount(b'none', b'/tmp', b'tmpfs', 0, None) == 0 else 'no-mount')\n"
            "r.append('rw' if libc.mount(None, b'/plugin', None, 32 | 1 << 5, None) == 0 else 'ro')\n"
            "r.append([l for l in open('/proc/self/status') if l.startswith('CapEff')][0].split()[1])\n"
            "print(json.dumps({'v':1,'kind':'facts','title':'t','points':r}))")

    def test_no_nested_userns_no_mounts_no_capabilities(self):
        want = ["no-userns", "no-mount", "ro", "0" * 16]
        self.assertEqual(self.facts(self.mk(self.HARD)), want)

    @unittest.skipUnless(plugins.pasta_ok() and shutil.which("ip"), "needs pasta and ip")
    def test_no_nested_userns_no_mounts_no_capabilities_with_pasta(self):
        self.assertEqual(self.facts(self.mk(self.HARD, network=True)), ["no-userns", "no-mount", "ro", "0" * 16])

    def test_the_path_has_only_store_entries(self):
        with mock.patch.dict(os.environ, {"PATH": "/home/x/bin:/etc/profiles/per-user/x/bin:/nix/store/abc-x/bin"}):
            a = plugins.sandbox_argv("/d", {"argv": ["run"]})
        self.assertEqual(a[a.index("PATH") + 1].split(":")[:2], ["/plugin", "/nix/store/abc-x/bin"])
        p = self.mk("import json, os\nbad = [x for x in os.environ['PATH'].split(':') if not x.startswith('/nix/store/') and x != '/plugin']\n"
                    "print(json.dumps({'v':1,'kind':'facts','title':'t','points':['bad:' + ','.join(bad)]}))")
        self.assertEqual(self.facts(p), ["bad:"])

    def test_a_hard_link_is_refused(self):
        outside = self.root / "outside"
        outside.write_text("secret")
        d = self.root / "hl"
        d.mkdir()
        os.link(outside, d / "x")
        with self.assertRaisesRegex(ValueError, "hard link"):
            plugins._snap(d)

    def test_a_deduplicated_file_in_the_store_is_fine(self):
        outside = self.root / "outside"
        outside.write_text("same")
        d = self.root / "st"
        d.mkdir()
        os.link(outside, d / "x")
        with mock.patch.object(plugins, "_in_store", return_value=True):
            self.assertEqual(len(plugins._snap(d)), 64)

    def test_a_network_plugin_will_not_run_without_pasta(self):
        p = self.mk("print(1)", network=True)
        with mock.patch.object(plugins, "pasta_ok", return_value=False):
            with self.assertRaisesRegex(plugins.StageError, "pasta"):
                self.facts(p)

    def test_a_fork_loop_is_stopped_by_the_process_limit(self):
        p = self.mk("import json, os, time\nkids = []\nfor _ in range(200):\n    try:\n        pid = os.fork()\n    except OSError:\n        break\n"
                    "    if pid == 0:\n        time.sleep(1)\n        os._exit(0)\n    kids.append(pid)\n"
                    "for k in kids:\n    os.waitpid(k, 0)\nprint(json.dumps({'v':1,'kind':'facts','title':'t','points':[str(len(kids))]}))")
        n = int(self.facts(p, timeout=8)[0])
        self.assertTrue(0 < n < plugins.NPROC, n)

    def test_dev_shm_is_capped(self):
        p = self.mk("import json\ntry:\n    with open('/dev/shm/big', 'wb') as f:\n        for _ in range(32):\n            f.write(b'x' * (1 << 20))\n    r = 'wrote'\n"
                    "except OSError:\n    r = 'refused'\nprint(json.dumps({'v':1,'kind':'facts','title':'t','points':[r]}))")
        self.assertEqual(self.facts(p), ["refused"])

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
        with mock.patch.object(plugins, "system_status", return_value={"generation": "nixos-system-h-1", "failed": None, "failed_system": None}):
            got = plugins.run_stage(load(EX / "nix-status"), "nixi status")
        h = got["hosts"][0]
        self.assertEqual(h["lists"][0]["items"], ["unavailable"])
        self.assertEqual(h["badges"][0], {"k": "gen", "v": "system-h-1"})
        self.assertTrue(all(m["pct"] is None for m in h["meters"][:2]))      # unknown is null, never 0

    def test_nix_status_partial_failure_is_not_all_fine(self):
        for failed, failed_system, items, tone, say in (
            (None, [], ["not all checked"], "warn", "I couldn't check all the services."),
            (["a.service"], None, ["a.service"], "bad", "One failed service: a.service. I couldn't check all of them."),
        ):
            with self.subTest(failed=failed, failed_system=failed_system), \
                    mock.patch.object(plugins, "system_status", return_value={"failed": failed, "failed_system": failed_system}):
                got = plugins.run_stage(load(EX / "nix-status"), "nixi status", fresh=True)
                self.assertEqual(got["hosts"][0]["lists"][0]["items"], items)
                self.assertEqual(got["hosts"][0]["lists"][0]["tone"], tone)
                self.assertEqual(got["say"], say)

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
        bins = {str(Path(x).resolve().parent) for x in (sys.executable, shutil.which("bwrap"))}   # the packaged PATH has no coreutils (#149 B5)
        with mock.patch.dict(os.environ, {"PATH": ":".join(bins)}):
            self.assertFalse(any(os.path.exists(os.path.join(b, "df")) for b in bins if b.startswith("/nix/store/")))   # (the sandbox keeps only these)
            got = plugins.run_stage(load(EX / "nix-status"), "nixi status")
        self.assertEqual((got["kind"], got["title"], got["live"], len(got["hosts"])), ("gauges", "Nix status", True, 1))
        self.assertTrue(got["say"])
        self.assertEqual([m["label"] for m in got["hosts"][0]["meters"]], ["CPU", "MEM", "/", "STORE", "NET \u2193", "NET \u2191"])
        store = got["hosts"][0]["meters"][3]
        self.assertIsNotNone(store["pct"])                                   # the statvfs fallback worked without df
        self.assertRegex(store["text"], r"^\S+ \S+ / \S+ \S+$")

    def test_nix_status_reads_the_host_and_says_what_failed(self):
        ss = {"generation": "nixos-system-h-1", "failed": ["a.service"], "failed_system": ["b.service"], "cpu_pct": 18.0, "host": "p620",
              "mem": {"total": 64 << 30, "available": 4 << 30}, "disks": [{"path": "/", "total": 100, "used": 50}, {"path": "/nix/store", "total": 100, "used": 25}],
              "net": {"rx_bps": 1.5e6, "tx_bps": None}, "uptime_s": 90000}
        with mock.patch.object(plugins, "system_status", return_value=ss):
            got = plugins.run_stage(load(EX / "nix-status"), "nixi status")
        h = got["hosts"][0]
        self.assertEqual((h["name"], got["say"], h["lists"][0]), ("p620", "2 failed services. Memory is high.", {"title": "Failed", "items": ["a.service", "b.service"], "tone": "bad"}))
        self.assertEqual([m["pct"] for m in h["meters"]], [18.0, 93.8, 50.0, 25.0, None, None])
        self.assertEqual((h["meters"][4]["text"], h["meters"][5]["text"], h["badges"][1]), ("1.4 MB/s", "unavailable", {"k": "up", "v": "1d 1h"}))

    def fleet(self, peers, ss=None, rev="a" * 40):
        import peers as peers_mod
        import stages
        ss = ss if ss is not None else {"generation": "nixos-system-h-1", "failed": [], "failed_system": [], "host": "p620", "rev": rev, "built": "2026-11-04T11:56:52.893078+00:00"}
        with mock.patch.object(plugins, "system_status", return_value=ss), mock.patch.object(plugins, "peers_allowed", lambda: True), \
                mock.patch.object(peers_mod, "snapshot", return_value=peers):
            got = plugins.run_stage(load(EX / "nix-status"), "nixi status", fresh=True)
        self.assertIsNotNone(stages.validate(got))
        return got

    @staticmethod
    def up(name, rev="a" * 40, failed=()):
        return {"name": name, "state": "up", "last_ok": 1.0, "status": {"rev": rev, "built": "2026-11-03T08:01:02+00:00", "failed": None, "failed_system": list(failed),
                "cpu_pct": 5.0, "uptime_s": 3600, "mem": {"total": 100, "available": 50}, "disks": [{"path": "/", "total": 100, "used": 10}]}}

    def test_nix_status_fleet_shows_every_machine(self):
        got = self.fleet([self.up("p510", failed=["secret.service"]), {"name": "evo", "state": "asking", "status": None, "last_ok": None},
                          {"name": "razer", "state": "down", "status": None, "last_ok": None}])
        self.assertEqual([(h["name"], h["state"]) for h in got["hosts"]], [("p620", "up"), ("p510", "up"), ("evo", "stale"), ("razer", "down")])
        self.assertEqual([m["label"] for m in got["hosts"][1]["meters"]], ["CPU", "MEM", "/", "STORE"])
        self.assertEqual(got["hosts"][3]["badges"], [{"k": "last", "v": "not seen yet"}])
        self.assertEqual(got["say"], "p510 has one failed service. razer is off.")
        self.assertNotIn("secret", got["say"])
        self.assertEqual({"k": "rev", "v": "aaaaaaa"}, got["hosts"][0]["badges"][1])
        # built is the date of system_status's full ISO 8601 time, on this host and on peers
        self.assertIn({"k": "built", "v": "2026-11-04"}, got["hosts"][0]["badges"])
        self.assertIn({"k": "built", "v": "2026-11-03"}, got["hosts"][1]["badges"])

    def test_nix_status_fleet_without_peers_is_the_one_host_board(self):
        got = self.fleet([])
        self.assertEqual((len(got["hosts"]), got["say"]), (1, "All fine."))

    def test_nix_status_fleet_all_fine(self):
        self.assertEqual(self.fleet([self.up("p510"), {"name": "evo", "state": "asking", "status": None, "last_ok": None}])["say"], "All machines look fine.")

    def test_nix_status_fleet_revisions(self):
        got = self.fleet([self.up("p510", rev="b" * 40)])
        self.assertEqual(got["hosts"][1]["badges"][0], {"k": "rev", "v": "≠ bbbbbbb", "tone": "warn"})
        self.assertEqual(got["say"], "p510 is on another revision.")
        got = self.fleet([self.up("p510", rev="c" * 40 + "-dirty")])
        self.assertIn("dirty", got["hosts"][1]["badges"][0]["v"])

    def test_nix_status_fleet_unknown_failed_units_are_not_none(self):   # failed_system null: the check failed on that machine
        peer = self.up("p510")
        peer["status"]["failed_system"] = None
        got = self.fleet([peer])
        self.assertEqual(got["hosts"][1]["lists"], [{"title": "Failed (system)", "items": ["unknown"], "tone": "warn"}])
        self.assertEqual(got["say"], "No problems I can see.")

    def test_nix_status_fleet_a_peers_bad_text_cant_blank_the_board(self):   # (fleet() validates the whole board)
        peer = self.up("p510", rev="b\x07" + "b" * 39, failed=["", "a\nb", "ok.service"])
        got = self.fleet([peer])
        self.assertEqual(got["hosts"][1]["lists"][0]["items"], ["ab", "ok.service"])
        self.assertEqual(got["hosts"][1]["badges"][0]["v"], "≠ bbbbbbb")

    def test_nix_status_fleet_say_is_capped(self):
        got = self.fleet([self.up("m%d" % i + "x" * 30, failed=["a", "b"]) for i in range(5)])
        self.assertLessEqual(len(got["say"]), 200)
        self.assertRegex(got["say"], r"and \d+ more\.$")

    @unittest.skipUnless(plugins.pasta_ok(), "needs pasta")
    def test_rss_headlines_example_against_a_local_feed(self):
        # the fixture listens on the host's loopback, which the sandbox cannot see; this test alone maps 10.255.255.1 to it (production never does)
        mock.patch.object(plugins, "PASTA_EXTRA", ["--map-host-loopback", "10.255.255.1"]).start()
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
        (d / "config.json").write_text(json.dumps({"url": "http://10.255.255.1:%d/feed.xml" % srv.server_port}))
        self.assertIsNone(plugins.check_dir(d))
        got = plugins.run_stage(load(d), "rss headlines")
        self.assertEqual(got["points"], ["Headline %d & more" % i for i in range(1, 6)])
        d2 = self.root / "rss-off"
        shutil.copytree(d, d2)
        m = json.loads((d2 / "plugin.json").read_text())
        m["stage"]["network"] = False
        (d2 / "plugin.json").write_text(json.dumps(m))
        plugins._cache.clear()
        with self.assertRaises(plugins.StageError):             # the same program with the network off: nothing to show
            plugins.run_stage(load(d2), "rss headlines")

    @unittest.skipUnless(plugins.pasta_ok(), "needs pasta")
    def test_news_refuses_unsafe_feed_urls_in_real_sandbox(self):
        d = self.root / "news"
        shutil.copytree(EX / "news", d)
        config = self.root / "config"
        path = config / "nixi-companion" / "plugin-config"
        path.mkdir(parents=True)
        (path / "news.json").write_text(json.dumps({"feeds": [
            {"name": "Private", "url": "https://127.0.0.1/a"},
            {"name": "Local", "url": "https://nas.local/b"}]}))
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}):
            start = time.monotonic()
            got = plugins.run_stage(load(d), "news")
        self.assertLess(time.monotonic() - start, plugins.TIME_DEFAULT)
        self.assertEqual((got["kind"], got["title"], got["points"]),
                         ("facts", "News", ["No news feeds could be reached."]))
        self.assertIn("2 couldn't be reached", got["source"])


class ExamplesCheckTest(unittest.TestCase):
    def test_check_cli_passes(self):
        for n in ("nix-status", "rss-headlines", "news"):
            r = subprocess.run([sys.executable, str(REPO / "app/plugins.py"), "--check", str(EX / n)], capture_output=True, text=True)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, "ok"), r.stderr)


if __name__ == "__main__":
    unittest.main()
