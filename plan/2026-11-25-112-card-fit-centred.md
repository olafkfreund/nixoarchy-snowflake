---
status: draft
issue: 112
spec: spec/2026-11-25-112-card-fit-centred.md
coders:
  1: codex    # small, exact maths in one function plus table tests
  2: coder    # medium refactor of _apply_zoom and the zoom spot across several call sites
  3: codex    # tricky ordering at startup and on monitor moves, where earlier drafts went wrong
  4: codex    # timer ownership and the button check; small but easy to get subtly wrong
  5: agy      # page CSS/JS plus a long browser fixture file (mechanical, larger edits)
reviewers:
  - codex     # reviewed all three spec rounds; best placed to check the diff against them
  - agy       # independent second read of the page side and the browser tests
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
   - Add `self.zoom_spot = None` next to `self.z` (`:355`).
   - Add a helper `_zoom_spot()`. While free (`not self.bar and not
     self.hover`), it sets `self.zoom_spot = (g, x0)` and returns it.
     Otherwise it returns the kept spot.
     - layer mode: `g = self._geom()[1]`, `x0 = self.mx + self.wide_shift`;
     - window mode: `g` is the monitor `_mon_at` picks for the ball today
       (`:484-485`), and `x0 = self.mx + self.wide_shift - g.x`.
   - Split `_apply_zoom` (`:478-494`): its `if page != self.z:` body
     becomes `_apply_page(page)`. That body sets `self.z`, calls
     `set_zoom_level`, `set_wide(..., "size")`, `set_bar(self.bar,
     glide=False)` if docked, and `_apply_region`. `_apply_zoom` gets
     `(g, x0)` from `_zoom_spot()`, calls `size.zooms(..., g.width,
     g.height, x0)`, calls `_apply_page` if the page changed, then
     `_push_zoom`.
   - `_push_zoom` (`:496-502`) uses `self.zoom_spot` when set, and today's
     lookup otherwise, passing `x0` to `size.zooms`.
   - New calls to `_apply_zoom`:
     - at the end of `_save_pos` (`:589-600`);
     - at the end of `_parked` (`:842`);
     - on each of `_glide_home`'s three exits (`:1281-1302`), through
       `GLib.idle_add(self._apply_zoom)`, because it runs on a worker
       thread.
   - Hover counts as not free from the moment hover starts until the glide
     home lands. Add `self.hover_return = True` in `set_hover(False)`
     before the glide starts, and clear it on each `_glide_home` exit.
     `_zoom_spot` treats `self.hover or self.hover_return` as not free.
   - `go_monitor` (`:744-772`), docked: set `self.zoom_spot` to the
     destination monitor's geometry and the saved `x` there, or `None`.
     This happens before its `_apply_zoom` at `:771`.
   - Tests (`window_methods` harness, `tests/test_window_room.py`):
     - the spot refreshes when free and is kept when docked, hovering, or
       during the hover return;
     - window mode subtracts `g.x`;
     - `_push_zoom` uses the cached spot;
     - drag-to-dock from `x0=374` with a drop at `x0=740`: no page change,
       and no `set_bar(..., glide=False)`;
     - `_save_pos` and `_parked` call `_apply_zoom`;
     - a docked `go_monitor` moves the spot.
     Update `test_window_zoom_applies_only_changed_page_and_always_pushes`
     (`:40`) and `test_window_pushes_zoom_values_for_current_monitor`
     (`:59`) for the new signature.
   - Check: the Step 1 command.
   - Traps:
     - `window_methods` loads only the methods it names, so add new
       helpers to its list in each test;
     - `GLib` in the harness has only `timeout_add`/`source_remove`, so
       add `idle_add` there;
     - never import `window.py` itself (GTK).

3. **`app/window.py`: zoom before placement.**
   - In `_load_pos` (`:530-545`), `_load_xpos` (`:548-558`) and
     `go_monitor` (`:751-767`), follow this order:
     1. Resolve the target monitor and the saved spot.
     2. Compute the page with `size.zooms(..., g.width, g.height, x0)`.
        With no saved spot, use `x0=None`. Then compute the default corner
        (10 px from the bottom-right) at that page, and if the term binds
        there, recompute once with the corner's `x0`.
     3. Call `_apply_page(page)` before `_place`/`_xmove`/`win.move`, so
        `cur_w`/`cur_h` (used by `_place`'s clamp, `:619`) are already the
        destination size.
     4. Place as today.
   - `_load_xpos`'s monitor-exists check (`:552`) uses the page from
     step 2 for its `_px(W)`. Order the two so the check can use it, for
     example by working out the monitor from the saved `gx` first.
   - At startup, `_apply_page` must be safe before `self.view` exists.
     `_load_pos`/`_load_xpos` run at `:401`/`:442`, and the WebView zoom is
     set at `:418`. Either guard `set_zoom_level` until the view exists,
     with `:418` then using `self.z`, or move the call. Keep
     `set_wide`/`set_bar` out of `_apply_page` until `__init__` has
     finished, guarded by a flag set at `:460`.
   - Tests:
     - startup with saved `x=748` on 1280×720 at 16 px / 200 % keeps
       `mx=748` and zoom 1.565, and asserts `cur_w` and the size request;
     - with no saved spot, the corner is 10 px from the edge at the capped
       zoom;
     - a 600×800 monitor with no saved spot gets the corner rule;
     - `go_monitor` from 2560×1440 to 1280×720 keeps a saved right-edge
       spot, both docked and free.
   - Check: the Step 1 command, then the full suite.
   - Traps:
     - startup order in `__init__` (`:350-460`) is delicate: the
       `_set_monitor` and `_place` calls need the layer surface;
     - keep `screens.clamp_on` behaviour;
     - test builds on the desktop use `systemd-run` with `RemainAfterExit`.

4. **`app/window.py`: window-mode drag settle.**
   - Move the button check from the X11 release poll (`:1001-1006`) into
     `_button_held()`, and call it from the poll.
   - `_moved` (`:561-571`) schedules `self._settle_xpos` instead of
     `_save_xpos`.
   - `_settle_xpos` returns `True`, keeping the same timer, while the
     button is held. Otherwise it sets `self.save_t = None`, calls
     `_save_xpos`, and returns `False`. `_save_xpos` stops touching
     `save_t`.
   - The window-mode branch of the delayed undock save in `set_bar`
     (`:1129`) also goes through `_settle_xpos`.
   - Tests:
     - held for 3 ticks, then released: one `_save_xpos`, and
       `timeout_add` called once;
     - a direct `_save_xpos` while a timer is pending does not drop the
       timer;
     - the `:1129` window branch defers while the button is held.
   - Check: the Step 1 command.
   - Traps: the harness's `GLib.timeout_add` is a `Mock`, so drive ticks by
     calling `_settle_xpos` directly.

5. **`app/static/index.html`: slide-over.**
   - `stagePlace` (`:3323-3326`):
     - Reset `stgEl.style.setProperty('--stgIn','0px')` first, before the
       closed-stage return.
     - Compute `R = (innerWidth - layoutX) / fitK - 340` and
       `L = layoutX / fitK`. Use `R`/`L` for the existing side choice,
       replacing the current `right`/`left`.
     - If `stgState === 'open'`, take `w = stgEl.offsetWidth` and set:

       | Side | `smallest` | `largest` |
       |---|---|---|
       | right | `10 + w − R` | `350 + L` |
       | left | `400 − L` | `740 + R − w` |

       `s = max(0, min(smallest, largest))`. When the window is narrower
       than the card (`340 + L + R < w`), set `s` so the card's left edge
       is at `-L` on either side: `350 + L` (right) or `400 - L` (left).
       Write `--stgIn` as `s + 'px'`.
   - CSS `:215`: `left:calc(350px - var(--stgIn,0px))`. CSS `:218`:
     `#stg.l{left:calc(-400px + var(--stgIn,0px)); ...}`, keeping its
     transform.
   - In `stageHide`'s close branch (`:3671`), reset `--stgIn` too.
   - The `resize` listener (`:5000`) calls `stagePlace()` after `fit()`
     and before `sendRegion(true)`.
   - Tests (`tests/stages_fit.mjs`, using the existing `view`/`nixiLayout`
     simulation):
     - a window narrower than `340 + 800` with Nixi in the middle, so both
       sides are under 400: the standard card (`facts`) and News
       (`headlines`) on the right and the left lie inside the window, and
       a button in each answers `document.elementFromPoint`;
     - the same at height 400 (`fitK < 1`) after a `resize`;
     - News on the left with 370 px of room is shifted, not clipped;
     - collapse to the tab, and close with no resize: `--stgIn` is `0px`
       and `#stgTab` sits at `left:350px`/its `.l` place;
     - room to spare: `#stg` sits at `350`/`-400` as today. The existing
       cases still pass.
   - Check: `nix develop -c python3 -B -m unittest discover -s tests -p
     'test_stages_fit.py'` (about 2-4 min, foreground).
   - Traps:
     - the transform on `#stg.l` (`translateX(14px) scale(.97)`) is only
       its entry animation, so `left` carries the shift;
     - no GPU Chrome, only the headless `--disable-gpu` harness;
     - keep `REACT`/other page size budgets in mind (`test_react_art.py`).

6. **Lead: full check, desktop check, deviations, PR.**
   - Run the full suite (`nix develop -c python3 -B -m unittest discover -s
     tests`), plus `test_stage_focus_fit.py` and `test_settings_fit.py`.
   - Make a test build on p620 through `systemd-run --user` with
     `RemainAfterExit` and its own test config, at Card text 200 % on a
     1280-wide monitor or a scaled output:
     - drop Nixi in the middle, open News and a standard card, check they
       are on screen, and click a button for real;
     - drop him at each edge, and the text size matches today's;
     - dock, undock and step aside: no snap, and the card fits after each;
     - restart: same spot and size.
   - Record any deviation in this file in the same commit as the code.
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
