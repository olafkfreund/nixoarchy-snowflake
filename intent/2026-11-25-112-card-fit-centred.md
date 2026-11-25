---
status: draft
issue: 112
author: olafkfreund
---

# Intent: cards fit beside Nixi wherever he stands

## Problem

#109 made answer cards (the stage, `#stg`) follow the terminal's text size
by zooming the whole companion page. To keep the card inside the monitor,
`size.zooms()` (`app/size.py:46`) caps the page zoom at
`min(mon_w / 750, mon_h / 460)`.

That cap only works when Nixi stands near a monitor edge. It assumes the
whole width beside Nixi is on one side. `stagePlace()`
(`app/static/index.html:3323`) puts an open card on whichever side of Nixi's
340 px strip has 400 CSS px free. If neither side has 400, it uses the
larger side anyway, and the card runs off the window.

Example (Codex review on #111): a 1280×720 monitor, Nixi in the middle,
Card text 200 %. The page zoom comes out at about 1.565, which leaves about
239 CSS px on each side of the strip. The card needs 400, so about 161 px
of it, and possibly its buttons, is off screen and cannot be reached.

The zoom is already recomputed when Nixi is dropped, docked or moved to
another monitor (`window.py` `_apply_zoom`, called at `:585`, `:771` and
`:1174`), but the cap never looks at where on the monitor he is.

## Proposed outcome

- An open card is always fully inside the monitor, with its buttons
  reachable, wherever Nixi stands, including dead centre on a small
  monitor at the highest Card text setting.
- When there is not enough room for the card at the requested text size,
  the text gets as large as still fits, and no larger. Today that rule
  applies only when Nixi is near an edge.
- Nothing changes on a monitor where the card already fits. The text size
  stays exactly what #109 gives today.
- Moving Nixi across a monitor updates the fit when he is dropped, not
  while he is being dragged.

## Affected users and systems

- `app/size.py` (`zooms`) and `app/window.py` (`_apply_zoom`,
  `_push_zoom`): the zoom cap and what it is given.
- `app/static/index.html` (`stagePlace`), only if the side rule has to
  agree with the new cap.
- Tests: `tests/test_shared_size.py` and the stage fit tests
  (`tests/stages_fit.mjs`, `tests/test_stages_fit.py`).
- Hosts: p620 and razer, through the usual `nixi-companion` bump. razer's
  laptop screen is the most likely to hit this.

## Constraints

- The #109 decisions stay: the card follows the terminal size and Card
  text, and Nixi's own size does not change it. This only changes the cap.
- No zoom change while dragging. A zoom change resizes the window, which
  would fight the drag.
- Tests must not touch the live config: new test servers use `nixi_env`.
- Test builds on the desktop go through `systemd-run` with
  `RemainAfterExit`. No GPU Chrome previews; use headless Chromium with
  `--disable-gpu`.
- No p510 build or deploy without the owner's OK.

## Open questions

1. When neither side has room even at the smallest allowed zoom, should
   the card move off Nixi's side (for example over him), or keep its side
   and scroll as #109 allows? The proposed default is to keep the side and
   scroll.
2. Should the closed tab (`need` of 160 px) also count, or only the open
   card (400 px)? The proposed default is the open card only, since the
   tab already fits in every case found so far.
