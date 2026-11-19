---
status: draft
issue: 109
author: olafkfreund
---

# Intent: stage cards readable at the shell's text size

## Problem

Answer stages (`#stg` in `app/static/index.html:207`), such as the News
card, are drawn inside the companion page. WebKit zooms that whole page by
Nixi's size setting (`set_zoom_level`, `app/window.py:402`), which defaults
to 0.75 (`window_size`, `app/window.py:132`; `app/size.py`). The card's
CSS sizes are 12-15 px (headlines 14 px, `#stg .tt` at `:231`; source line
12 px, `#stg .src` at `:363`). On screen that is about 9-10.5 px.

The user's terminals are set to 12 pt (ghostty, alacritty, kitty, foot),
about 16 px. Next to the shell the card is hard to read (screenshot in
#109). The only way to enlarge it today is Nixi's size setting, which
also enlarges Nixi himself, and it tops out at 1.25.

## Proposed outcome

- A stage card's body text shows at about the size of the user's terminal
  text, on each monitor, at Nixi's default size.
- Nixi himself and his other panels (settings, chat bubble) keep their
  current size.
- The window still fits the bigger card: nothing clipped. The card stays
  on the side of Nixi that has room, as it does now (`stagePlace`, `:3091`).
- When no terminal font can be read, the card falls back to a sensible
  default, larger than today.

## Affected users and systems

- `app/static/index.html`: stage CSS, `stagePlace`, `stgSize` and
  `sizeWindow` (`:3088`, `:4715`).
- `app/window.py`: the zoom level and window size the page asks for, and
  the click-through region around the card.
- `app/server.py` (or a small helper) if the terminal font and the monitor
  scale are read there.
- Every host running the companion; all stage kinds (news, board,
  notebook, map, sky, desk, term, press, phone).

## Constraints

- Must not change Nixi's size or the size setting's meaning
  (`app/size.py`, 0.5-1.25).
- Must keep the card inside the monitor's work area, including on small
  or HiDPI (scaled) monitors.
- Must not read files outside the user's own config. A config it cannot
  parse means the fallback, never a crash.
- Tests must not touch the live config (`tests/nixi_env.py`; memory:
  tests must not import server under the real HOME).
- Hyprland must not be disrupted during testing: test builds go through
  `systemd-run` with `RemainAfterExit` (memory: test builds on the
  desktop).

## Open questions

1. Which terminal is "the shell"? All four are set to 12 pt today.
   Proposal: read the one `$TERMINAL` (or the Omarchy default) names, and
   fall back to the first one found.
2. Should the card also get a manual override (Settings → "Card text
   size"), or is the automatic size enough for now? Proposal: automatic
   only; an override is a later issue if needed.
3. Should Nixi's message bubble (`#him`, 14.5 px) follow the same size?
   Proposal: no, stage cards only, as asked.
