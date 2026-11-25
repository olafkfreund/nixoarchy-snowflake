---
status: draft
issue: 112
intent: intent/2026-11-25-112-card-fit-centred.md
---

# Spec: cards fit beside Nixi wherever he stands

## Design

Four parts: a position term in the zoom cap, a stable anchor for it, more
places that recompute it, and a slide-over for when no zoom can fit the
card.

### 1. The cap learns where Nixi stands (`app/size.py`)

`zooms(size, card_text, term_px, mon_w, mon_h)` gains one optional input:
`cx`, the x of Nixi's ball centre relative to the monitor's left edge, in
logical px. `None` means "position unknown", and gives today's result.

The open card is 390 CSS px wide with a 10 px gap (`#stg`, `left:350px` on
the right, `left:-400px` on the left; `index.html:215`, `:218`). The strip
is 340 CSS px with the ball centre at 170 (`BALL`, `window.py:130`). At page
zoom `p`, with the ball centre held at `cx`:

- right card fits when `cx + (750 − 170)·p ≤ mon_w`, so `p ≤ (mon_w − cx) / 580`
- left card fits when `cx − 170·p − 410·p ≥ 0`, so `p ≤ cx / 580`

So the new cap is:

```python
fit = min(mon_w / 750, mon_h / 460)                 # today's cap, kept as an outer bound
if cx is not None:
    fit = min(fit, max(cx, mon_w - cx) / 580)        # the card fits on the roomier side
page = page_zoom(max(min(target / 14, fit), z))      # floor at Nixi's size stays (Decision 1)
```

Today's `mon_w / 750` stays. With the strip against an edge
(`cx = 170·p`), the new term is never below `mon_w / 750`, so at the edges
nothing changes. More generally, the new term only binds where the card
would not fit at today's zoom (the intent's "nothing changes where it fits"
outcome). Keeping `mon_w / 750` also covers the case where a larger zoom
pushes the strip against the monitor edge and the clamp moves it in: the
card on the other side still has `mon_w − 340·p ≥ 410·p`.

The 1280×720 example: `cx = 640` gives `640 / 580 ≈ 1.103`. At Card text
200 % the page zoom becomes 1.103 instead of 1.565, and the right card ends
at `640 + 580·1.103 ≈ 1280`.

### 2. Zoom changes keep the ball centre still (`app/window.py`)

Today `set_wide` places the window from the strip's left edge
(`base = mx + wide_shift`), so a zoom change grows or shrinks Nixi to the
right. With a position-aware cap that would move `cx` after the cap was
computed. So when `_apply_zoom` changes the page zoom from `old` to `new`,
it first shifts the strip by `round(BALL[0] · (old − new))` (in `mx`; layer
margins and window positions alike), then calls `set_wide` as today.
Vertical placement is unchanged (Decision 3, horizontal only).

`cx` comes from the strip's current position, computed in one helper used
by both `_apply_zoom` and `_push_zoom`:

- layer mode: `mx + wide_shift + px(BALL[0])` (margins are already
  relative to the monitor);
- window mode: the same, minus the monitor's `g.x` (global coordinates).

### 3. When the cap is recomputed (`app/window.py`)

- `_save_pos` (layer mode) now ends by calling `_apply_zoom`, like
  `_save_xpos` already does (`:585`). That covers a layer-mode move, the
  undock (`set_bar` saves after its glide, `:1129`), and the return from
  stepping aside (`aside_off` saves after its glide).
- While docked or hovering (`self.bar` or `self.hover`), `cx` is `None`.
  Cards are hidden in those modes (`stageVisSync`, `index.html:3322`), so
  his docked spot must not shrink the text. This also makes the drag-to-dock
  order at `:1169-1174` harmless: `self.bar` is already set when `:1174`
  runs, so the drop point is ignored.
- `_apply_zoom` does nothing while a drag is in progress (`self.dragging`
  or `self.pmoving`). The drag-finish call at `:1174` recomputes. This
  stops the 700 ms window-mode debounce (`_moved`, `:570`) from resizing
  the window mid-drag when the user pauses.
- While stepped aside, the zoom stays at what his home spot gave.
  `aside_on` saves before it glides, and the parked spot is not saved, so
  the cap uses his home position, which is the more conservative one.

### 4. The card slides over Nixi when nothing fits (`app/static/index.html`)

The floor at Nixi's size stays, so with a large size setting in the middle
of a small monitor the card can still lack room on both sides (Decision 1).
`stagePlace()` keeps its side choice. For an open card whose chosen side has
less than `need` (400), it sets a CSS variable `--stgIn` on `#stg` to the
shortfall, `need − room`, clamped so the card's other edge does not leave
the window either. The stage CSS uses it:

```css
#stg   { left: calc(350px - var(--stgIn, 0px)) }
#stg.l { left: calc(-400px + var(--stgIn, 0px)) }
```

The card slides inward over the strip just far enough to end at the window
edge. The window already reaches the monitor edge on that side, because
`stgSize(800)` asks `split_room` for room on both sides. The card's
z-index (7) already draws it above Nixi. `sendRegion` reads element
rectangles, so the click-through region follows the moved card. With room
to spare, `--stgIn` is 0 and the layout is exactly today's. The collapsed
tab (`#stgTab`, need 160) is not shifted (Decision 3).

`stagePlace` already runs on every `nixiLayout` (`:4999`), so the shift
follows any window resize, including one from a zoom change.

## Alternatives rejected

- **The issue's constant, `max(left, right) / 570`.** It has no 10 px gap,
  so at an edge it gives a cap above today's `mon_w / 750` and the card
  would end 10 px past the monitor. 580 matches today's edge case exactly.
- **Anchor on the strip's left edge (today's behaviour).** The cap would
  have to be `max((mon_w − x0) / 750, x0 / 410)`, and the strip must also
  fit (`p ≤ (mon_w − x0) / 340`). Against the right edge that last term
  pins the zoom at its current value, so the text could never grow there.
- **Iterating the cap until the centre settles.** Needless with a fixed
  centre, and a zoom change already resizes the window once.
- **Applying the position term only while a card is open.** Rejected by
  Decision 2: text would jump when cards open and close.
- **Dropping below Nixi's size, or scrolling the card sideways.** Rejected
  by Decision 1.
- **Sending the card to another monitor.** Large change, and it separates
  the card from Nixi.

## Risks

- **Nixi now grows around his centre** when the zoom changes for any
  reason, including the size and Card text keys. Before, he grew to the
  right. On p620 and razer that looks like a small sideways move of the
  strip's edges when stepping text size. It is intended, but visible.
- **A zoom change after every layer-mode drop.** On a small monitor,
  dropping Nixi in the middle now shrinks the text a moment after the drop,
  and moving him to an edge grows it back. That is the outcome, but it is a
  new visible change on razer's laptop screen.
- **Clamp at the edges.** In layer mode, `screens.clamp_on` keeps the strip
  on the monitor. Keeping the outer `mon_w / 750` bound is what makes the
  card fit after a clamp. Removing it later would bring the bug back.
- **Window mode on multiple monitors.** `cx` uses the monitor under the
  strip's centre (`_mon_at`). A strip straddling two monitors uses the one
  holding the ball, as `_apply_zoom` does today.
- **The slide-over hides part of Nixi.** Only when the size floor leaves no
  room, which needs a large size setting in the middle of a small monitor.
  Accepted by Decision 1.

## Verification

- **Unit, `tests/test_window_room.py` (`size.zooms`):**
  - `cx=None` and `cx` at either edge give today's values;
  - 1280×720, Card text 2.0, term 16, `cx=640` gives about 1.103;
  - Nixi size 1.25 at the same spot gives 1.25 (the floor);
  - 2560 wide, centred, Card text 2.0 gives `1280/580` only when that is
    below today's cap, and today's value when the card already fits.
- **Unit, window methods (same file, `window_methods` harness):**
  - `_apply_zoom` passes `cx` in layer and window mode, and `None` when
    docked or hovering;
  - a page change shifts `mx` by `BALL[0]·(old − new)` before `set_wide`;
  - `_apply_zoom` is a no-op while dragging;
  - `_save_pos` calls `_apply_zoom`.
- **Page, `tests/stages_fit.mjs`:** with an open card, a window narrower
  than 340 + 400 on both sides, and the strip in the middle, the `#stg`
  rectangle lies inside the window. With room to spare, `#stg` is at
  `left:350px` as today.
- **Regression:** the full suite (`nix develop -c python3 -B -m unittest
  discover -s tests`), including `test_stages_fit.py`,
  `test_shared_size.py` and `test_stage_focus_fit.py`.
- **On the desktop:** a test build through `systemd-run` with
  `RemainAfterExit`. On razer's screen at Card text 200 %, drop Nixi in the
  middle, open the News card, and check the card and its buttons are on
  screen. Then drop him at each edge and check the text size is what it was
  before the change.
