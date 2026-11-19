---
status: approved
issue: 109
author: olafkfreund
---

# Intent: companion cards readable at the shell's text size

## Problem

Answer stages (`#stg` in `app/static/index.html:207`), such as the News
card, are drawn inside the companion page. WebKit zooms that whole page by
Nixi's size setting (`set_zoom_level`, `app/window.py:402` and live at
`:466`), which defaults to 0.75 (`window_size`, `app/window.py:132`;
`app/size.py`).

The News card is the `press` stage. Its headlines are 14 px
(`#stg.press .prt`, `:325`), the source and age line 11.5 px
(`#stg.press .prm`, `:326`), and the footer 12 px (`#stg .fn`, `:365`).
At 0.75 that is about 10.5 px, 8.6 px and 9 px of logical screen space.
Other stages are similar: most card text is 11-15 CSS px, so 8.25-11.25 px
on screen. `fit()` (`:4717`) can shrink the page further when the window
is smaller than 340x460.

The user's terminals are set to 12 pt (ghostty, alacritty, kitty, foot),
about 16 logical px. Next to the shell the card is hard to read
(screenshot in #109). The only way to enlarge it today is Nixi's size
setting, which also enlarges Nixi himself, and it tops out at 1.25.

## Proposed outcome

- Every card's text (headlines, metadata lines, buttons, inputs; the
  cards are listed under Decisions) shows at about the user's terminal
  text size, measured in logical pixels, and the user can step it up or
  down from the keyboard.
  Monitor scaling is already applied by the compositor, so on a 2x
  monitor the card is not scaled twice; what differs per monitor is the
  space available.
- That size stays the same whatever Nixi's size setting is (0.5-1.25).
  Changing the setting resizes Nixi, not the card's text.
- Nixi himself, his message bubble (`#him`) and his other panels
  (settings, chat) keep their current size. The collapsed stage tab
  (`#stgTab`) is part of the stage and follows the stage's size.
- The window grows to fit the bigger card: nothing is clipped. If a
  monitor is too small for the whole card, readability wins: the card
  keeps its text size and scrolls, and every control stays reachable.
- When no terminal font can be read, the card uses a fixed default that
  is larger than today's (about 16 px body text). A terminal font outside
  a sane range is clamped, so a 6 pt or 30 pt terminal cannot break the
  overlay.

## Affected users and systems

- `app/static/index.html`: stage CSS for every stage class (`board`,
  `map`, `cinema`, `sky`, `desk`, `term`, `press`, `notebook`;
  `:3101`), including the fixed widths of `term` and `press`;
  `stagePlace` (`:3091`, its 400/160 px space check), `stgSize`
  (`:3088`, width only today, called with 800 and 300 at `:3426`,
  `:3438`, `:3443`), `sizeWindow` (`:4715`), `fit()` (`:4717`) and the
  click-through region (`sendRegion`, `:4749`).
- `app/window.py`: zoom (`set_zoom`, `:461`), window growth (`set_wide`,
  `:628`; it uses the monitor geometry at `:646-651`, since layer-shell
  runs with `exclusive_zone -1`) and the input region (`_apply_region`).
- Wherever the terminal font is read (server or a small helper).
- Every host running the companion.

## Constraints

- Must not change Nixi's size or the size setting's meaning
  (`app/size.py`, 0.5-1.25).
- Must keep the card on the monitor (inside the monitor bounds the window
  uses today) on small and scaled monitors.
- Must keep current behavior that works:
  - Clicks land on the visible card and its controls; the transparent
    space around them still passes clicks through.
  - Collapse to the tab, restore and close still work, and closing gives
    the extra window space back.
  - Stages and their props (`#chalk`, `#hat`, `#pop`, `#wtc`) stay hidden
    in docked (bar), hover and calm modes, dimmed while an approval is
    open, and held back while a panel is open, as today
    (`:339`, `:396`, `:3420-3422`). The props keep their size and their
    place next to Nixi.
  - The card picks the side of Nixi that has room, and the music card
    still avoids the stage's side (`:1832`).
  - The text stays readable after Nixi's size changes and after he moves
    to another monitor.
- Reads only the user's terminal configuration (files under `~/.config`,
  including ones Home Manager links into the Nix store). A config it
  cannot read or parse means the fallback, never a crash.
- Tests must not touch the live config (`tests/nixi_env.py`; memory:
  tests must not import server under the real HOME).
- Hyprland must not be disrupted during testing: test builds go through
  `systemd-run` with `RemainAfterExit` (memory: test builds on the
  desktop).

## Decisions (approved 2026-11-19)

1. **Source of the size:** automatic, from the terminal the user
   launches: `$TERMINAL`, else the Omarchy / `xdg-terminal-exec` default,
   else the fixed default. Not "the first config found": an installed
   but unused terminal says nothing about the user's preference. The
   companion runs as a user service, so `$TERMINAL` may be missing from
   its environment; the spec settles where it is read.
2. **Keyboard control: yes.** The user can make card text bigger or
   smaller, and reset it to the automatic size, from the keyboard, the
   way `nixi-companion size up|down|reset` changes Nixi's size today
   (`bin/nixi-companion:153`, bound in `nixos_config`, `docs/GUIDE.md:584`).
   The chosen step persists like the size setting does.
3. **All cards, not only stages.** Every card the companion shows
   follows the card text size: answer stages and their tab (`#stg`,
   `#stgTab`), the approval card (`#appr`), the password box (`#pwbox`),
   the mail pop-up (`#mailPop`), the music card (`#musCard`), the code
   sheet (`#code`), and notification cards (`.ncard`, `:3014`, shown
   inside the bubble). Nixi's plain message bubble text (`#him`), his
   menu and his panels (settings, history; `.pn`) keep their size.
   Each card keeps the window-space request it already makes
   (`cardWant`, `sheetWant`, `popWant`, `stageWant`; `:4714`), scaled.
