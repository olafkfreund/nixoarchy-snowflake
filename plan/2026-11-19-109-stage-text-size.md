---
status: draft
issue: 109
spec: spec/2026-11-19-109-stage-text-size.md
coders:
  2: coder    # terminal-font parser and its tests: mechanical, well specified formats
  3: codex    # small, tricky: the zoom formula, its clamps and invariants
  4: coder    # one more setting next to `size`: mechanical, existing pattern
  5: codex    # tricky: window zoom ownership, start order, reload and monitor triggers
  6: agy      # large page edit: CSS and JS across many places, each one specified
  7: coder    # CLI branch copied from `size`, and docs
reviewers:
  - codex     # read-only review of each step's diff and of the branch against this plan
  - agy       # read-only review of the branch against this plan, a second model's view
---

# Plan: companion cards readable at the shell's text size

This plan carries every approved intent and spec decision, so it can be
implemented without opening either.

- **Repo:** `/mnt/code/Source-home/GitHub/nixoarchy-snowflake`
- **Branch:** `feat/109-stage-text-size`, from `main` `a6c2124`. Line
  numbers refer to commit `071edbe` (code unchanged since `a6c2124`).

## Decisions

### The two numbers

```text
T     = clamp(term_px or 16, 10, 28) · card_text      # target text, logical px
C     = T / 14                                        # card CSS is designed around 14 px text
P_fit = min(mon_w / 750, mon_h / 460)                 # strip (340) + stage card (410) fit the monitor
P     = clamp(max(min(C, P_fit), z), 0.5, 2.5)        # WebKit page zoom
n     = z / P                                         # Nixi's own scale inside the page, ≤ 1
```

`z` is Nixi's size setting (0.5-1.25, unchanged meaning). The whole page
is zoomed by `P`; only Nixi is drawn at `n`, so he looks as he does today
(`P · n = z`). Default here (kitty 12 pt = 16 px, `card_text` 1.0,
`z` 0.75, 2560x1440): `P ≈ 1.14`, `n ≈ 0.66`. Monitor scale is not in the
formula (logical px throughout).

Approved limits:
- When `z > C`, cards are drawn at Nixi's size (up to 9 % larger than the
  terminal text today), and `text down` has no visible effect until
  `C > z`.
- `P_fit` caps card text on small monitors (about 22 px on 1280x720);
  Nixi's size always wins over it.
- With click-through off (the default; input shaping flickers on some
  drivers) the larger transparent window catches clicks, as the window
  does today.

### What follows Nixi's scale `n`

Everything else is drawn at `P` and needs no change: cards, bubble,
chips, menu, panels, approval and password boxes, mail pop, music card,
and their placement, window space and click regions.

| Thing | Rule |
|---|---|
| `#stage` | `transform:scale(var(--nk))` at rest, around the ball centre (`transform-origin:170px 165px`) |
| hover / peek | `scale(calc(.17 * var(--nk)))`, `scale(calc(.4 * var(--nk)))`; `nixiCorner` offsets `±(170 − 68·n)`, `±(165 − 66·n)` |
| docked (bar) | unchanged: page scale, notch and Nixi grow together |
| `#chalk` `#hat` `#pop` `#wtc` | `transform: translate(var(--ox),var(--oy)) <today's transform> scale(var(--nk))`, offset = (prop centre − ball centre)·(nk − 1); individual `translate` left free for `#chalk.pt` |
| `#musChip`, `#remChip` | page size; their CSS anchor corner moved by (anchor − ball)·(n − 1) |
| menu sparks `MENU_XY` | SVG units with the ball at (0,0): target `xy / n` outside bar mode, `xy` in bar mode |
| code sheet | mode scale from body class (peek .4, hover .17, else 1), not the live transform; native `SHEET_K = 14/15` (browser keeps .7); width capped so `W · SHEET_K ≤ ZOOM.monW / ZOOM.page − 380` |
| `screen.*` in page px | divided by `ZOOM.page` (unless step 1 shows WebKit already does it) |

### Ownership and timing

- `app/window.py` alone computes `(P, n, T)` via `size.zooms()` and pushes
  `nixiZoom({page, nk, cardPx, monW, size, cardText})` to the page. The
  server never computes them; `/api/state` carries only `size` and
  `card_text`.
- The page keeps them in a `ZOOM` object (defaults `{page:1, nk:1,
  cardPx:16}`), never in `info` (`refresh()` and `setSetting()` replace
  `info`). Browser fallback (`!NATIVE`): never pushed, defaults stay.
- Pushed: at start (after the monitor is known), after every page load
  (before `_send_corner()`), on `zoom:`/`text:` from socket or page, when
  Nixi settles on another monitor (not per frame), and on `rezoom` (sent
  when Settings opens; re-reads the terminal font).
- `nixiZoom` and the `#stage` `transitionend` both re-run the placement
  that depends on Nixi's drawn size.

### Terminal font (`app/termfont.py`)

Terminal: `$TERMINAL` (set, non-empty, not `xdg-terminal-exec`; basename,
`client` suffix stripped), else the first entry of
`<desktop>-xdg-terminals.list` for each lowercased `$XDG_CURRENT_DESKTOP`
name split on `:`, then `xdg-terminals.list`, under `$XDG_CONFIG_HOME`
(blank/`#` lines skipped, `:action` dropped, case-insensitive desktop IDs:
`kitty.desktop`, `Alacritty.desktop`, `com.mitchellh.ghostty.desktop`,
`foot.desktop`, `footclient.desktop`), else `None`. Size from the main
config only, last value wins, includes not followed: kitty `font_size`,
ghostty `font-size =`, alacritty `[font] size` (`tomllib`, bools
rejected), foot `font` in the main section (keys before any section are
main; first font of the list; `size=` pt or `pixelsize=` px; hand-parsed).
pt · 96/72; result outside 5-96 px, non-finite or unreadable → `None`.
Only files under `$XDG_CONFIG_HOME`.

### The keyboard step

Setting `card_text`, default 1.0, range 0.6-2.0, steps 0.1, shared like
`size`; an invalid POST value becomes 1.0. Global
`nixi-companion text up|down|reset`; in the page Ctrl+`=`/`+`/`-`/`0`;
Settings → Look "Card text" chips 80/100/120/150 %. Hyprland binds
(proposed SUPER+CTRL+ALT+SHIFT `=`/`-`/`0`) are a separate `nixos_config`
PR; this repo documents them.

## Steps

1. **WebKit probe** (me). In a scratch script, not the repo: a
   `WebKit2.WebView` in a `Gtk.OffscreenWindow` from the packaged
   `webkitgtk_4_1` (`nix develop`), zoom level 1.5, page with
   `#a{translate:10px 0;scale:.5;transform:rotate(10deg)}`. Read back
   `getComputedStyle(a).translate/scale`, `getBoundingClientRect()`, and
   `screen.width`/`screen.availWidth`/`innerWidth` vs zoom 1.
   → verify by the recorded output. Record the result in this plan; if
   individual properties are missing, props fold the offset into
   `transform` only (and `#chalk.pt` keyframes move to `transform`); if
   `screen.*` is already divided by the zoom, step 6 skips the
   `screen.*` change.
   Traps: memory "no GPU Chrome previews": offscreen only, no new
   visible window, no Chrome; WebKit only.

2. **`app/termfont.py` + `tests/test_termfont.py`** (new files).
   `term_px(env, config_home) -> float | None` per the Decisions.
   → verify by `python3 -B .github/ci/run_tests.py test_termfont`.
   Tests: each terminal's format; `$TERMINAL` set, empty,
   `xdg-terminal-exec`, `footclient`, a full path;
   `XDG_CURRENT_DESKTOP=Hyprland:wlroots` → `hyprland-xdg-terminals.list`;
   the five desktop IDs, `:action`, blank and comment lines; foot keys
   before `[main]`, repeated keys, a fallback list, `pixelsize`;
   alacritty `size = true`; missing, garbled, non-finite, 2 pt, 200 px →
   `None`.
   Traps: never read the real `~/.config`: every test builds its own
   temp `config_home` and passes `env` explicitly (memory: tests must not
   touch the live config). No imports from `server`.

3. **`app/size.py`: `page_zoom`, `zooms`, `text_step`** (+ tests in
   `tests/test_window_room.py`, which already imports `size.step`).
   - `page_zoom(raw)`: clamp to 0.5-2.5, non-finite → 1.0.
   - `zooms(size, card_text, term_px, mon_w, mon_h) -> (P, n, T)` exactly
     as the formula; `mon_w`/`mon_h` `None` → no `P_fit`.
   - `text_clamp(raw)`: 0.6-2.0, invalid → 1.0;
     `text_step(current, direction)` like `step` (`:13-18`), steps 0.1,
     `reset` → 1.0.
   → verify by `python3 -B .github/ci/run_tests.py test_window_room`.
   Tests: default → `P ≈ 1.143, n ≈ 0.656, T = 16`; `z 1.25` →
   `P 1.25, n 1`; `term_px None` → `T 16`; 1280x720 with `card_text 2`
   → `P = P_fit ≈ 1.565`; 960x540 with `z 1.25` → `P 1.25, n 1`;
   `n ≤ 1` over a grid of inputs; `card_text 2.0` with 28 px → 2.5;
   `text_step` up/down/reset and clamps.
   Traps: `step`, `clamp` and their 0.5-1.25 meaning stay untouched
   (`bin/nixi-companion:162` imports `step`).

4. **`app/server.py`: the `card_text` setting.**
   - `DEFAULTS` (`:160`): `"card_text": 1.0` next to `"size"` (`:251`).
   - Range rule `("card_text", 0.6, 2.0)` next to `("size", 0.5, 1.25)`
     (`:313`), so `SHARED_RULES`/`SHARED_OK` (`:298-299`) share it.
   - `card_text_value()` next to `size_value()` (`:6257`) using
     `size.text_clamp`; POST branch next to `:9548-9549`.
   - `info` (`:9116`): `"card_text": card_text_value(CFG.get("card_text"))`.
   → verify by `python3 -B .github/ci/run_tests.py test_shared_size
   test_shared_settings` (and a new test in `test_shared_settings.py`: a bad POST value becomes 1.0, a
   shared `card_text` is taken like a shared `size`).
   Traps: tests start the server only through `nixi_env` (memory: test
   servers use nixi_env; tests must not import server under the real
   HOME). `card_text` is not in `LOCAL_ONLY`.

5. **`app/window.py` (+ `app/aside.py`): the window owns the zoom.**
   - `saved_card_text()` next to `saved_size()` (`:140-147`), same file
     order, via `size.text_clamp`.
   - `__init__` (`:339`): `self.size = saved_size()`,
     `self.card_text = saved_card_text()`,
     `self.term_px = termfont.term_px(os.environ, <XDG_CONFIG_HOME>)`;
     `self.z = zooms(..., None, None)[0]` before `set_default_size`
     (`:343`); after `_load_pos` / `_load_xpos` (`:385`, `:426`) call
     `_apply_zoom()`.
   - `_apply_zoom(reread=False)`: optional re-read of `term_px`;
     `P, n, T = zooms(self.size, self.card_text, self.term_px, mon_w,
     mon_h)` with the current monitor's logical geometry (`_geom()` in
     layer mode, `_mon_at` of the window centre in X11 mode); if
     `P != self.z` run today's `set_zoom` body (`:463-470`) with
     `page_zoom`; always `_push_zoom()`.
   - `_push_zoom()`: `self._js("window.nixiZoom&&nixiZoom({...})")` with
     page, nk, cardPx, monW, size, cardText.
   - `set_zoom` / `socket_zoom` (`:461-475`): `zoom:<z>` now sets
     `self.size = window_size(z)` and calls `_apply_zoom()`. New
     `text:<v>` sets `self.card_text = text_clamp(v)` and calls
     `_apply_zoom()`. New `rezoom` calls `_apply_zoom(reread=True)`.
     Wire all three in `_on_msg` (`:1393`) and the socket table
     (`:1441`).
   - `load-changed` (`:1365`): on FINISHED, `_push_zoom()` then
     `_send_corner()`.
   - Monitor settle points call `_apply_zoom()`: `go_monitor` (`:693`),
     the end of a drag, `set_bar` (`:1034`), step-aside moves (`:775-840`).
     Not `_place`.
   - Drag dock threshold (`:1169-1171`): `self._px(40)` →
     `round(40 * self.size)`.
   - `app/aside.py` `plan()` (`:36-39`): take `strip_w` and `visible_w`
     arguments (defaults today's constants); `app/window.py:782-785`
     passes `340 · P` and `VISIBLE_W · self.size`.
   → verify by `python3 -B .github/ci/run_tests.py` (whole suite) and
   `python3 -c "import ast;ast.parse(open('app/window.py').read())"`.
   New tests via `window_methods(...)` in `tests/test_window_room.py`:
   `_apply_zoom` calls the zoom setter only when `P` changes and always
   pushes; `zoom:`/`text:` update the right field. `aside.plan` with
   scaled widths.
   Traps: `window_size()` keeps 0.5-1.25 for Nixi's size; `self.z` is
   now `P` and every `_px`/`_css` stays as is. No test may open a GTK
   window. No live restart in this step.

6. **`app/static/index.html`: the page.**
   - `ZOOM` object and `window.nixiZoom(o)`: store, set
     `info.size`/`info.card_text`, set `--nk` on `:root`, re-run
     `nixiCorner(corner)` (`:4770`), then `cardPlace()` and `fitCard()`
     if `pendingAppr`, `stagePlace()`, `sizeWindow()`,
     `sendRegion(true)`, `renderSettings()` if Settings is on.
   - `#stage` `transitionend` (`:4759`): also the placement above.
   - CSS: `:root{--nk:1}`; `#stage` (`:36`) resting
     `transform:scale(var(--nk))`; hover (`:38`) and peek (`:39`) scales
     times `var(--nk)`; bar rules (`:80-83`) unchanged.
   - `nixiCorner` (`:4770`): offsets `±(170 − 68·ZOOM.nk)`,
     `±(165 − 66·ZOOM.nk)`.
   - Props `#chalk` `#hat` `#pop` `#wtc` (`:381-391`) and `.l` variants:
     `--ox`/`--oy` from each prop's centre vs (170, 165), folded into
     `transform` as in the Decisions (per step 1's result).
   - `#musChip` (`:427`), `#remChip` (`:432`): anchor offsets with
     `calc()` and `var(--nk)`.
   - `MENU_XY` (`:3867-3870`) used by the sparks: divide by `ZOOM.nk`
     unless `barEdge()`.
   - Code sheet (`:4880`, `:4897-4898`, `:4916`): mode scale from body
     class; `SHEET_K = NATIVE ? 14/15 : .7`; width cap in `fitSheet`.
   - `screen.*` (`:3585`, `:3739`, `:4096`, `:4106`): divide by
     `ZOOM.page` (per step 1).
   - Keys (`:4864-4867`): Ctrl+`=`/`+` up, Ctrl+`-` down, Ctrl+`0` reset:
     step like `text_step`, `setSetting({card_text})`, then
     `native('text:'+v)`. Settings filter (`:4635`) lets these through.
     Keys help (`:1056`) lists them.
   - Settings → Look: "Card text" chips 80/100/120/150 % under
     `#sizeChips` (`:4328`), showing `ZOOM.cardPx`-based px; click posts
     `card_text` and sends `native('text:…')`, like the size handler
     (`:4547`). Opening Settings sends `native('rezoom')`.
   → verify by `python3 -B .github/ci/run_tests.py` (page tests such as
   `test_settings_fit`, `test_accessories_fit`, `test_stage_actions`), and
   `node --check` on the extracted `<script>` text.
   Traps: never put `page`/`nk` in `info`; `NATIVE` false leaves all of
   this inert; keep text via `textContent` (#144 rule). Settings labels
   are plain English in the HTML (Size row, `:910`); the new row follows
   that, and the Size help text (`:910`, "Nixi and everything he shows
   shrink together.") becomes "Nixi's own size. Cards follow Card text."
   `test_settings_fit` must still pass with the extra row.

7. **`bin/nixi-companion` and docs.**
   - A `text` branch copied from `size` (`:153-183`): `up|down|reset`,
     reads `card_text` from `shared.json` then `config.json`,
     `text_step`, POSTs `{"card_text": v}`, sends `text:<v>`; its own
     lock file `text.lock`.
   - `docs/GUIDE.md` (`:584`): the `text` row, the in-page keys, the
     proposed Hyprland binds, and Size meaning Nixi's own size.
   → verify by `bash -n bin/nixi-companion` and the whole suite.
   Traps: none beyond copying the `size` branch's error handling exactly
   (`|| true`, `exit 0`).

8. **Full check and runtime test** (me).
   - `python3 -B .github/ci/run_tests.py` and
     `nix develop -c python3 -B tests/test_plugin_sandbox.py` (README
     "Working on it"; only if the plugin path changed, else state it).
   - `nix build` of the package.
   - Runtime: start the built companion through `systemd-run --user`
     with `RemainAfterExit` (memory: test builds on the desktop), using
     the live Hypr signature (memory: Nixi restart).
     - News stage with kitty 12 pt: headline cap height within ±10 % of
       kitty's, at Nixi size 0.5 and 0.75.
     - Nixi's drawn size equal to before (±2 px) at 0.5, 0.75, 1.0;
       sparks reach the menu; props and chips beside him.
     - `nixi-companion text up` ×3 / `reset`, Ctrl+`=`/`-`/`0`,
       `nixi-companion size up/down`, each with a stage and an approval
       open and with Settings open.
     - Each card on both sides, docked on four edges, peek, hover, calm,
       step-aside; clicks checked with `wev` (memory: verify focus with
       wev); click-through on and off.
     - `card_text 2.0` on the smaller monitor; move between monitors; a
       re-auth reload; wait past a 15 s refresh with a card open.
   → verify by the screenshots and notes in the PR.
   Traps: deploys and `~/.config/nixos` are out of scope; the Hyprland
   binds are a separate `nixos_config` PR.

## Tests

```bash
python3 -B .github/ci/run_tests.py
nix develop -c python3 -B tests/test_plugin_sandbox.py
nix build
```

Expected: all pass; the plugin sandbox result stated in the PR.

## Rollback

Revert the branch's merge commit. A `card_text` key left in
`config.json` or `shared.json` is not read by older builds, so no data
migration is needed.
