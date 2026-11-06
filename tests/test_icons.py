import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from unittest import mock

from test_speakable import _ServerEnv

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8ffff3f0005fe02fea75b9bd90000000049454e44ae426082")


class IconsTest(_ServerEnv):
    """#142: the sending app's icon is found locally and served by id only."""

    def setUp(self):
        self.I = self.server.Icons
        self.root = Path(tempfile.mkdtemp(dir=self.tmp))
        self.share, self.home = self.root / "share", self.root / "home"
        (self.share / "applications").mkdir(parents=True)
        self.home.mkdir()
        p = mock.patch.dict(os.environ, {"HOME": str(self.home), "XDG_DATA_DIRS": str(self.share)})
        p.start()
        self.addCleanup(p.stop)
        self.I.built, self.I.cache, self.I.served = 0.0, {}, {}

    def desktop(self, fid, icon, name="", wm="", extra="", kind="Application"):
        (self.share / "applications" / fid).write_text(
            f"[Desktop Entry]\nType={kind}\nName={name}\nIcon={icon}\n" + (f"StartupWMClass={wm}\n" if wm else "") + extra + "[Desktop Action x]\nName=Other\n")

    def test_desktop_for_exact_identity_and_iconless(self):
        self.desktop("org.foo.Bar.desktop", "", "Foo Mail - Inbox", "FooWM")
        self.desktop("org.visualstudio.Code.desktop", "", "Visual Studio Code")
        want = {"id": "org.foo.Bar", "wmclass": "foowm"}
        for app, source in (("org.foo.bar", ""), ("other", "FOOWM"), ("Foo Mail - Inbox", "")):
            self.assertEqual(self.I.desktop_for(app, source), want)
        for app in ("Foo Mail", "code"):
            self.assertIsNone(self.I.desktop_for(app, ""))
        self.assertEqual(self.I.desktop_for("Visual Studio Code", "")["id"], "org.visualstudio.Code")
        self.assertIsNone(self.I.lookup("org.foo.Bar", ""))

    def test_desktop_for_refuses_hidden_non_apps_and_collisions(self):
        for fid, extra in (("hidden", "Hidden=true\n"), ("nodisplay", "NoDisplay=true\n"), ("-refused", "")):
            self.desktop(fid + ".desktop", "", fid, extra=extra)
        self.desktop("link.desktop", "", "Link", kind="Link")
        self.assertIsNone(self.I.desktop_for("hidden", ""))
        self.assertIsNone(self.I.desktop_for("nodisplay", ""))
        self.assertIsNone(self.I.desktop_for("link", ""))
        self.assertIsNone(self.I.desktop_for("-refused", ""))
        self.desktop("one.desktop", "", "Shared")
        self.desktop("two.desktop", "", "Shared")
        self.I.built = 0
        self.assertIsNone(self.I.desktop_for("shared", "one"))
        self.assertEqual(self.I.desktop_for("one", ""), {"id": "one", "wmclass": ""})

    def test_desktop_for_own_id_beats_a_shared_name(self):
        self.desktop("discord.desktop", "d", name="Discord")
        self.desktop("omarchy-Discord.desktop", "d", name="Discord")
        self.assertEqual(self.I.desktop_for("discord", "")["id"], "discord")
        self.desktop("a.desktop", "x", name="Twin")
        self.desktop("b.desktop", "x", name="Twin")
        self.I.built = 0.0
        self.assertIsNone(self.I.desktop_for("twin", ""))

    def test_desktop_for_same_id_in_two_data_dirs_is_one_app(self):
        self.desktop("org.foo.Bar.desktop", "foo", name="Foo", wm="FooWM")
        other = self.root / "other"
        (other / "applications").mkdir(parents=True)
        (other / "applications" / "org.foo.Bar.desktop").write_text((self.share / "applications" / "org.foo.Bar.desktop").read_text())
        hidden = self.root / "hidden"
        (hidden / "applications").mkdir(parents=True)
        (hidden / "applications" / "org.gone.App.desktop").write_text("[Desktop Entry]\nType=Application\nName=Gone\nHidden=true\n")
        (other / "applications" / "org.gone.App.desktop").write_text("[Desktop Entry]\nType=Application\nName=Gone\n")
        with mock.patch.dict(os.environ, {"XDG_DATA_DIRS": f"{hidden}:{self.share}:{other}"}):
            self.I.built = 0.0
            self.assertEqual(self.I.desktop_for("Foo", "")["id"], "org.foo.Bar")
            self.assertIsNone(self.I.desktop_for("Gone", ""))   # (a file hiding an app earlier in the path wins)

    def test_desktop_for_rebuilds_on_expired_miss(self):
        self.assertIsNone(self.I.desktop_for("new", ""))
        self.desktop("New.desktop", "", "New")
        self.assertIsNone(self.I.desktop_for("new", ""))
        self.I.built -= self.I.TTL + 1
        self.assertEqual(self.I.desktop_for("new", "")["id"], "New")

    def theme_icon(self, name, size="64x64", data=PNG, ext=".png"):
        d = self.share / "icons" / "hicolor" / size / "apps"
        d.mkdir(parents=True, exist_ok=True)
        (d / (name + ext)).write_bytes(data)
        return str(d / (name + ext))

    def test_by_file_id_and_wm_class_and_name(self):
        want = self.theme_icon("foo")
        self.desktop("org.foo.Bar.desktop", "foo", name="Foo Mail - Inbox", wm="FooWM")
        for app, src in (("org.foo.bar", ""), ("x", "FooWM"), ("Foo Mail", "y")):
            self.assertEqual(self.I.lookup(app, src), want)

    def test_chrome_web_app_by_name(self):
        want = self.theme_icon("gm")
        self.desktop("chrome-abc-Default.desktop", "gm", name="Gmail - Inbox (3)")
        self.assertEqual(self.I.lookup("Google Chrome", "mail.google.com"), want)

    def test_quick_web_apps_slug(self):
        want = self.theme_icon("qwa")
        self.desktop("io.github.someone.QuickWebApps.mail-google-com-ireb.desktop", "qwa", name="Mail")
        self.assertEqual(self.I.lookup("Brave", "mail.google.com"), want)

    def test_absolute_icon_path_and_pixmaps(self):
        f = self.root / "abs.png"
        f.write_bytes(PNG)
        self.desktop("a.desktop", str(f), name="Abs")
        (self.share / "pixmaps").mkdir()
        (self.share / "pixmaps" / "pm.svg").write_text("<svg/>")
        self.desktop("p.desktop", "pm", name="Pm")
        self.assertEqual(self.I.lookup("abs", ""), str(f))
        self.assertTrue(self.I.lookup("pm", "").endswith("pm.svg"))

    def test_missing_and_refused_files(self):
        self.desktop("a.desktop", "nothere", name="A")
        self.assertIsNone(self.I.lookup("a", ""))
        self.assertIsNone(self.I.lookup("unknown", "none.example"))
        self.theme_icon("big", data=b"0" * (512 * 1024 + 1))
        self.desktop("b.desktop", "big", name="B")
        self.assertIsNone(self.I.lookup("b", ""))
        self.theme_icon("txt", ext=".txt")
        self.desktop("c.desktop", "txt", name="C")
        self.assertIsNone(self.I.lookup("c", ""))
        self.desktop("d.desktop", "../../etc/passwd", name="D")
        self.assertIsNone(self.I.lookup("d", ""))

    def test_misses_are_cached(self):
        self.assertIsNone(self.I.lookup("late", ""))
        self.theme_icon("late")
        self.desktop("late.desktop", "late", name="Late")
        self.assertIsNone(self.I.lookup("late", ""))          # cached miss, index not rebuilt within 10 min

    def serve(self, path):
        httpd = HTTPServer(("127.0.0.1", 0), self.server.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_port}{path}") as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            e.close()
            return e.code, e.headers, b""

    def test_route(self):
        f = self.theme_icon("ok")
        i = self.I.register(f)
        st, h, body = self.serve("/api/icon/" + i)
        self.assertEqual((st, body, h["Content-Type"], h["Cache-Control"]), (200, PNG, "image/png", "max-age=86400"))
        for bad in ("0" * 16, "../../etc/passwd", "ABCDEF0123456789", i + "0", "../" + i):
            self.assertEqual(self.serve("/api/icon/" + bad)[0], 404, bad)
        Path(f).write_bytes(b"0" * (512 * 1024 + 1))             # re-checked at serve time
        self.assertEqual(self.serve("/api/icon/" + i)[0], 404)

    def test_svg_type(self):
        f = self.theme_icon("v", "scalable", b"<svg/>", ".svg")
        h = self.serve("/api/icon/" + self.I.register(f))[1]
        self.assertEqual(h["Content-Type"], "image/svg+xml")
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")              # opened on its own, an SVG can't run script
        self.assertIn("sandbox", h["Content-Security-Policy"])

    def test_row_gets_an_icon_the_route_serves(self):
        self.theme_icon("gm")
        self.desktop("gmail.desktop", "gm", name="Gmail")
        rows = self.server.Inbox.rows(json.dumps([
            {"key": "k1", "app": "Chrome", "source": "x", "category": "chat"},
            {"key": "k2", "app": "Google Chrome", "source": "mail.google.com", "category": "other"},
            {"key": "k3", "app": "zzz", "source": "", "category": "chat"}]))
        self.assertNotIn("icon", rows[0])
        self.assertNotIn("icon", rows[2])
        st, _, body = self.serve("/api/icon/" + rows[1]["icon"])
        self.assertEqual((st, body), (200, PNG))


if __name__ == "__main__":
    unittest.main()
