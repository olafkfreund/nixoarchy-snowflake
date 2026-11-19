import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from termfont import term_px  # noqa: E402


class TermFont(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.home = Path(self.d.name)

    def put(self, rel, text):
        p = self.home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def px(self, **env):
        return term_px(env, self.home)

    def test_kitty(self):
        self.put("kitty/kitty.conf", "# font_size 30\nfont_size 9\nfont_size 12\n")
        self.assertAlmostEqual(self.px(TERMINAL="kitty"), 16)

    def test_kitty_tab_and_spaces(self):
        self.put("kitty/kitty.conf", "font_size\t9\nfont_size     12\nfont_size_extra 30\n")
        self.assertAlmostEqual(self.px(TERMINAL="kitty"), 16)

    def test_ghostty(self):
        self.put("ghostty/config", "font-size = 15\n")
        self.assertAlmostEqual(self.px(TERMINAL="ghostty"), 20)

    def test_alacritty(self):
        self.put("alacritty/alacritty.toml", "[font]\nsize = 12.0\n")
        self.assertAlmostEqual(self.px(TERMINAL="alacritty"), 16)

    def test_alacritty_bool(self):
        self.put("alacritty/alacritty.toml", "[font]\nsize = true\n")
        self.assertIsNone(self.px(TERMINAL="alacritty"))

    def test_foot_before_section_repeated_and_comma_list(self):
        self.put("foot/foot.ini", "font=mono:size=6\nfont=mono:size=9, other:size=40\n[colors]\nfont=x:size=30\n")
        self.assertAlmostEqual(self.px(TERMINAL="foot"), 12)

    def test_foot_pixelsize_and_main_section(self):
        self.put("foot/foot.ini", "[main]\nfont=mono:pixelsize=18\n")
        self.assertAlmostEqual(self.px(TERMINAL="foot"), 18)

    def test_terminal_variants(self):
        self.put("foot/foot.ini", "font=m:size=12\n")
        for t in ("footclient", "/usr/bin/foot", "/run/current-system/sw/bin/footclient"):
            self.assertAlmostEqual(self.px(TERMINAL=t), 16, msg=t)

    def test_terminal_empty_or_xdg_exec_falls_to_list(self):
        self.put("kitty/kitty.conf", "font_size 12\n")
        self.put("xdg-terminals.list", "kitty.desktop\n")
        self.assertAlmostEqual(self.px(TERMINAL=""), 16)
        self.assertAlmostEqual(self.px(TERMINAL="xdg-terminal-exec"), 16)

    def test_unknown_terminal_does_not_fall_through(self):
        self.put("kitty/kitty.conf", "font_size 12\n")
        self.put("xdg-terminals.list", "kitty.desktop\n")
        self.assertIsNone(self.px(TERMINAL="xterm"))

    def test_desktop_list(self):
        self.put("kitty/kitty.conf", "font_size 12\n")
        self.put("foot/foot.ini", "font=m:size=6\n")
        self.put("hyprland-xdg-terminals.list", "# c\n\n  kitty.desktop:new-window\nfoot.desktop\n")
        self.put("xdg-terminals.list", "foot.desktop\n")
        self.assertAlmostEqual(self.px(XDG_CURRENT_DESKTOP="Hyprland:wlroots"), 16)

    def test_fallback_list(self):
        self.put("foot/foot.ini", "font=m:size=12\n")
        self.put("xdg-terminals.list", "footclient.desktop\n")
        self.assertAlmostEqual(self.px(XDG_CURRENT_DESKTOP="Hyprland"), 16)

    def test_desktop_ids(self):
        for ident, rel, text in (("Alacritty.desktop", "alacritty/alacritty.toml", "[font]\nsize=12\n"),
                                 ("com.mitchellh.ghostty.desktop", "ghostty/config", "font-size=12\n"),
                                 ("kitty.desktop", "kitty/kitty.conf", "font_size 12\n"),
                                 ("foot.desktop", "foot/foot.ini", "font=m:size=12\n")):
            self.put(rel, text)
            self.put("xdg-terminals.list", ident + "\n")
            self.assertAlmostEqual(self.px(), 16, msg=ident)

    def test_none_cases(self):
        self.assertIsNone(self.px(TERMINAL="kitty"))                      # missing
        self.assertIsNone(self.px())                                      # nothing selected
        self.put("kitty/kitty.conf", "font_size big\n")
        self.assertIsNone(self.px(TERMINAL="kitty"))                      # garbled
        self.put("kitty/kitty.conf", "font_size nan\n")
        self.assertIsNone(self.px(TERMINAL="kitty"))                      # non-finite
        self.put("kitty/kitty.conf", "font_size 2\n")
        self.assertIsNone(self.px(TERMINAL="kitty"))                      # 2 pt
        self.put("foot/foot.ini", "font=m:pixelsize=200\n")
        self.assertIsNone(self.px(TERMINAL="foot"))                       # 200 px


if __name__ == "__main__":
    unittest.main()
