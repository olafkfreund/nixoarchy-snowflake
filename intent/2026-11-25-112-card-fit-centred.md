---
status: draft
issue: 112
author: olafkfreund
---

# Intent: cards fit beside Nixi wherever he stands

## Problem

#109 made answer cards (the stage, `#stg`) follow the terminal's text size
by zooming the whole companion page. To keep things inside the monitor,
`size.zooms()` (`app/size.py:45`) caps the page zoom at
`min(mon_w / 750, mon_h / 460)` (`:48`), and floors it at Nixi's own size
setting (`max(..., z)`, `:49`; `z` is 0.5-1.25).

The cap ignores where Nixi stands on the monitor. `stagePlace()`
(`app/static/index.html:3323`) puts an open card on whichever side of
Nixi's 340 CSS px strip has 400 CSS px free. If neither side has 400, it
uses the larger side anyway, and the card runs off the window. Near an edge
the whole spare width is on one side, so the card fits. In the middle the
spare width is split in two, and on a small monitor neither half is enough.
A wide monitor can still fit the card in the middle.

Example (Codex review on #111): a 1280×720 monitor, a 16 px terminal font,
Card text 200 %, and Nixi in the middle. The requested zoom is 32/14 ≈ 2.29,
the cap makes it 720/460 ≈ 1.565, and that leaves about 239 CSS px on each
side of the strip. The card needs 400, so about 161 CSS px of it, and
possibly its buttons, is off screen and cannot be reached.

Nixi's size floor makes it worse. At size 1.25 the page zoom cannot drop
below 1.25. That leaves (1280/1.25 − 340)/2 ≈ 342 CSS px each side in the
middle of a 1280 px monitor, still short of 400. So lowering the cap alone
cannot fix every case.

The zoom is recomputed at startup (`app/window.py:460`), after a move in
window (X11) mode (`_save_xpos`, `:585`, after a 700 ms pause), on a move to
another monitor (`go_monitor`, `:771`) and when a drag ends (`:1174`). It is
not recomputed when Nixi docks or undocks (`set_bar`), when he steps aside
(`aside_on`/`aside_off`), or after a layer-mode move (`_save_pos`). In the
drag-to-dock case, `:1174` runs before the dock glide ends, so it sees the
drop point, not the docked one. Cards are hidden while he is docked or
hovering (`stageVisSync`, `index.html:3322`).

## Proposed outcome

- In both layer and window mode, an open answer card is fully inside the
  monitor horizontally, with every button reachable, after Nixi is dropped,
  sent to another monitor, undocked or stepped aside.
- When there is not enough room at the requested text size, the text gets as
  large as still fits beside Nixi, and no larger.
- At a given position and monitor where the card already fits today,
  nothing changes: the text size is exactly what #109 gives.
- The zoom does not change while Nixi is being dragged. It settles once he
  is dropped and, when docking, once the dock glide ends.
- When even the smallest allowed zoom cannot fit the card beside him (Nixi's
  own size is large and he stands in the middle of a small monitor), the
  card still stays fully on the monitor. How it does so is open question 1.

## Affected users and systems

- `app/size.py` (`zooms`): the cap and the inputs it gets.
- `app/window.py`: `_apply_zoom` and `_push_zoom` (`:478`, `:496`); the
  paths that move Nixi without recomputing (`set_bar`, `_save_pos`,
  `aside_on`/`aside_off`, the drag-to-dock order at `:1169-1174`);
  `set_wide` (`:667`) and the strip offset (`mx + wide_shift`).
- `app/room.py` (`split_room`): how the widened window shares the room left
  and right of Nixi.
- `app/static/index.html`: `stagePlace` (`:3323`), `stgSize`, `sizeWindow`,
  `fit()` and `nixiLayout` (`:4999`, which also refreshes the click-through
  region).
- Tests: `tests/test_shared_size.py` and the stage fit tests
  (`tests/stages_fit.mjs`, `tests/test_stages_fit.py`).
- Hosts: every host running the companion, through the usual
  `nixi-companion` bump. razer's laptop screen is the most likely to hit
  this. p510 only with the owner's OK.

## Constraints

- The #109 decisions stay: card text follows the terminal size and Card
  text, and Nixi's size setting does not change his on-screen size. Only
  the cap changes, plus whatever open question 1 decides.
- Nixi stays where he was dropped when the zoom changes. The window may
  grow or shrink around him, but he must not jump.
- The click-through region stays correct after a zoom change.
- Tests must not touch the live config: new test servers use `nixi_env`.
- Test builds on the desktop go through `systemd-run` with
  `RemainAfterExit`. No GPU Chrome previews; use headless Chromium with
  `--disable-gpu`.

## Open questions

1. When the card cannot fit beside Nixi even at the smallest zoom his size
   allows, what gives? (a) The card may overlap Nixi. (b) The cap may go
   below Nixi's size, so the text gets smaller than his size setting would
   allow. (c) The card keeps its side and scrolls, as #109 allows, but that
   does not fix horizontal overflow, so it fails the outcome above.
   Proposed: (a), the card slides over Nixi just far enough to fit.
2. The zoom is page-wide, so the cap also sizes the bubble, the collapsed
   tab, other cards and panels. Should the position-aware cap apply always,
   or only while an answer card is open? "Always" keeps text steady but
   makes all text smaller in the middle of a small monitor even with no
   card open. "Only while open" means the text size jumps when a card opens
   and closes. Proposed: always, because steady text is easier to read.
3. Scope: is horizontal fit of the answer card enough for this issue, with
   vertical fit and the other cards and panels (`#mailPop`, `#code`, `.pn`
   panels) left as they are today? Proposed: yes; they keep #109's
   behaviour, and anything still broken gets its own issue.
