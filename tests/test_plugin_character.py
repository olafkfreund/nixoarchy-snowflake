"""#213: a plugin's character is loaded, sent with no-store, and a private one leaves nothing in the logs, Settings or diagnostics."""
import contextlib
import io
import json
import shutil
import tempfile
import threading
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from unittest import mock

from test_speakable import _ServerEnv

DOTS = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-10 -10 20 20"><circle cx="0" cy="0" r="9" fill="#778899"/><circle cx="-3" cy="-2" r="1"/><circle cx="3" cy="-2" r="1"/></svg>'
D_MARK = "M7 7L91919 3"                      # (a distinctive path value to look for)
MARK = "private-marker-213"


class CharEnv(_ServerEnv):
    """A temp plugin folder with a synthetic character (a circle with two dots); plugin_dirs and the state file are patched."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=self.tmp))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.user = self.root / "user"
        self.user.mkdir(mode=0o700)
        s = self.server
        mock.patch.object(s.plugins, "plugin_dirs", return_value=[self.root / "pkg", self.user]).start()
        self.state = s.plugins.State(self.root / "state.json")
        mock.patch.object(s.plugins, "State", return_value=self.state).start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(s.Plug.reload)

    def make(self, pid="dots", private=False, art=DOTS, front=None, prop=None):
        d = self.user / pid
        d.mkdir(mode=0o700)
        c = {"label": "Dots", "template": "round", "fill": "#778899", "back": "back.svg", "front": "front.svg", "fits": ["none", "halo"], "private": private}
        m = {"api": 1, "id": pid, "name": "Dots", "version": "1", "character": c}
        if prop is not None:
            m["prop"] = {"file": "prop.svg", "anchor": "head"}
            (d / "prop.svg").write_text(prop)
        (d / "plugin.json").write_text(json.dumps(m))
        (d / "back.svg").write_text(art)
        (d / "front.svg").write_text(front if front is not None else art)
        for p in d.iterdir():
            p.chmod(0o600)
        self.state.set(pid, True)
        self.server.Plug.reload()
        return d


class PluginCharacterTest(CharEnv):
    def test_loaded_and_sent(self):
        self.make()
        s = self.server
        self.assertTrue(s.Plug.has_character("dots"))
        self.assertFalse(s.Plug.has_character("other"))
        with mock.patch.object(s.eleven, "voices", return_value=[]), mock.patch.object(s.quick, "projects", return_value={}):
            ch = s.state_info()["plugin_characters"]
        self.assertEqual([c["id"] for c in ch], ["dots"])
        self.assertIn("Adds a character (pick it in Look)", s.plugin_caps({"character": {}}))
        self.assertNotIn("Private: keep this folder out of Nix and out of any repo.", s.plugin_caps({"character": {}}))
        self.assertIn("Private: keep this folder out of Nix and out of any repo.", s.plugin_caps({"character": {"private": True}}))

    def test_json_routes_are_no_store(self):
        s = self.server
        for patcher in (mock.patch.object(s.eleven, "voices", return_value=[]), mock.patch.object(s.quick, "projects", return_value={})):
            patcher.start()
            self.addCleanup(patcher.stop)
        httpd = HTTPServer(("127.0.0.1", 0), s.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        for path in ("/api/state", "/api/companion-plugins", "/api/ping"):
            req = urllib.request.Request(f"http://127.0.0.1:{httpd.server_port}{path}", headers={"X-Nixi-Token": s.TOKEN})
            try:
                r = urllib.request.urlopen(req)
            except urllib.error.HTTPError as e:     # (a 404 still goes through _json)
                r = e
            self.assertEqual(r.headers.get("Cache-Control"), "no-store", path)

    def test_private_art_and_names_stay_out_of_logs_settings_and_diagnostics(self):
        s = self.server
        self.make("good", private=True, art=DOTS.replace("</svg>", f'<path d="{D_MARK}"/></svg>'))
        bad = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><{MARK}-tag {MARK}-attr="{D_MARK}"/></svg>'
        self.make("bad", private=True, art=bad)
        self.make("propbad", private=True, prop=bad)            # (a good private character with a bad prop: the prop error is fixed text too)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            s.Plug.reload()
            rows = json.dumps(s.plugins_api())
            with mock.patch.object(s, "claude_bin", return_value=None):
                diag = s.diagnostics()
        log = out.getvalue() + err.getvalue() + ((s.DATA_DIR / "server.log").read_text(errors="replace") if (s.DATA_DIR / "server.log").exists() else "")
        for text in (log, rows, diag):
            self.assertNotIn(D_MARK, text)
            self.assertNotIn(MARK, text)
        self.assertIn(s.plugins.PRIVATE_ART_ERROR, rows)
        self.assertFalse(s.Plug.has_character("bad"))
        self.assertEqual(s.Plug.prop_errors.get("propbad"), s.plugins.PRIVATE_ART_ERROR)


if __name__ == "__main__":
    import unittest
    unittest.main()
