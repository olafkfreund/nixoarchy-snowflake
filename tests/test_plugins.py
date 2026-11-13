"""app/plugins.py: scan, manifest rules, hashing and the state file (#149)."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import plugins  # noqa: E402

GOOD = {"api": 1, "id": "pirate-quips", "name": "Pirate", "version": "1.0"}
DOTS = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-10 -10 20 20"><circle cx="0" cy="0" r="9" fill="#778899"/><circle cx="-3" cy="-2" r="1"/><circle cx="3" cy="-2" r="1"/></svg>'
CHARACTER = {"label": "Dots", "template": "round", "fill": "#778899", "back": "back.svg", "front": "front.svg", "fits": ["none", "halo", "plug"], "private": False}


class T(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.root = Path(self._t.name)
        mock.patch.object(plugins, "_in_store", lambda d: True).start()      # (the first dir stands in for the store)
        self.addCleanup(mock.patch.stopall)

    def mk(self, name, manifest, base="a", files=()):
        d = self.root / base / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "plugin.json").write_text(manifest if isinstance(manifest, str) else json.dumps(manifest))
        for f in files:
            (d / f).write_text("x")
        return d

    def one(self, manifest, files=()):
        shutil.rmtree(self.root / "a", ignore_errors=True)
        self.mk("p", manifest, files=files)
        (p,) = plugins.scan([self.root / "a"])
        return p

    def test_good(self):
        p = self.one(GOOD)
        self.assertIsNone(p.error)
        self.assertEqual((p.id, p.source), ("pirate-quips", "nix"))

    def test_reserved_voice_clips(self):
        self.assertTrue(plugins.reserved("play the first video"))
        self.assertTrue(plugins.reserved("play the second clip"))
        self.assertTrue(plugins.reserved("play the fifth video"))   # (agy review: every ordinal _ACT parses)
        self.assertTrue(plugins.reserved("open the first one"))

    def test_sources(self):
        self.mk("p", GOOD, "a")
        self.mk("q", dict(GOOD, id="other-one"), "b")
        self.assertEqual([x.source for x in plugins.scan([self.root / "a", self.root / "b"])], ["nix", "folder"])

    def test_bad_json_and_missing(self):
        self.assertIn("unreadable", self.one("{nope").error)
        (self.root / "a" / "empty").mkdir()
        self.assertIn("missing", [x for x in plugins.scan([self.root / "a"]) if x.dir.name == "empty"][0].error)

    def test_api(self):
        self.assertEqual(self.one(dict(GOOD, api=2, future=1)).error, "needs a newer Nixi")
        self.assertEqual(self.one(dict(GOOD, api=True)).error, "needs a newer Nixi")

    def test_required_unknown_id(self):
        self.assertIn("missing key: name", self.one({k: v for k, v in GOOD.items() if k != "name"}).error)
        self.assertIn("unknown key", self.one(dict(GOOD, extra=1)).error)
        for bad in ("ab", "Pirate", "-abc", "a" * 65, "a b c"):
            self.assertEqual(self.one(dict(GOOD, id=bad)).error, "bad id", bad)

    def test_duplicates_both_broken(self):
        self.mk("p", GOOD, "a")
        self.mk("q", GOOD, "b")
        r = plugins.scan([self.root / "a", self.root / "b"])
        self.assertEqual([x.error for x in r], [None, "duplicate id"])        # the Nix one wins over a Folder one
        self.mk("q", GOOD, "c")
        r = plugins.scan([self.root / "a", self.root / "c"])
        self.assertEqual([x.error for x in r], [None, "duplicate id"])
        self.mk("r", GOOD, "a")
        r = plugins.scan([self.root / "a", self.root / "b"])                    # two Nix ones: every one is marked
        self.assertEqual([x.error for x in r], ["duplicate id"] * 3)

    def test_no_valid_id_does_not_count_as_duplicate(self):
        self.mk("pirate-quips", GOOD, "a")
        self.mk("pirate-quips", dict(GOOD, id="BAD ID"), "b")
        r = plugins.scan([self.root / "a", self.root / "b"])
        self.assertEqual([x.error for x in r], [None, "bad id"])

    def test_notifications(self):
        ok = [{"app": "element", "category": "chat"}, {"host": "*.example.org", "category": "mail"}]
        self.assertIsNone(self.one(dict(GOOD, notifications=ok)).error)
        for bad in ([{"app": "Element", "category": "chat"}], [{"app": "a.*", "category": "chat"}],
                    [{"host": "a/b", "category": "chat"}], [{"app": "a", "host": "b", "category": "chat"}],
                    [{"app": "a", "category": "spam"}]):
            self.assertTrue(self.one(dict(GOOD, notifications=bad)).error, bad)

    def test_reactions(self):
        for entry in ({"app": "element", "reaction": "notice"},
                      {"host": "example.org", "reaction": "music"},
                      {"host": "*.example.org", "reaction": "notice"}):
            with self.subTest(entry=entry):
                self.assertIsNone(self.one(dict(GOOD, reactions=[entry])).error)

        bad = (({"app": "element", "reaction": "video"}, "reaction not allowed"),
               ({"app": "element", "reaction": "news"}, "reaction not allowed"),
               ({"app": "element", "reaction": "notice", "extra": 1}, "bad reactions entry"),
               ({"app": "element", "host": "example.org", "reaction": "notice"}, "bad reactions entry"),
               ({"app": "Element", "reaction": "notice"}, "notification app must be a literal lowercase id"),
               ({"host": "a/b", "reaction": "notice"}, "notification host must be a name or *.suffix"))
        for entry, error in bad:
            with self.subTest(entry=entry):
                self.assertEqual(self.one(dict(GOOD, reactions=[entry])).error, error)
        self.assertEqual(self.one(dict(GOOD, reactions={"app": "element"})).error, "bad reactions")

    def test_prop_and_quips(self):
        prop = {"file": "prop.svg", "anchor": "head", "layer": "front"}
        self.assertIsNone(self.one(dict(GOOD, prop=prop, quips="quips.json"), ["prop.svg", "quips.json"]).error)
        self.assertTrue(self.one(dict(GOOD, prop=dict(prop, anchor="feet")), ["prop.svg"]).error)
        self.assertTrue(self.one(dict(GOOD, prop=prop)).error)  # file missing

    def character_dir(self, private=False, base="user"):
        c = dict(CHARACTER, private=private)
        d = self.mk("dots", dict(GOOD, character=c), base)
        for side in ("back", "front"):
            (d / f"{side}.svg").write_text(DOTS)
        if private:
            for p in (d, *d.iterdir()):
                p.chmod(0o700 if p.is_dir() else 0o600)
        return d

    def test_character_manifest_and_art(self):
        d = self.character_dir()
        self.assertIsNone(plugins._check(json.loads((d / "plugin.json").read_text()), d))
        self.assertIsNone(plugins.scan([self.root / "pkg", self.root / "user"])[0].error)
        no_private = {k: v for k, v in CHARACTER.items() if k != "private"}   # (private is optional)
        self.assertIsNone(plugins._check(dict(GOOD, character=no_private), d))
        self.assertIsNotNone(plugins._check(dict(GOOD, character={k: v for k, v in CHARACTER.items() if k != "fill"}), d))
        for change in ({"template": "square"}, {"fits": ["none", "wings"]}, {"fill": "url(#x)"},
                       {"label": "x" * 21}, {"label": "bad\u202e"}, {"private": 1}, {"extra": 1}):
            with self.subTest(change=change):
                m = dict(GOOD, character={**CHARACTER, **change})
                self.assertIsNotNone(plugins._check(m, d))
        (d / "front.svg").unlink()
        self.assertIsNotNone(plugins._check(dict(GOOD, character=CHARACTER), d))

    def test_character_refuses_unsafe_art(self):
        d = self.character_dir()
        bad = ('<linearGradient/>', '<circle class="x"/>', '<script/>',
               '<circle onload="x()"/>', '<circle href="#x"/>', '<circle fill="url(#x)"/>')
        for node in bad:
            with self.subTest(node=node):
                (d / "front.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg">' + node + '</svg>')
                self.assertIsNotNone(plugins.scan([self.root / "pkg", self.root / "user"])[0].error)

    def test_private_character_refusals(self):
        d = self.character_dir(private=True)
        self.assertIsNone(plugins.scan([self.root / "pkg", self.root / "user"])[0].error)
        self.assertEqual(plugins.check_dir(d), plugins.PRIVATE_STORE_ERROR)
        (self.root / "pkg").mkdir()
        shutil.move(str(d), self.root / "pkg" / "dots")
        self.assertEqual(plugins.scan([self.root / "pkg", self.root / "user"])[0].error, plugins.PRIVATE_STORE_ERROR)
        shutil.move(str(self.root / "pkg" / "dots"), d)
        (d / "front.svg").chmod(0o640)
        self.assertEqual(plugins.scan([self.root / "pkg", self.root / "user"])[0].error, plugins.PRIVATE_MODE_ERROR)
        (d / "front.svg").chmod(0o600)
        real_lstat = os.lstat
        def foreign(path, *args, **kwargs):
            st = real_lstat(path, *args, **kwargs)
            return mock.Mock(st_uid=os.getuid() + 1, st_mode=st.st_mode) if os.fspath(path) == os.fspath(d / "front.svg") else st
        with mock.patch.object(plugins.os, "lstat", side_effect=foreign):
            self.assertEqual(plugins.scan([self.root / "pkg", self.root / "user"])[0].error, plugins.PRIVATE_MODE_ERROR)
        with mock.patch.object(plugins.os, "lstat", side_effect=OSError("secret marker")):
            self.assertEqual(plugins.scan([self.root / "pkg", self.root / "user"])[0].error, plugins.PRIVATE_MODE_ERROR)

    def test_private_errors_are_fixed(self):
        d = self.character_dir(private=True)
        (d / "front.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>')
        self.assertEqual(plugins.scan([self.root / "pkg", self.root / "user"])[0].error, plugins.PRIVATE_ART_ERROR)
        (d / "front.svg").write_text(DOTS)
        m = json.loads((d / "plugin.json").read_text())
        m["character"]["extra"] = "secret marker"
        (d / "plugin.json").write_text(json.dumps(m))
        self.assertEqual(plugins.scan([self.root / "pkg", self.root / "user"])[0].error, plugins.PRIVATE_ART_ERROR)
        m["character"].pop("extra")
        (d / "plugin.json").write_text(json.dumps(m))
        (d / "secret-marker").symlink_to(self.root / "outside")
        self.assertEqual(plugins.scan([self.root / "pkg", self.root / "user"])[0].error, plugins.PRIVATE_ART_ERROR)

    def test_stage_and_argv_escape(self):
        st = {"phrases": ["nixi status"], "argv": ["run"], "cache_seconds": 30}
        self.assertIsNone(self.one(dict(GOOD, stage=st), ["run"]).error)
        self.assertIn("argv[0]", self.one(dict(GOOD, stage=dict(st, argv=["../run"])), ["run"]).error)
        self.assertIn("argv[0]", self.one(dict(GOOD, stage=dict(st, argv=["/bin/sh"]))).error)
        self.assertIn("cache", self.one(dict(GOOD, stage=dict(st, cache_seconds=601)), ["run"]).error)
        self.assertTrue(self.one(dict(GOOD, stage=dict(st, reads=["home"])), ["run"]).error)

    def test_argv_symlink_escape(self):
        outside = self.root / "outside"
        outside.write_text("x")
        d = self.mk("p", dict(GOOD, stage={"phrases": ["x"], "argv": ["run"]}))
        os.symlink(outside, d / "run")
        (p,) = plugins.scan([self.root / "a"])
        self.assertIn("symlink", p.error)

    def test_symlinks_anywhere_fail_the_plugin(self):
        d = self.mk("p", GOOD, files=["quips.json"])
        (d / "plugin.json").rename(d / "real.json")
        os.symlink(d / "real.json", d / "plugin.json")                           # the manifest itself a symlink
        self.assertIn("symlink", plugins.scan([self.root / "a"])[0].error)

    def test_symlinked_folders_only_count_in_the_package_dir(self):
        real = self.mk("realone", GOOD, "elsewhere")
        for base in ("pkg", "user"):
            (self.root / base).mkdir()
            os.symlink(real, self.root / base / "linked")
        self.assertEqual(plugins.scan([self.root / "pkg"])[0].error, None)        # Nix store links
        self.assertEqual(plugins.scan([self.root / "empty", self.root / "user"]), [])

    def test_odd_manifests_never_stop_the_scan(self):
        self.mk("good-one", dict(GOOD, id="good-one"), "a")
        for i, extra in enumerate(({"notifications": [{"app": "x", "category": ["chat"]}]},
                                   {"stage": {"phrases": ["a b"], "argv": ["run"], "reads": [[1]]}},
                                   {"prop": {"file": "p.svg", "anchor": ["head"]}},
                                   {"prop": {"file": "p.svg", "anchor": "head", "layer": {"x": 1}}},
                                   {"notifications": [{"host": ["a"], "category": "chat"}]},
                                   {"quips": {"a": 1}}, {"description": 3}, {"stage": []}, {"notifications": 5})):
            self.mk(f"odd-{i}", dict(GOOD, id=f"odd-{i}", **extra), "a", files=["run", "p.svg"])
        r = plugins.scan([self.root / "a"])
        self.assertEqual(len(r), 10)
        self.assertEqual([x.error for x in r if x.id == "good-one"], [None])
        self.assertTrue(all(x.error for x in r if x.id.startswith("odd-")))

    def test_check_exception_becomes_that_plugins_error(self):
        self.mk("p", GOOD)
        from unittest import mock
        with mock.patch.object(plugins, "_check", side_effect=RuntimeError("boom")):
            (p,) = plugins.scan([self.root / "a"])
        self.assertIn("not understood", p.error)

    def test_sha256(self):
        d = self.mk("p", GOOD, files=["run"])
        h = plugins.sha256_of(d)
        self.assertEqual(h, plugins.sha256_of(d))
        (d / "run").write_text("y")
        self.assertNotEqual(h, plugins.sha256_of(d))
        h = plugins.sha256_of(d)
        outside = self.root / "outside"
        outside.write_text("x")
        os.symlink(outside, d / "link")
        with self.assertRaises(ValueError):          # any symlink at all fails it
            plugins.sha256_of(d)

    def test_state_roundtrip(self):
        f = self.root / "s" / "plugins-state.json"
        s = plugins.State(f)
        self.assertFalse(s.get("x")["enabled"])
        s.set("x", True, "abc")
        s2 = plugins.State(f)
        self.assertEqual(s2.get("x"), {"enabled": True, "sha256": "abc"})
        self.assertEqual(os.listdir(f.parent), ["plugins-state.json"])  # no temp left
        f.write_text("garbage")
        self.assertEqual(plugins.State(f).data, {})

    def test_network_and_system_status_are_refused_together(self):
        st = {"phrases": ["x"], "argv": ["run"], "reads": ["system-status"]}
        self.assertIsNone(self.one(dict(GOOD, stage=st), ["run"]).error)
        self.assertIsNone(self.one(dict(GOOD, stage=dict(st, network=True, reads=[])), ["run"]).error)
        self.assertIn("system status", self.one(dict(GOOD, stage=dict(st, network=True)), ["run"]).error)
        self.assertEqual(self.one(dict(GOOD, stage=dict(st, network=True, reads=["peer-status"])), ["run"]).error,
                         "a plugin that reads your other machines' status can't use the network")

    def test_phone_status_read_is_valid_and_refused_with_network(self):
        st = {"phrases": ["x"], "argv": ["run"], "reads": ["phone-status"]}
        self.assertIsNone(self.one(dict(GOOD, stage=st), ["run"]).error)
        self.assertIsNone(self.one(dict(GOOD, stage=dict(st, reads=["system-status", "phone-status"])), ["run"]).error)
        self.assertEqual(self.one(dict(GOOD, stage=dict(st, network=True)), ["run"]).error,
                         "a plugin that reads your phone's status can't use the network")
        self.assertEqual(self.one(dict(GOOD, stage=dict(st, reads=["phone-state"])), ["run"]).error, "bad stage reads")

    def test_plugin_dirs(self):
        d = plugins.plugin_dirs()
        self.assertEqual(d[0], plugins.APP_DIR.parent / "plugins")
        self.assertEqual(d[1].name, "plugins")


from test_speakable import _ServerEnv


class FolderErrorApi(_ServerEnv):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=self.tmp))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.user = self.root / "user"
        self.user.mkdir()
        mock.patch.object(self.server.plugins, "plugin_dirs", return_value=[self.root / "pkg", self.user]).start()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(self.server.plugins, "State", return_value=self.server.plugins.State(self.root / "state.json")).start()

    def test_pre_manifest_errors_hide_marker_from_api(self):
        marker = "private-marker-213"
        for kind in ("link", "manifest"):
            with self.subTest(kind=kind):
                d = self.user / kind
                d.mkdir()
                if kind == "link":
                    (d / "plugin.json").write_text(json.dumps(dict(GOOD, id=kind)))
                    (d / marker).symlink_to(self.root / "outside")
                    expected = "contains a symlink"
                else:
                    (d / "plugin.json").write_text("{" + marker)
                    expected = "plugin.json unreadable"
                rows = self.server.plugins_api()["items"]
                row = next(x for x in rows if x["id"] == kind)
                self.assertEqual(row["error"], expected)
                self.assertNotIn(marker, json.dumps(rows))
                if kind == "link":
                    (d / marker).unlink()
                shutil.rmtree(d)


HAT = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><g transform="translate(1 2) scale(1.5)"><path d="M50 8L88 92Z" fill="acc" stroke="#fff"/><circle cx="5" cy="5" r="2" fill="#abc" opacity=".5"/></g></svg>'


class SettingsFile(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.tmp / "cfg")}).start()
        self.addCleanup(mock.patch.stopall)
        self.d = self.tmp / "plug"
        self.d.mkdir()
        (self.d / "defaults.json").write_text('{"feeds": []}')
        self.p = plugins.config_path("cfg-plug")
        self.p.parent.mkdir(parents=True)

    def test_path_reads_the_environment_at_call_time(self):
        self.assertEqual(self.p, self.tmp / "cfg/nixi-companion/plugin-config/cfg-plug.json")

    def test_missing_gives_the_defaults(self):
        self.assertEqual(plugins.read_config("cfg-plug", self.d), ({"feeds": []}, None))

    def test_good_file_wins(self):
        self.p.write_text('{"a": 1}')
        self.assertEqual(plugins.read_config("cfg-plug", self.d), ({"feeds": [], "a": 1}, None))

    def test_a_file_with_only_some_keys_keeps_the_other_defaults(self):
        (self.d / "defaults.json").write_text('{"feeds": [], "videos": true}')
        self.p.write_text('{"feeds": ["x"]}')
        self.assertEqual(plugins.read_config("cfg-plug", self.d), ({"feeds": ["x"], "videos": True}, None))

    def test_read_user_config_opens_only_the_users_file(self):
        self.assertEqual(plugins.read_user_config("cfg-plug"), (None, None))
        self.p.write_text("[1]")
        self.assertEqual(plugins.read_user_config("cfg-plug"), (None, "settings file unreadable"))
        self.p.write_text('{"a": 1}')
        self.assertEqual(plugins.read_user_config("cfg-plug"), ({"a": 1}, None))
        self.assertEqual(plugins.read_config("cfg-plug", self.d, ({"b": 2}, None)), ({"feeds": [], "b": 2}, None))  # a result in hand is not re-read

    def test_check_videos_key(self):
        (self.d / "run").write_text("x")
        m = lambda i, v: dict(GOOD, id=i, stage={"phrases": ["zz top"], "argv": ["run"], "videos": v})
        self.assertIsNone(plugins._check(m("news", True), self.d))
        self.assertIsNone(plugins._check(m("other-one", False), self.d))
        self.assertEqual(plugins._check(m("news", 1), self.d), "bad stage videos")
        self.assertEqual(plugins._check(m("other-one", True), self.d), "only the news plugin can search YouTube")

    def test_bad_files_give_the_defaults_and_a_note(self):
        for make in (lambda: self.p.symlink_to(self.d / "defaults.json"), lambda: os.mkfifo(self.p),
                     lambda: self.p.write_text("[1]"), lambda: self.p.write_text('{"a": "' + "x" * 17000 + '"}'), lambda: self.p.write_text("{nope")):
            self.p.unlink(missing_ok=True)
            make()
            self.assertEqual(plugins.read_config("cfg-plug", self.d), ({"feeds": []}, "settings file unreadable"))

    def test_check_config_key(self):
        m = lambda c: dict(GOOD, stage={"phrases": ["zz top"], "argv": ["run"], "config": c})
        (self.d / "run").write_text("x")
        self.assertIsNone(plugins._check(m(True), self.d))
        self.assertIsNone(plugins._check(m(False), self.d))
        self.assertEqual(plugins._check(m(1), self.d), "bad stage config")
        (self.d / "defaults.json").unlink()
        self.assertIn("defaults.json", plugins._check(m(True), self.d))
        (self.d / "defaults.json").write_text("[]")
        self.assertIn("defaults.json", plugins._check(m(True), self.d))

    def test_edit_creates_0600_from_the_defaults_and_keeps_an_existing_file(self):
        self.assertEqual(plugins.edit_config("cfg-plug", self.d), self.p)
        self.assertEqual((self.p.read_text(), self.p.stat().st_mode & 0o777), ('{"feeds": []}', 0o600))
        self.p.write_text('{"mine": 1}')
        plugins.edit_config("cfg-plug", self.d)
        self.assertEqual(self.p.read_text(), '{"mine": 1}')

    def test_edit_refuses_a_planted_symlink(self):
        victim = self.tmp / "victim"
        self.p.symlink_to(victim)
        with self.assertRaises(OSError):
            plugins.edit_config("cfg-plug", self.d)
        self.assertFalse(victim.exists())


class Readings(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.d = Path(self._t.name)
        for n, v in (("PROC_STAT", "stat"), ("PROC_NET", "net")):
            mock.patch.object(plugins, n, str(self.d / v)).start()
        self.addCleanup(mock.patch.stopall)
        plugins._last.clear()
        plugins._generation_details.clear()

    def put(self, busy, idle, rx, tx):
        (self.d / "stat").write_text("cpu %d 0 0 %d 0 0 0 0 0 0\n" % (busy, idle))
        (self.d / "net").write_text("h\nh\n lo: 999 0 0 0 0 0 0 0 999 0\n eth0: %d 0 0 0 0 0 0 0 %d 0\n" % (rx, tx))

    def test_rates_from_two_readings_and_null_after_a_reset(self):
        self.put(0, 0, 1000, 500)
        plugins.prime()
        self.put(25, 75, 3000, 1500)
        cpu, rx, tx = plugins._rates()
        self.assertEqual(cpu, 25.0)
        self.assertTrue(rx > 0 and tx > 0 and rx > tx)
        self.put(1, 1, 10, 10)                                  # counters went back
        plugins._last["t"] -= 2                                 # (a reading under 1 s old is shared, #168)
        self.assertEqual(plugins._rates(), (None, None, None))

    def test_unreadable_is_null_not_zero(self):
        plugins.prime()
        self.assertEqual(plugins._rates(), (None, None, None))

    def test_the_two_systemctl_calls_run_in_parallel(self):
        starts = []

        def slow(cmd, **kw):
            if cmd[0] == "systemctl":                        # (nixos-version is read too, once per generation, #168)
                starts.append(time.monotonic())
            time.sleep(1)
            return mock.Mock(returncode=0, stdout="")
        self.put(0, 0, 0, 0)
        plugins.prime()
        t0 = time.monotonic()
        with mock.patch.object(plugins.subprocess, "run", slow):
            r = plugins.system_status()
        self.assertEqual((len(starts), r["failed"], r["failed_system"]), (2, [], []))
        self.assertLess(max(starts) - min(starts), 0.5)
        self.assertLess(time.monotonic() - t0, 2.5)


class Sanitize(unittest.TestCase):
    def bad(self, svg, why=""):
        with self.assertRaises(ValueError, msg=svg) as c:
            plugins.sanitize_svg(svg if isinstance(svg, bytes) else svg.encode())
        self.assertIn(why, str(c.exception))

    def wrap(self, inner, root_attrs='viewBox="0 0 10 10"'):
        return f'<svg xmlns="http://www.w3.org/2000/svg" {root_attrs}>{inner}</svg>'

    def test_a_hat_passes(self):
        n = plugins.sanitize_svg(HAT)
        self.assertEqual([x["tag"] for x in n], ["svg", "g", "path", "circle"])
        self.assertEqual([x["p"] for x in n], [-1, 0, 1, 1])
        self.assertEqual(n[0]["a"], {"viewBox": [0, 0, 100, 100]})

    def test_refused_elements(self):
        for tag in ("script", "use", "image", "text", "foreignObject", "style", "animate", "linearGradient", "filter", "svg"):
            self.bad(self.wrap(f"<{tag}/>"), "element not allowed")
        self.bad(self.wrap('<x:path xmlns:x="urn:evil"/>'), "element not allowed")

    def test_refused_attributes(self):
        for a in ('style="x"', 'href="#a"', 'onload="x()"', 'id="a"', 'class="a"', 'filter="a"', 'xlink:href="a" xmlns:xlink="urn:x"'):
            self.bad(self.wrap(f"<g {a}/>"), "not allowed")
        self.bad(self.wrap('<path d="M0 0" fill="url(#a)"/>'), "bad fill")
        self.bad(self.wrap('<path d="M0 0" fill="red"/>'), "bad fill")
        self.bad(self.wrap('<path d="M0 0" fill="#12"/>'), "bad fill")
        self.bad(self.wrap('<path d="M0 0" fill-opacity="2"/>'), "bad fill-opacity")
        self.bad(self.wrap('<path d="M0 0" stroke-linecap="x"/>'), "bad stroke-linecap")
        self.bad(self.wrap('<rect x="1e3" y="0" width="1" height="1"/>'), "bad number")
        self.bad(self.wrap('<circle cx="0" cy="0" r="1" d="M0 0"/>'), "not allowed")

    def test_transform_numeric_translate_scale_rotate_only(self):
        for t in ("skewX(3)", "matrix(1 0 0 1 0 0)", "translate(url(#a))", "rotate(1 2)", "scale(1 2 3)", "translate()", "translate(1) foo"):
            self.bad(self.wrap(f'<g transform="{t}"/>'), "bad transform")
        plugins.sanitize_svg(self.wrap('<g transform="translate(1,2) rotate(30 5 5) scale(2)"/>').encode())

    def test_dangerous_prologue(self):
        self.bad(b'<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg"/>', "DOCTYPE")
        self.bad(b'<!doctype svg><svg/>', "DOCTYPE")
        self.bad(b'<!DOCTYPE svg [<!ENTITY a "b">]><svg/>', "DOCTYPE")
        self.bad(b'<?xml version="1.0"?><svg/>', "<?")
        self.bad(b'<svg/><?pi x?>', "<?")
        self.bad("<svg/>".encode("utf-16"), "UTF-8")
        self.bad(b"<svg", "not valid")

    def test_limits(self):
        self.bad(b"<svg>" + b" " * 17000 + b"</svg>", "16 KB")
        self.bad(self.wrap("<g/>" * 200), "200 elements")   # root + 200 = 201
        plugins.sanitize_svg(self.wrap("<g/>" * 198).encode())
        deep = "<g>" * 7 + "</g>" * 7                      # root + 7 = depth 8
        plugins.sanitize_svg(self.wrap(deep).encode())
        self.bad(self.wrap("<g>" + deep + "</g>"), "deeper than 8")
        self.bad(self.wrap(f'<path d="M0 0{" L1 1" * 800}"/>'), "too long")
        self.bad(self.wrap('<path d="M0 1001"/>'), "±1000")
        self.bad(self.wrap('<path d="M0 -1001.5"/>'), "±1000")
        self.bad(self.wrap('<circle cx="1001" cy="0" r="1"/>'), "bad number")
        self.bad(self.wrap('<path d="M0 0 alert(1)"/>'), "path data")
        self.bad(self.wrap('<polygon points="0,0 1001,5"/>'), "±1000")
        self.bad("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'>text</svg>", "text not allowed")

    def test_attribute_values_are_capped_before_any_regex(self):
        import time
        hostile = ("translate(" + "1 " * 7000, "1" * 15000, "#" + "a" * 15000, "1." * 7000, " " * 15000 + "x")
        for attr in ("transform", "fill", "stroke-width", "opacity", "stroke"):
            for v in hostile:
                t = time.perf_counter()
                self.bad(self.wrap(f'<path d="M0 0" {attr}="{v}"/>'), "")
                self.assertLess(time.perf_counter() - t, 0.1, (attr, v[:20]))
        t = time.perf_counter()
        self.bad(self.wrap('<path d="' + "1." * 7000 + '"/>'), "")
        self.assertLess(time.perf_counter() - t, 0.1)
        self.bad(self.wrap('<path d="M0 0" fill="acc\n"/>'), "bad fill")           # fullmatch: no trailing newline

    def test_viewbox_is_four_numbers_at_least_one_wide(self):
        n = plugins.sanitize_svg(self.wrap("<g/>", 'viewBox="-5 -5 40.5 20"').encode())
        self.assertEqual(n[0]["a"]["viewBox"], [-5, -5, 40.5, 20])
        for vb in ("0 0 10", "0 0 0.5 10", "0 0 10 0", "0 0 1 1 1", "a b c d"):
            self.bad(self.wrap("<g/>", f'viewBox="{vb}"'), "viewBox")
        n = plugins.sanitize_svg(b'<svg xmlns="http://www.w3.org/2000/svg"><g/></svg>')    # none: a default
        self.assertEqual(n[0]["a"]["viewBox"], [0, 0, 100, 100])

    def test_scales_are_bounded_and_multiply(self):
        plugins.sanitize_svg(self.wrap('<g transform="scale(10)"/>').encode())
        plugins.sanitize_svg(self.wrap('<g transform="scale(2 3)"><g transform="scale(3)"/></g>').encode())
        for t in ("scale(10.1)", "scale(0)", "scale(0.001)", "scale(-1)", "scale(1 11)"):
            self.bad(self.wrap(f'<g transform="{t}"/>'), "scale must be")
        self.bad(self.wrap('<g transform="scale(4)"><g transform="scale(4)"/></g>'), "multiply")

    def test_the_example_hat(self):
        d = Path(__file__).resolve().parent.parent / "plugins/examples/party-hat-plus"
        plugins.sanitize_svg((d / "prop.svg").read_bytes())
        m = json.loads((d / "plugin.json").read_text())
        self.assertIsNone(plugins._check(m, d))


class Cli(unittest.TestCase):
    def run_check(self, d):
        import subprocess
        return subprocess.run([sys.executable, str(plugins.APP_DIR / "plugins.py"), "--check", str(d)], capture_output=True, text=True)

    def test_check(self):
        root = plugins.APP_DIR.parent
        good = self.run_check(root / "plugins/examples/party-hat-plus")
        self.assertEqual((good.returncode, good.stdout.strip()), (0, "ok"))
        bad = self.run_check(root / "tests/fixtures/plugins/broken")
        self.assertEqual(bad.returncode, 1)
        self.assertIn("unknown key: surprise", bad.stderr)


if __name__ == "__main__":
    unittest.main()
