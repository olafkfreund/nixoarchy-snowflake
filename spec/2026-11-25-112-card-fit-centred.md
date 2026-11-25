---
status: approved
issue: 112
intent: intent/2026-11-25-112-card-fit-centred.md
---

# Spec: cards fit beside Nixi wherever he stands

## Design

Four parts:

1. a position term in the zoom cap;
2. one "zoom spot" (monitor plus strip edge) that feeds it, and the
   rules for when that spot updates;
3. computing the zoom before the strip is placed at startup and on a
   monitor move;
4. a slide-over for when no allowed zoom can fit the card.

### 1. The cap learns where Nixi stands (`app/size.py`)

`zooms(size, card_text, term_px, mon_w, mon_h)` gains one optional input:
`x0`, the left edge of Nixi's 340 CSS px strip relative to the monitor's
left edge, in logical px. With `x0` or `mon_w` set to `None`, the result is
exactly today's.

The cap copies `stagePlace()`'s own rule (`index.html:3324`): an open card
needs 400 CSS px beside the strip on the side it uses. The strip's left
edge is the point that stays put when the zoom changes: `set_wide` places
the window from `base = mx + wide_shift` (`window.py:684`). At page zoom
`p`:

- right card fits when `x0 + (340 + 400)·p ≤ mon_w`, so `p ≤ (mon_w − x0) / 740`
- left card fits when `x0 ≥ 400·p`, so `p ≤ x0 / 400`

```python
fit = min(mon_w / 750, mon_h / 460) if mon_w is not None and mon_h is not None else math.inf
if x0 is not None and mon_w is not None:
    fit = min(fit, max((mon_w - x0) / 740, x0 / 400))     # the card fits on one side or the other
page = page_zoom(max(min(target / 14, fit), z))           # the floor at Nixi's size stays (Decision 1)
```

The new term is `stagePlace`'s test solved for `p`. It binds only where
`stagePlace` finds no side with 400 CSS px, which is exactly where the card
runs off today. Elsewhere the zoom is unchanged.

Today's `mon_w / 750` stays as an outer bound. In layer mode, a zoom that
grows the strip past the right edge makes `screens.clamp_on`
(`screens.py:32`) pull it left. With `p ≤ mon_w / 750`, the clamped strip
still leaves `mon_w − 340·p ≥ 410·p` on its left. Against the right edge,
`x0 / 400 ≥ mon_w / 750` holds whenever `p_old ≤ mon_w / 729`, which the
outer bound guarantees. So the term never lowers the zoom at either edge.

The 1280×720 example (16 px terminal, Card text 200 %, `x0 = 374`) gives
`max(906/740, 374/400) ≈ 1.224`, down from 1.565. The right card then ends
at `374 + 740·1.224 ≈ 1280`.

The cap is sized for the standard 390 px card. News (`#stg.press`, 340 px,
`:311`) needs 50 px less on the right, so at a few positions News gets
slightly smaller text than it strictly needs. For example, at `x0 = 180`
the zoom is 1.486 where News alone would fit at 1.565. The native side
does not know which card will open, so one rule for all cards is kept.

### 2. The zoom spot, and when it updates (`app/window.py`)

The cap reads one cached **zoom spot**: the monitor geometry together with
`x0` on that monitor. `_apply_zoom` updates the spot and then computes the
zoom from it. `_push_zoom` sends the zoom and the spot `_apply_zoom` last
used, and does not look them up again (before the first `_apply_zoom` it
falls back to today's lookup). Native and page zoom therefore
always agree, even on a monitor seam.

The spot is refreshed from Nixi's current strip only while he is **free**:
not docked (`self.bar`) and not hovering (`self.hover`, from the moment
hover starts until the glide home lands). Cards are hidden
while docked or hovering (`stageVisSync`, `index.html:3322`). In those
states the spot stays where it was before he docked or started hovering. A
size, text or terminal change still recomputes, from that kept spot.

- Window mode resolves the monitor from Nixi's position (`_mon_at` on the
  ball, as `_apply_zoom` does today) and gets `x0` by subtracting that
  monitor's `g.x`. Layer mode uses `self._geom()` and the margins.
- **Drag-to-dock** keeps the zoom. `:1174` runs with `self.bar` already
  set, so it reuses the pre-drag spot and finds the zoom unchanged. Nothing
  calls `set_bar(..., glide=False)` mid-glide.
- **A monitor move while docked** (`go_monitor`, `:759-767`) sets the
  spot to the destination monitor and the saved spot there (`bar_home`'s
  new `x`), or `x0 = None` when there is none. A drag that docks on a
  different monitor sets it to that monitor with `x0 = None`, so the zoom
  may change there and that dock snaps instead of gliding. That is rare and
  accepted.
- **Undock** recomputes after the glide: `set_bar` already saves at
  `:1129` (skipped while dragging), and `_save_pos` now calls
  `_apply_zoom`, as `_save_xpos` does (`:585`).
- **Hover exit** recomputes when the glide home lands: `_glide_home` runs
  on a worker thread, so each of its three exits queues
  `GLib.idle_add(self._apply_zoom)`. While hovering on another monitor, the
  kept spot pairs the home monitor with its own `x0`, so the two never
  get mixed.
- **Step-aside** counts as free. Cards can show while he is aside, and on
  `mode == "monitor"` he is on another monitor. The spot follows him:
  `go_monitor` recomputes on the destination, the side glide's landing
  (`_parked`, `:842`) calls `_apply_zoom`, and `aside_off` recomputes through
  `_save_pos` when he returns (`:867`). A manual move while aside
  recomputes through `_drag_finished`, like any move.
- **Window-mode drags:** the 700 ms debounce in `_moved` (`:570`) now
  fires a small `_settle_xpos`. It owns the one `save_t` timer: while
  button 1 is held it returns `True` to run again, and it clears `save_t`
  when it finishes. It uses the button check the X11 release poll
  already does (`:1002-1006`, moved into a helper both call). Once the
  button is up, it calls `_save_xpos`. The window-mode branch of the delayed undock save
  (`:1129`) also goes through `_settle_xpos`, because pulling Nixi out of the
  notch is a drag that sets no drag flag. The direct calls in `go_monitor`
  stay as they are. A size or text key pressed in
  the middle of a drag still applies at once. That is rare, and it is
  today's behaviour.

### 3. Zoom before placement (`app/window.py`)

Today the first zoom is computed with no monitor (`:355`). `_load_pos`
then clamps the saved spot using that uncapped size (`:545`), and the
default corner is computed with it too (`:543`, `:557`). `go_monitor`
clamps with the old monitor's size (`:757`, `:767`). Either can move `x0`
before the cap sees it.

New order, in `_load_pos`, `_load_xpos` and `go_monitor`:

1. Resolve the target monitor and the saved spot on it.
2. Compute the zoom from that monitor and the saved `x0`. With no saved
   spot, the default bottom-right corner is computed with `x0 = None` and
   then checked. The corner is 10 px in from the edge, so on a small
   monitor the term can still bind there (600 px wide at zoom 0.8 gives
   0.795). In that case the zoom is recomputed once with the corner's `x0`.
3. **Apply** that zoom before placing: the WebKit zoom level, `self.z`,
   and the base window size (`cur_w`, `cur_h` and the size request). This
   is the part of `_apply_zoom` that runs today when `page != self.z`,
   moved into an `_apply_page(page)` that both call. `_place(...,
   clamp=True)` clamps with `cur_w`/`cur_h` (`:619`), so they must already
   be the destination size, or a saved right-edge spot gets pulled in.
4. Compute the default corner, if needed, and place or clamp the strip as
   today.

`_load_xpos` also checks whether the saved spot's monitor still exists,
using `self._px(W)` (`:552`). It uses the zoom from step 2 for that check,
so a spot saved near a right edge at a small zoom is not thrown away.

The first `_apply_zoom` (`:460`) then finds the zoom already applied. It
refreshes the spot and pushes it. The saved spot is written
before `_apply_zoom` runs, and the zoom does not move the strip's left
edge, so the position on disk stays right.

### 4. The card slides over Nixi when nothing fits (`app/static/index.html`)

The floor at Nixi's size stays, so with a large size setting in the middle
of a small monitor the card can still lack room on both sides (Decision 1).

`stagePlace()` keeps its side choice. It now measures the room in the
body's own units. The body's left margin is outside its scale transform
(`fit()`, `:4994-4996`), so:

- the right room `R` is `(innerWidth − layoutX) / fitK − 340`, not
  `innerWidth / fitK − layoutX − 340` as today;
- the left room `L` is `layoutX / fitK`.

For an open card of rendered width `w` (390, or 340 for News), the shift
`s` slides the card inward:

| Side | Card left today | Smallest `s` that fits | Largest `s` (other edge stays in) |
|---|---|---|---|
| right | `350` | `10 + w − R` | `350 + L` |
| left | `−400` (News too) | `400 − L` | `740 + R − w` |

`s` is clamped to `[0, largest]` and written as `--stgIn` on `#stg`:

```css
#stg   { left: calc(350px - var(--stgIn, 0px)) }
#stg.l { left: calc(-400px + var(--stgIn, 0px)) }
```

- The window already reaches the monitor on the short side, because
  `stgSize(800)` asks `split_room` for room on both sides. The card's
  z-index (7) draws it above Nixi.
- `--stgIn` is reset to `0px` at the top of `stagePlace`, before its early
  return for a closed stage, and also in the close path of `stageHide`
  (`:3671`), which does not call `stagePlace`. It is set only when
  `stgState === 'open'`, so the tab is never shifted (Decision 3).
- `stagePlace` reads `stgEl.offsetWidth`, so borders on some card styles
  (`board`, `notebook`) are counted whatever the box sizing is.
- `stagePlace()` also runs from the `resize` listener (`:5000`), before
  `sendRegion`, so a late resize cannot leave the shift stale.
- `sendRegion` measures the card's rectangle, so the click-through region
  follows it.
- The props anchored to Nixi (`#chalk`, `#pop`, `#wtc`, `:453-463`) keep
  their places. In the slide-over case the card may cover them. Accepted
  under Decision 1.
- If the window is narrower than the card itself (only on a monitor under
  about 490 px wide at Nixi's largest size), no shift can fit it. The shift
  is then chosen so the card starts at the window's left edge, on either
  side, keeping its title and left-hand buttons visible.

With room to spare, `s` is 0 and the layout is exactly today's.

## Alternatives rejected

- **Keep Nixi's ball centre still, and cap by `max(cx, mon_w − cx) /
  570`** (the first draft). It moved Nixi at startup, could push a
  window-mode strip off its monitor, and saved a spot from before the
  shift. The strip's left edge already stays still, so capping by it needs
  no new movement.
- **The home spot (`bar_home`, `self.home`, `aside["home"]`) while docked,
  hovering or aside** (the second draft). `bar_home` is the drop point, so
  drag-to-dock still changed the zoom and snapped the glide. The tuples can
  also carry a stale monitor index in window mode. A cached spot is simpler
  and keeps the monitor with its `x0`.
- **`cx = None` while docked or hovering.** It changes the zoom at the end
  of a drag-to-dock and snaps the glide.
- **Guarding `_apply_zoom` on `dragging`/`pmoving`.** Window-mode drags set
  neither flag, and the guard could swallow the only recompute after a
  drop.
- **A per-card cap (News smaller).** The window does not know which card
  will open.
- **Applying the position term only while a card is open.** Rejected by
  Decision 2.
- **Dropping below Nixi's size, or scrolling the card sideways.** Rejected
  by Decision 1.

## Risks

- **Nixi shrinks toward his left edge.** When the cap lowers the zoom,
  Nixi gets smaller around his strip's left edge, as he already does today
  for the size and Card text keys. In the 1280 example his ball centre
  moves about 58 px left. The intent's constraint says he "must not jump".
  This spec reads that as "the edge you dropped him by stays put". Keeping
  the centre still instead was the first draft, and it is rejected above.
- **A zoom change a moment after a drop.** On a small monitor at a high
  Card text, dropping Nixi in the middle shrinks the text after the drop.
  Moving him to an edge grows it back. This is the outcome, and razer's
  laptop screen will show it.
- **Window mode does not clamp** (`set_wide`, `:691`). A zoom growth near
  the right edge can push the strip off the monitor. That is true today,
  and the new term only ever lowers the cap.
- **A drag from a larger monitor to a smaller one** is clamped with the
  source size before the zoom is recomputed (`_drag_finished`), as today.
  The cap then sees the clamped spot. The card still fits there, but the
  text can be smaller than that spot strictly needs until Nixi is moved
  again. Fixing the drag clamp is out of scope.
- **Tiny monitors.** With Nixi's size above `mon_w / 750` (only below about
  940 px wide), the outer bound cannot hold. The slide-over then keeps the
  card on screen, unless the window is narrower than the card.
- **The slide-over hides part of Nixi and his props.** Only when the size
  floor leaves no room. Accepted by Decision 1.

## Verification

**Unit, `size.zooms`** (`tests/test_window_room.py`, beside
`test_card_zoom`; 16 px terminal and Card text 2.0 unless noted):

| Case | Expected |
|---|---|
| `x0=None`; `mon_w=None` | today's values |
| 1280×720, `x0=0`, and `x0` at the right edge for zoom 1.565 | 1.565 |
| 1280×720, `x0=374` | ≈ 1.224 |
| 1280×720, `x0=100` (the right card fits: `1180/740 ≈ 1.595`) | 1.565 |
| 2560×1440, `x0=900` | 2.25 |
| 1024×768, Nixi size 1.25, `x0=320` | 1.25 (the floor) |

**Unit, window methods** (the `window_methods` harness, same file):

- The zoom spot:
  - refreshes from the current strip when free, in layer and window mode;
  - window mode subtracts the monitor's `g.x`;
  - kept while docked or hovering;
  - `_push_zoom` sends the cached spot's values.
- Drag-to-dock: start at `x0=374` and drop at `x0=740`. `_drag_finished`
  makes no zoom change and no `set_bar(..., glide=False)` call.
- `_save_pos` calls `_apply_zoom`. `_parked` calls it too, and so does
  each exit of `_glide_home` (via `idle_add`). A zoom request during the
  hover return glide uses the kept spot.
- A docked `go_monitor` moves the spot to the destination monitor.
- `_settle_xpos` keeps exactly one timer while the button is held, and
  calls `_save_xpos` once after release. The same holds for the
  window-mode undock save at `:1129`.
- Startup with a saved right-edge spot (`x=748` on 1280×720 at 16 px /
  200 %) keeps `x0=748` and zoom 1.565, and asserts `cur_w`, the size
  request and `set_zoom_level`. A 600 px monitor with no saved spot gets
  the corner rule from Design 3, step 2. With no saved spot, the corner sits
  10 px from the edge at the capped zoom. The same holds for `go_monitor`
  from 2560×1440 to 1280×720, docked and free.

**Page, `tests/stages_fit.mjs`:**

- With the strip in the middle and both sides under 400:
  - the standard card and the News card, each on the right and on the
    left, lie inside the window (`left ≥ 0`, `right ≤ innerWidth`);
  - a click on a card button lands on it.
- The same at `fitK < 1`, after a `resize`.
- News on the left with 370 px of room is shifted, not clipped.
- Collapsing to the tab, and closing with no window resize, each reset
  `--stgIn`. The tab sits at
  its usual place.
- With room to spare, `#stg` sits at `left:350px` (right) and `-400px`
  (left), as today.

**Regression:** the full suite (`nix develop -c python3 -B -m unittest
discover -s tests`).

**On the desktop:** a test build through `systemd-run` with
`RemainAfterExit`, with its own test config. Screenshots come from headless
Chromium with `--disable-gpu`. On razer at Card text 200 %:

- drop Nixi in the middle, open News and a standard card, and check each
  card and its buttons are on screen. Click a button for real, with
  click-through on, since a page hit test does not exercise the GTK input
  region;
- drop him at each edge and check the text size matches today's build;
- drag him to dock, undock him, and step aside with a card: the zoom does
  not change during the dock glide, and the card fits after each return;
- restart Nixi and check the text size and position are as before.
