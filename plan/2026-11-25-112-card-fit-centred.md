---
status: approved
issue: 112
spec: spec/2026-11-25-112-card-fit-centred.md
coders:
  1: codex    # small, exact maths in one function plus table tests
  2: coder    # window.py steps 2-4 go to one coder: they share the _apply_page / zoom-spot contract
  3: coder
  4: coder
  5: agy      # page CSS/JS plus a long browser fixture file (mechanical, larger edits)
reviewers:
  - codex     # cross-review: reads the coder's window.py steps and agy's step 5 (not its own step 1)
  - agy       # cross-review: reads Codex's step 1 and the coder's window.py steps (not its own step 5)
---

# Plan: cards fit beside Nixi wherever he stands

Self-contained. Everything here is carried over from the approved intent and
spec, so the steps can be implemented without opening them.

## Approved decisions

- **D1.** When the card cannot fit beside Nixi even at the smallest zoom his
  size allows, it slides over him just far enough to stay on the monitor.
  Text is never made smaller than his size setting allows, and sideways
  scrolling is not used.
- **D2.** The position-aware cap applies always, not only while a card is
  open.
- **D3.** Scope is the answer card's horizontal fit. Vertical fit, other
  cards and panels (`#mailPop`, `#code`, `.pn`) keep #109's behaviour. The
  collapsed tab is never shifted.
- **D4.** The cap is keyed to the strip's **left edge** `x0` (monitor-relative,
  logical px), the point `set_wide` already keeps still
  (`base = mx + wide_shift`). Nixi shrinks toward that edge when the zoom
  drops, as he already does for the size keys. Accepted by the owner.
- **D5.** The cap is sized for the standard card (400 CSS px beside the
  strip), so News (340 px) can get slightly smaller text than it strictly
  needs. Accepted.
- **D6.** One cached **zoom spot** `(monitor geometry, x0)` feeds the cap.
  It refreshes only while Nixi is free (not docked, not hovering from hover
  start until the glide home lands). Accepted limits: a drag that docks on
  another monitor may snap. A drag from a larger to a smaller monitor can
  leave text a little small until the next move.

The cap, in `size.zooms`:

```python
fit = min(mon_w / 750, mon_h / 460) if mon_w is not None and mon_h is not None else math.inf
if x0 is not None and mon_w is not None:
    fit = min(fit, max((mon_w - x0) / 740, x0 / 400))
page = page_zoom(max(min(target / 14, fit), z))
```

## Steps

1. **`app/size.py:45-50` (`zooms`): add `x0=None` as the last parameter,
   and add the two lines above.** Keep every existing caller working
   unchanged.
   - Tests go in `tests/test_window_room.py`, beside `test_card_zoom`
     (`:91`). Use a 16 px terminal and Card text 2.0 unless noted:

     | Call | Expected |
     |---|---|
     | `x0=None`; `mon_w=None, mon_h=None, x0=500` | today's values |
     | 1280×720, `x0=0` and `x0=748` | 1.565 (to 3 dp) |
     | 1280×720, `x0=374` | 1.224 (to 3 dp) |
     | 1280×720, `x0=100` | 1.565 |
     | 2560×1440, `x0=900` | 2.25 |
     | 1024×768, size 1.25, `x0=320` | 1.25 |

   - Check: `nix develop -c python3 -B -m unittest discover -s tests -p 'test_window_room.py'`
   - Traps: `zooms` returns `(page, z/page, target)`, so keep all three.
     `page_zoom` clamps to 0.5-2.5.

2. **`app/window.py`: zoom spot, `_apply_page` and the recompute points.**
   - In `__init__`, add `self.zoom_spot = None` next to `self.z` (`:355`)
     and `self.hover_return = False` next to `self.hover` (`:385`).
   - Add `_zoom_spot()`, which returns `(g, x0)` and never `None`.
     - When free (`not (self.bar or self.hover or self.hover_return)`, or
       when `self.zoom_spot is None`), compute and store it:
       - layer mode: `g = self._geom()[1]`, `x0 = self.mx + self.wide_shift`;
       - window mode: `g` is the monitor `_mon_at` picks for the ball today
         (`:484-485`), and `x0 = self.mx + self.wide_shift - g.x`.
     - Otherwise, return `self.zoom_spot` unchanged.
   - Split `_apply_zoom` (`:478-494`) into two helpers:
     - `_size_page(page)` sets `self.z`, calls
       `self.view.set_zoom_level(self.z)` if `self.view` exists, sets
       `cur_w, cur_h = self._px(W), self._px(H)`, and calls
       `set_size_request`/`resize`. It does no room, dock or region work,
       so it is safe before placement and in `__init__`.
     - `_apply_page(page)` calls `_size_page(page)`, then today's
       `set_wide(..., "size")`, `set_bar(self.bar, glide=False)` if docked,
       and `_apply_region()`.
     `_apply_zoom` takes `(g, x0)` from `_zoom_spot()`, computes
     `size.zooms(..., g.width, g.height, x0)`, calls `_apply_page` if the
     page changed, then `_push_zoom`.
   - `_push_zoom` (`:496-502`) uses `self.zoom_spot` if it is set, and
     otherwise today's lookup with `x0=None`. It passes `x0` to `zooms`.
   - New calls to `_apply_zoom`:
     - at the end of `_save_pos` (`:589-600`);
     - at the end of `_parked` (`:842`).
   - Hover return: in `set_hover(False)`, set `self.hover_return = True`
     only inside the branch that starts `_glide_home` (`:1265-1266`). Each
     of `_glide_home`'s three exits (`:1282`, `:1288`, `:1303`) replaces
     `GLib.idle_add(self._rewide)` with `GLib.idle_add(self._hover_landed)`.
     `_hover_landed` runs on the GTK thread after the final move: it calls
     `_rewide()`, sets `self.hover_return = False`, then calls
     `_apply_zoom()`. `set_hover(True)` also clears `hover_return`, which
     covers re-entering hover during a return.
   - Docked monitor move: in `go_monitor` (`:732-774`), when `self.bar` is
     set, set `self.zoom_spot = (g_dest, x_saved)` before the
     `_apply_zoom` at `:771`. `x_saved` is the saved `x` on the destination,
     or `None`.
   - Cross-monitor drag-to-dock: in `_dock_if_edge` (`:1022-1040`), when
     the layer branch moves him to monitor `i != self.mon_i`, set
     `self.zoom_spot = (g_i, None)` before `set_bar(edge)`. Accepted under
     D6: that dock may snap.
   - New tests (`window_methods` harness, `tests/test_window_room.py`):
     - the spot refreshes when free, and is kept when docked, hovering,
       and while `hover_return` is set;
     - window mode subtracts `g.x`;
     - `_push_zoom` uses the cached spot, and falls back when there is
       none;
     - a same-monitor drag-to-dock from `x0=374` with a drop at `x0=740`:
       no page change and no `set_bar(..., glide=False)`. A cross-monitor
       drag-to-dock sets `(g_i, None)`;
     - `_save_pos` and `_parked` call `_apply_zoom`;
     - `_hover_landed` clears the flag and then zooms. A queued idle
       callback is not run inline, and the flag is still set until it runs;
     - a docked `go_monitor` sets `(g_dest, x)` with a saved spot and
       `(g_dest, None)` without one.
   - Existing tests to update for the new helpers and state:
     - `test_window_zoom_applies_only_changed_page_and_always_pushes`
       (`:40`);
     - `test_window_pushes_zoom_values_for_current_monitor` (`:59`);
     - `test_layer_place_and_saved_base` (`:244`, `_save_pos` now zooms);
     - `test_hover_and_monitor_use_base` (`:273`, `go_monitor`);
     - `test_hover_collapses_upward_growth_and_restores_at_home` (`:297`,
       `_glide_home` exits).
   - Check: `nix develop -c python3 -B -m unittest discover -s tests -p
     'test_window_room.py'`.
   - Traps:
     - `window_methods` loads only the methods it names, so add new
       helpers to each test's list;
     - the harness's `GLib` has only `timeout_add`/`source_remove`, so add
       an `idle_add` that queues callbacks, and run the queue explicitly;
     - never import `window.py` itself (GTK).

3. **`app/window.py`: zoom before placement** (same coder as Step 2).
   - In `_load_pos` (`:530-546`), `_load_xpos` (`:548-559`) and the
     placement part of `go_monitor` (`:751-769`):
     1. Resolve the target monitor and the saved spot. Keep the existing
        `try/except` only around reading `POS_FILE`, and put the new zoom
        and size logic after it, so a bug there is not swallowed into the
        default corner.
     2. Compute the page with `size.zooms(..., g.width, g.height, x0)`.
        - With no saved spot, compute the page with `x0=None`. Then place
          the default corner once, 10 px from the bottom-right at that
          page, and compute the final page from that corner's `x0`, without
          moving the corner again.
        - The gap can then be up to `340·Δp` px more than 10, but the first
          `_apply_zoom` sees the same `x0` and the same page, so it is
          stable. That is the authoritative rule, replacing the spec's
          "recompute once" wording; record it as a deviation.
     3. Call `_size_page(page)`, not `_apply_page`, before
        `_place`/`_xmove`/`win.move`. `cur_w`/`cur_h` (used by `_place`'s
        clamp, `:619`) are then the destination size, and no room or dock
        work runs on the source monitor.
     4. Place as today. `go_monitor` then runs its `_rewide()` (`:770`)
        and `_apply_zoom()` (`:771`) on the destination as before.
   - `_load_xpos` monitor check (`:552`): for each monitor `g`, compute
     that monitor's page from the saved spot. Accept the first monitor
     whose bounds contain the saved centre `(gx + px(W)/2, gy + px(H)/2)`
     at that page. That same `g` and page are then used. Keep the "monitor
     is gone" fallback.
   - `__init__`: `_size_page` already skips `set_zoom_level` until
     `self.view` exists. Make `:418` use the `self.z` that `_load_pos`
     produced. In window mode, `_load_xpos` (`:442`) runs after the view
     exists, so `_size_page` sets the zoom level itself.
   - Tests:
     - layer startup with saved `x=748` on 1280×720 at 16 px / 200 %:
       `mx=748`, zoom 1.565, `cur_w=round(340·1.565)` and a matching size
       request;
     - window startup with the same spot also asserts `set_zoom_level`;
     - no saved spot on 1280×720: corner 10 px from the edge, zoom 1.565;
     - no saved spot on 600×800: the zoom equals what a following
       `_apply_zoom` computes, with no change and the gap stated;
     - a saved spot straddling a seam between two monitors of different
       sizes resolves to one monitor, with no fallback to the default;
     - `go_monitor` from 2560×1440 to 1280×720 with a saved right-edge spot
       keeps it, both docked and free, and no `set_wide`/`set_bar` runs
       before the destination placement.
   - Check: the Step 2 command, then the full suite.
   - Traps:
     - the `__init__` order (`:350-460`) is delicate: `_set_monitor` and
       `_place` need the layer surface, and `self.rects`/`self.region_on`
       do not exist before `:458`, which is why `_size_page` skips
       `_apply_region`.

4. **`app/window.py`: window-mode drag settle** (same coder).
   - Move the button check out of the X11 release poll (`:1001-1006`) into
     `_button_held()`, and call it from the poll.
   - `self.save_t` has one owner, `_arm_settle(ms)`. It removes any live
     `save_t`, then sets
     `self.save_t = GLib.timeout_add(ms, self._settle_xpos)`.
   - `_moved` (`:561-571`) calls `_arm_settle(700)`.
   - `_settle_xpos`:
     - while `_button_held()`, return `True` (the same source runs again);
     - otherwise set `self.save_t = None`, call `_save_xpos()`, and return
       `False`.
     `_save_xpos` no longer touches `save_t`.
   - The delayed undock save in `set_bar` (`:1129`) keeps its drag guards.
     Its window-mode branch calls `_arm_settle(0)` and returns `False`, so
     the settle timer (not the lambda) does the waiting. Layer mode still
     calls `_save_pos()` directly.
   - Tests:
     - held for 3 ticks, then released: `_save_xpos` runs once and one
       source stays live throughout;
     - `_moved` twice gives a single live source;
     - the undock callback with a configure timer pending leaves one
       source, and one save after release;
     - a direct `_save_xpos` (as `go_monitor` does) leaves a pending timer
       alone.
     Update `test_floating_drag_saves_base_after_upward_growth` (`:225`,
     `_moved` now uses `_arm_settle`/`_settle_xpos`).
   - Check: the Step 2 command.
   - Traps: the harness's `GLib.timeout_add` is a `Mock`, so drive ticks by
     calling `_settle_xpos` directly and count live sources by hand.

5. **`app/static/index.html`: slide-over.**
   - `stagePlace` (`:3323-3326`):
     - First set `stgEl.style.setProperty('--stgIn','0px')`, before the
       closed-stage return.
     - Compute `R = (innerWidth - layoutX) / fitK - 340` and
       `L = layoutX / fitK`. Use `R`/`L` for the existing side choice,
       replacing the current `right`/`left`.
     - If `stgState === 'open'`, take `w = stgEl.offsetWidth` and use the
       side's limits:

       | Side | `smallest` | `largest` |
       |---|---|---|
       | right | `10 + w − R` | `350 + L` |
       | left | `400 − L` | `740 + R − w` |

       Set `s = max(0, min(smallest, largest))`. When the window is
       narrower than the card (`340 + L + R < w`), use instead the `s` that
       puts the card's left edge at `-L`: `350 + L` (right) or `400 - L`
       (left). Write `--stgIn` as `s + 'px'`.
   - CSS `:215`: `left:calc(350px - var(--stgIn,0px))`. CSS `:218`:
     `#stg.l{left:calc(-400px + var(--stgIn,0px)); ...}`, keeping its
     transform.
   - In `stageHide`'s close branch (`:3671`), also reset `--stgIn`.
   - The `resize` listener (`:5000`) calls `stagePlace()` after `fit()`
     and before `sendRegion(true)`.
   - Tests in `tests/stages_fit.mjs`. They go after `:626`, where
     `window.fetch` is restored, and use a new helper. `show()` always
     grows the view to `340 + want`, so it cannot make a narrow window.
     The helper sets an explicit view size and `nixiLayout(ox)`, then
     waits more than 220 ms for `#stg.on`.
     - Asymmetric short rooms force each side: a 700 px window with
       `ox=100` (left 100, right 260, so the card goes right) and with
       `ox=260` (left 260, right 100, so it goes left). The standard card (`facts`) and News
       (`headlines`) each lie inside the window (`left ≥ 0`,
       `right ≤ innerWidth`).
     - A real click on a card button, sent with
       `Input.dispatchMouseEvent`, triggers its action (assert the post
       the button makes, as the existing button tests do).
     - Resize the view without a new `nixiLayout`: the shift is
       recalculated by the `resize` listener.
     - At height 400 (`fitK < 1`), the card is still inside.
     - News on the left with 370 px of room: shifted by 30, not clipped.
     - A 300 px window narrower than the card: its left edge is at the
       window's left.
     - Collapse to the tab, and close with no resize: `--stgIn` is `0px`,
       and `#stgTab`'s rectangle matches its pre-change place for that
       side.
     - Room to spare: `#stg` at `350`/`-400` as today, and all existing
       cases still pass.
   - Check: `nix develop -c python3 -B -m unittest discover -s tests -p
     'test_stages_fit.py'` (about 2-4 min). Run it in the foreground.
   - Traps:
     - `#stg.l`'s transform (`translateX(14px) scale(.97)`) is only the
       entry animation, so `left` carries the shift;
     - headless `--disable-gpu` Chromium only, never a GPU Chrome;
     - keep the page's size budgets (`test_react_art.py`).

6. **Lead: full check, review, desktop check, deviations, PR.**
   - Run the full suite (`nix develop -c python3 -B -m unittest discover -s
     tests`), plus `test_stage_focus_fit.py` and `test_settings_fit.py`.
   - Review:
     - a fresh Opus agent reads only this plan and `git diff main`;
     - the cross-reviews (`reviewers:`): Codex reads the window.py steps
       and Step 5, and agy reads Step 1 and the window.py steps.
   - Desktop check on **razer** at Card text 200 %, with click-through on,
     comparing against today's build:
     - Start the test build on razer over ssh with `systemd-run --user`,
       `RemainAfterExit` and its own test config, then take screenshots
       with `grim` there.
     - The owner does the real clicks on razer (a click through the GTK
       input region cannot be faked from p620). The lead asks for them and
       records the answers. The checks are:
       - drop Nixi in the middle, open News and a standard card: both are
         on screen and a button click works;
       - drop him at each edge: the text size matches today's build;
       - drag to dock: no snap and no zoom change during the glide. Then
         undock and step aside with a card: the card fits after each;
       - restart: same spot and size.
   - Record any deviation in this file in the same commit as the code.
     This includes the default-corner rule from Step 3.
   - Open the PR linking intent, spec and plan, stating which steps Codex,
     the coder and agy did, and comment "@codex review".
   - Merge and deploy to p620 and razer (not p510) only when the owner
     says so.

## Tests

| Command | Expected |
|---|---|
| `nix develop -c python3 -B -m unittest discover -s tests -p 'test_window_room.py'` | all pass, including the new cases |
| `… -p 'test_stages_fit.py'` | all pass, including the narrow-window cases |
| `… -p 'test_stage_focus_fit.py'`, `… -p 'test_settings_fit.py'` | pass |
| full suite `nix develop -c python3 -B -m unittest discover -s tests` | 0 failures (1463+ OK, 5 skipped today) |

## Rollback

Revert the PR. The change is confined to `app/size.py`, `app/window.py`,
`app/static/index.html` and their tests, with no config or saved-state
format change: `pos.json` keeps its fields. Deployed hosts roll back by
bumping `nixi-companion` back, or with `nixos-rebuild switch --rollback`.

## Deviations

- Step 2 (coder): `_apply_page` sets `self.cur_w = 0` after `_size_page`,
  before `set_wide`. `_size_page` already writes the new base size, so with
  no extra room `set_wide` would take its "nothing changed" early return and
  skip the re-clamp, `nixiLayout` and the Hyprland resize that a zoom change
  does today. Covered by
  `test_page_change_without_extra_room_still_reclamps_and_tells_page`.
- Step 2 (coder): `_parked` calls `_apply_zoom` first, not last. A larger
  page at the parked edge re-clamps him, and `aside["parked"]` must hold the
  clamped spot, or `may_return` (an exact match) never lets him glide home.
- Step 3 (coder): the default corner is placed once, at the page computed
  with `x0=None`, and the final page comes from that corner's `x0`. It is
  not moved again, so the first `_apply_zoom` is stable. This replaces the
  spec's "recompute once" wording, as Step 3 says. Also folded in: a
  `hover_n` counter, so only the latest glide home clears `hover_return`
  (a race the coder found in Step 2).
- Step 4: done by the lead, not the coder. The coder went idle without
  starting it, so it was stopped and the step taken over. As planned:
  `_button_held()` is shared with the X11 release poll, and
  `_arm_settle()` is the only owner of `save_t`. `_settle_xpos()` waits
  while the button is held, and the window-mode undock save goes through
  `_arm_settle(0)`.
