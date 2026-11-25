---
status: draft
issue: 112
intent: intent/2026-11-25-112-card-fit-centred.md
---

# Spec: cards fit beside Nixi wherever he stands

## Design

Three parts: a position term in the zoom cap, the right position to feed
it with the places that recompute it, and a slide-over for when no allowed
zoom can fit the card.

### 1. The cap learns where Nixi stands (`app/size.py`)

`zooms(size, card_text, term_px, mon_w, mon_h)` gains one optional input:
`x0`, the left edge of Nixi's 340 CSS px strip relative to the monitor's
left edge, in logical px. `None` gives today's result.

The cap copies `stagePlace()`'s own rule (`index.html:3324`): an open card
needs 400 CSS px beside the strip on the side it uses. The strip's left
edge is the point that stays put when the zoom changes: `set_wide` places
the window from `base = mx + wide_shift` (`window.py:684`). So at page zoom
`p`:

- right card fits when `x0 + (340 + 400)·p ≤ mon_w`, so `p ≤ (mon_w − x0) / 740`
- left card fits when `x0 ≥ 400·p`, so `p ≤ x0 / 400`

```python
fit = min(mon_w / 750, mon_h / 460)                       # today's cap, kept as an outer bound
if x0 is not None:
    fit = min(fit, max((mon_w - x0) / 740, x0 / 400))     # the card fits on one side or the other
page = page_zoom(max(min(target / 14, fit), z))           # the floor at Nixi's size stays (Decision 1)
```

Why this leaves fitting positions alone: the new term is exactly
`stagePlace`'s test solved for `p`. So it binds only where `stagePlace`
would find no side with 400 CSS px, which is where the card runs off today.

Why the outer `mon_w / 750` must stay: in layer mode, a zoom that grows the
strip past the right edge makes `screens.clamp_on` (`screens.py:32`) pull it
left, which changes `x0` after the cap was computed. With `p ≤ mon_w / 750`,
the clamped strip leaves `mon_w − 340·p ≥ 410·p` on its left, so the left
card still fits. Against the right edge, `x0 / 400 ≥ mon_w / 750` holds
whenever `p_old ≤ mon_w / 729`, which the outer bound guarantees. So the
term never lowers the zoom at either edge.

The 1280×720 example (16 px terminal, Card text 200 %, `x0 = 640 − 170·1.565
≈ 374`): `max(906/740, 374/400) ≈ 1.224`, down from 1.565. The right card
then ends at `374 + 740·1.224 ≈ 1280`. The text gets smaller only by what is
needed, and Nixi does not move.

### 2. The spot the cap uses, and when it is recomputed (`app/window.py`)

One helper returns `x0` for `_apply_zoom` and `_push_zoom`, from Nixi's
**home spot**: the place where an open card would show.

- normally: his current strip, `mx + wide_shift`, minus the monitor's `g.x`
  in window mode (layer margins are already monitor-relative);
- docked (`self.bar`): `bar_home`, where he returns on undock (`:1084`);
- hovering (`self.hover`): `self.home` (`:1252`), where he glides back;
- stepped aside (`self.aside`): `aside["home"]` (`:822`).

Cards are hidden while docked, hovering or aside (`stageVisSync`,
`index.html:3322`). Using the home spot means docking, hovering and stepping
aside never change the zoom. So drag-to-dock is safe: `:1174` sees
`self.bar` set, uses `bar_home` (the drop point, `:1084`), and finds the
zoom it already has. Nothing calls `set_bar(..., glide=False)` mid-glide.
Undock, hover exit and aside return go back to that same spot, so the zoom
is already right when he lands.

New recompute points:

- `_save_pos` (layer mode) calls `_apply_zoom` at its end, as `_save_xpos`
  does (`:585`). This covers a layer-mode move and the delayed saves after
  undock (`:1129`, which already skips while dragging) and after the aside
  return (`:867`). The aside save before its glide (`:826`) reads
  `aside["home"]`, which is where he is, so it changes nothing. The layer
  drag itself never calls `_save_pos` mid-drag. `drag_by` only places him,
  and `_drag_finished` recomputes at release.
- `_save_xpos` (window mode) checks the mouse button first. If button 1 is
  still held, it re-arms its 700 ms timer and returns. This stops a pause
  mid-drag from resizing the window under the pointer. The check is the one
  the X11 release poll already uses (`:1002-1006`), moved into a small
  helper that both call.

`_save_xpos` and `_save_pos` write the position before `_apply_zoom` runs,
and the zoom change does not move the strip's left edge, so the saved spot
stays right. Startup reads the saved `x0` before the first `_apply_zoom`
(`:460`), and `x0` does not depend on the zoom, so a restart gives the same
cap.

### 3. The card slides over Nixi when nothing fits (`app/static/index.html`)

The floor at Nixi's size stays, so with a large size setting in the middle
of a small monitor the card can still lack room on both sides (Decision 1).

`stagePlace()` keeps its side choice. It now measures the room in the
body's own units. The body's left margin is outside its scale transform
(`fit()`, `:4994-4996`), so the right room is
`(innerWidth − layoutX) / fitK − 340`, not `innerWidth / fitK − layoutX −
340` as today. The left room is `layoutX / fitK`. For an open card it sets a
CSS variable on `#stg`:

```
--stgIn = clamp(0, 10 + stgEl.offsetWidth − room, 350 + otherRoom)   // CSS px
```

It uses the card's rendered width: 390, or 340 for News (`#stg.press`,
`:311`). The stage CSS uses the variable:

```css
#stg   { left: calc(350px - var(--stgIn, 0px)) }
#stg.l { left: calc(-400px + var(--stgIn, 0px)) }
```

The card slides inward over the strip just far enough to end at the window
edge. `stgSize(800)` already asks `split_room` for room on both sides, so
the window reaches the monitor on the short side. The card's z-index (7)
draws it above Nixi.

- `--stgIn` is reset to `0px` whenever the stage is not open (tab or
  closed). The collapsed tab is never shifted (Decision 3).
- `stagePlace()` also runs from the `resize` listener (`:5000`), before
  `sendRegion`, so a resize that lands after `nixiLayout` cannot leave the
  shift stale.
- `sendRegion` measures the card's rectangle, so the click-through region
  follows it.
- The props anchored to Nixi (`#chalk`, `#pop`, `#wtc`, `:453-463`) keep
  their places. In the slide-over case the card may cover them. Accepted
  under Decision 1.

With room to spare, `--stgIn` is 0 and the layout is exactly today's.

## Alternatives rejected

- **Keep Nixi's ball centre still on zoom changes, and cap by
  `max(cx, mon_w − cx) / 570`.** This was the first draft. Both reviews
  found it moved Nixi on startup (the first zoom is computed before the
  saved spot loads), could push a window-mode strip off its monitor, and
  stored a pre-shift spot. The strip's left edge already stays still, so
  capping by it needs no new movement at all.
- **`cx = None` (today's cap) while docked or hovering.** A changed zoom at
  the end of a drag-to-dock calls `set_bar(..., glide=False)` and snaps the
  glide. The home spot avoids any change.
- **Guarding `_apply_zoom` on `dragging`/`pmoving`.** Window-mode drags set
  neither flag, and the guard could swallow the only recompute after a
  drop. Checking the button in `_save_xpos` covers the one path that fires
  mid-drag.
- **Applying the position term only while a card is open.** Rejected by
  Decision 2.
- **Dropping below Nixi's size, or scrolling the card sideways.** Rejected
  by Decision 1.

## Risks

- **A zoom change after a drop.** On a small monitor at a high Card text,
  dropping Nixi in the middle shrinks the text a moment after the drop.
  Moving him to an edge grows it back. That is the outcome, and razer's
  laptop screen will show it.
- **Window mode does not clamp.** `set_wide` clamps only in layer mode
  (`:691`). A zoom growth near the right edge in window mode can push the
  strip off the monitor. That is true today. The cap is only ever lowered
  by the new term, so this change does not make it worse.
- **Monitor seams in window mode.** `_apply_zoom` picks the monitor under
  the strip's middle, and `set_wide` under its top-left. They can differ on
  a seam, which is true today. `x0` is computed from the monitor
  `_apply_zoom` picks.
- **Tiny monitors.** With Nixi's size above `mon_w / 750` (only below about
  940 px wide), the outer bound cannot hold, so the edge argument does not
  apply. The slide-over still keeps the card on screen.
- **The slide-over hides part of Nixi and his props.** Only when the size
  floor leaves no room. Accepted by Decision 1.

## Verification

- **Unit, `size.zooms` (`tests/test_window_room.py`, next to
  `test_card_zoom`), each with a concrete expected value:**
  - `x0=None`, and `x0` against either edge of a 1280×720 monitor: today's
    1.565;
  - 1280×720, term 16, Card text 2.0, `x0=374`: about 1.224;
  - 1280×720 with `x0=100`, where the right card already fits
    (`1180/740 ≈ 1.595 ≥ 1.565`): 1.565, unchanged from today;
  - Nixi size 1.25 at a centred spot on a 1024 px monitor: 1.25, the floor;
  - 2560×1440, centred, Card text 2.0: the exact value from the formula.
- **Unit, window methods (`window_methods` harness, same file):**
  - the home-spot helper returns the current spot, `bar_home`,
    `self.home` and `aside["home"]` in the four states, in layer and window
    mode (window mode subtracts `g.x`);
  - `_apply_zoom` and `_push_zoom` pass that `x0`;
  - `_save_pos` calls `_apply_zoom`;
  - `_save_xpos` re-arms and returns without saving or zooming while the
    button is held, and saves and zooms once it is released;
  - startup: the saved spot gives the same `x0` whatever the first zoom
    was.
- **Page, `tests/stages_fit.mjs`:**
  - an open standard card, Nixi in the middle, both sides under 400: the
    `#stg` rectangle lies inside the window on both sides, for a right card
    and a left card;
  - the same with `fitK < 1` (a window shorter than 460) after a `resize`;
  - the News card (340 px) gets the shift for its own width;
  - collapsing to the tab resets `--stgIn` and leaves `#stgTab` at its
    usual place;
  - the region sent by `sendRegion` contains the card's buttons;
  - room to spare: `#stg` at `left:350px` (right) and `-400px` (left), as
    today.
- **Regression:** the full suite (`nix develop -c python3 -B -m unittest
  discover -s tests`).
- **On the desktop:** a test build through `systemd-run` with
  `RemainAfterExit` and its own test config. Screenshots come from headless
  Chromium with `--disable-gpu`. On razer at Card text 200 %:
  - drop Nixi in the middle, open News, and check the card and its buttons
    are on screen;
  - drop him at each edge and check the text size matches today's build;
  - dock and undock him, and step-aside with a card, and check the zoom
    does not change during either.
