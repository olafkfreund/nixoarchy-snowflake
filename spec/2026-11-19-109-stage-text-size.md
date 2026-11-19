---
status: draft
issue: 109
intent: intent/2026-11-19-109-stage-text-size.md
---

# Spec: companion cards readable at the shell's text size

## Design

### 1. One number: the card scale `k`

Card CSS was designed around a 14 CSS px body line at page zoom 1. WebKit
draws the page at Nixi's size `z` (`app/window.py:402`, `:466`). So a
card's body text shows at `14 · z · k` logical px, where `k` is a CSS
`zoom` on the card. To get the target size `T`:

```text
T = clamp(term_px, 10, 28) · step      # step: the user's keyboard factor
k = T / (14 · z)
```

Default `term_px` 16, `z` 0.75, `step` 1.0 gives `k ≈ 1.52`: News
headlines go from about 10.5 px to 16 px. Changing Nixi's size changes
`z` and `k` together, so the card text stays put (intent outcome 2).
Monitor scale is not in the formula: GDK, WebKit and Hyprland already
work in logical px (`Hypr.monitors()` divides by `scale`,
`app/window.py:252`).

The page sets `--ck: k` on `:root` in one function, `cardScale()`, run
on load, on `info` changes (`size`, `card_text`, `card_px`), and from the
window's socket message. Nothing else computes `k`.

### 2. Applying `k`: CSS `zoom` on each card

Each card root in the intent's list gets `zoom: var(--ck)`: `#stg`,
`#stgTab`, `#appr`, `#pwbox`, `#mailPop`, `#musCard`, `#code`, `.ncard`.
`zoom` (not `transform: scale`) because it reflows: text wraps at the
new size, rasterises crisp, and `getBoundingClientRect()` (which
`sendRegion` measures, `app/static/index.html:4745-4755`) returns the
zoomed box, so the click-through region needs no change.

WebKit's `zoom` also multiplies the element's own `left`, `top`, `right`
and `max-height`. Each zoomed card's position is therefore written as
`calc(<today's px> / var(--ck))`, and positions set from JS (`cardPlace`,
`#code`'s `pos`, `#musCard`'s side) divide by `k` the same way. Props
around the stage (`#chalk`, `#hat`, `#pop`, `#wtc`) are not zoomed and
keep their place next to Nixi.

`.ncard` sits in the bubble strip `#cap` (`:182`, fixed 100 px tall).
While a notification shows (`#cap.ntf`), `#cap` drops its fixed height
and grows downward to fit the zoomed card; a new `capWant` in
`sizeWindow` (`:4714-4716`) asks for the extra height, like the other
cards. `#him`'s plain text keeps 14.5 px.

### 3. Window space follows the measured card

Every card's window request is computed from the card's measured
`getBoundingClientRect()` instead of fixed numbers:

- Stage: `stgSize(800)` and `stgSize(300)` (`:3426`, `:3438`, `:3443`)
  become `stgSize()` computing `[width needed beside Nixi, height
  overflow]` from the card's box. `stageWant` gains a height (today
  `[w,0]`, `:3088`). `stagePlace`'s room check (`:3092`, 400/160) uses
  the card's measured width plus 10.
- Approval card: `fitCard` (`:3586`) already measures `offsetHeight`;
  it uses the zoomed box and divides the 312-640 px width rule by `k`.
- Code sheet: `fitSheet` (`:4916-4920`) uses the zoomed `W` and `H`.
- Mail pop: `popWant` (`:3075`) from its zoomed box.

`set_wide` (`app/window.py:628`) already clamps the window to the
monitor (`:646-651`). When the card is taller than the window can be,
the card's own max-height is the window height (in card px, `/k`) and
its body scrolls (`#stg .bd` already scrolls, `:348`), so text size
wins over showing everything (intent outcome 4). Width is never
squeezed below the card's width at `k`: the stage picks the side with
room, and if neither side has room it takes the larger one and the
window grows up to the monitor edge.

`fit()` (`:4717`) still scales the whole body when the window is
smaller than 340x460; that only happens when the compositor refuses the
size, as today.

### 4. Where `term_px` comes from: `app/termfont.py`

A new module with one function, `term_px(env, home) -> float | None`,
run by the server at start and when Settings opens (cached; terminals
are not watched for changes):

1. Pick the terminal: `$TERMINAL` from the server's environment, else
   the first entry of `~/.config/xdg-terminals.list`, else Omarchy's
   default (alacritty). On this machine `$TERMINAL` is unset in both the
   shell and the systemd user environment, and the list (the file
   `xdg-terminal-exec` reads; comment lines skipped) names
   `kitty.desktop`, so the list is the real source; `$TERMINAL` only
   wins when someone sets it.
2. Read that terminal's font size, in points:
   - ghostty: `~/.config/ghostty/config`, `font-size = N`
   - alacritty: `~/.config/alacritty/alacritty.toml`, `[font] size`
     (`tomllib`)
   - kitty: `~/.config/kitty/kitty.conf`, `font_size N`
   - foot: `~/.config/foot/foot.ini`, `[main] font=...:size=N`
     (`configparser`; `pixelsize=` is already px)
3. Convert points to logical px: `pt · 96 / 72`.

Unknown terminal, missing file, parse error or a value outside 4-72 pt
returns `None`; the page then uses 16 px. The page clamps to 10-28 px.
Files are read only below `~/.config` (following Home Manager's store
symlinks is fine: `open()` resolves them).

The server sends it to the page in the existing `info` object as
`card_px` (number or `null`).

### 5. The keyboard step: `card_text`

A new setting `card_text` (the `step` in section 1), handled exactly
like `size` in `app/server.py`: a default in `DEFAULTS` (`:160`, next to
`size` at `:251`), a `("card_text", 0.6, 2.0)` range rule next to
`("size", 0.5, 1.25)` (`:313`), so it is shareable through
`SHARED_RULES`/`SHARED_OK` (`:298-299`) and settable from Nix like
`size` (#99), the POST branch next to `:9548`, and in `info` next to
`:9116`. Default 1.0, steps of 0.1, clamped by a new
`text_step(current, direction)` in `app/size.py`, the same shape as
`step`.

Keys:

- **Global:** `nixi-companion text up|down|reset`, a copy of the
  `size` branch in `bin/nixi-companion:153-183`: it saves `card_text`
  through `/api/settings` and sends `text:<value>` on the window socket.
  `app/window.py` handles `text:` next to `zoom:` (`:1393`, `:1441`) by
  running `info.card_text=<v>; cardScale()` in the page. The Hyprland
  binds live in `nixos_config` (outside this repo): proposed
  SUPER+CTRL+ALT+SHIFT `=` / `-` / `0`, next to the size binds
  (`docs/GUIDE.md:584`). This repo documents them; the bind change is a
  separate PR there.
- **When Nixi has the keyboard:** Ctrl+`=` / Ctrl+`-` / Ctrl+`0` in the
  page's key handler (`:4864-4867`) post the same setting and call
  `cardScale()`. Listed in the keys help (`:1056`).

### 6. Settings and docs

- Settings → Look shows "Card text" chips (80, 100, 120, 150 %) next to
  the existing Size chips (`#sizeChips`, `:4328`, handler `:4547`), with
  the resulting px shown.
- `docs/GUIDE.md` command table gains the `text` row; README feature
  line updated if it mentions sizes.

## Alternatives rejected

- **Raise Nixi's size default:** enlarges Nixi as well, and stops at
  1.25 (`k` at 1.25 is still 0.91 of the terminal size).
- **`transform: scale` on cards:** no reflow, blurrier text in WebKit
  layers, and it fights the stage's own open/close transform (`:208`).
- **A second WebView or layer-shell surface per card:** a much bigger
  change to window, region and focus handling for the same result.
- **Rewriting every card's CSS in `em`/`rem`:** ~170 `#stg` rules plus
  the other cards; a large diff with the same outcome as one `zoom`.
- **Scaling by monitor scale or DPI:** double-scales on HiDPI (intent).
- **First terminal config found:** an unused terminal's font says
  nothing about the user's preference (intent decision 1).

## Risks

- **WebKitGTK `zoom` semantics.** Whether `getBoundingClientRect()`,
  `offsetWidth` and absolute `left/top` include `zoom` differs between
  WebKit versions (WebKit has been moving to the standardised `zoom`).
  Plan step 1 is a probe in the packaged `webkitgtk_4_1`
  (`nix/package.nix:9`) that measures a zoomed element; if
  `getBoundingClientRect` does not include it, `sendRegion` multiplies
  by `k` for zoomed cards, and the `calc(/k)` positions are dropped if
  `left/top` turn out not to be multiplied.
- **Window too big on small monitors.** A 16 px card wants about
  600x670 logical px; on a 1366x768 laptop the stage may not fit beside
  Nixi on either side and will overlap him. Accepted: it scrolls and
  stays readable; Nixi can be moved.
- **Click-through drift.** If any card's region is measured before its
  zoom applies, clicks fall through it. `cardScale()` calls
  `sendRegion(true)` after it sets `--ck`.
- **Notification bubble growth** changes the strip under Nixi (`#cap`)
  that docked/bar mode also uses (`#barPill`, `:132`). In bar mode
  `.ncard` keeps `zoom:1`; only the floating bubble grows.
- **Hosts:** every host running the companion. No host-specific code;
  `nixos_config` key binds are a follow-up there.

## Verification

- `python3 .github/ci/run_tests.py` passes, with new tests:
  - `tests/test_termfont.py`: each terminal's config format, `$TERMINAL`
    vs `xdg-terminals.list` order, missing/garbled files → `None`,
    out-of-range values → `None`, under a temp HOME via `nixi_env`.
  - `tests/test_window_room.py` (where `size.step` is tested): `text_step`
    clamps and steps.
  - Settings API rejects a non-finite or out-of-range `card_text`, and a
    shared `card_text` is accepted like a shared `size`.
- WebKit probe (plan step 1) output recorded in the plan.
- Runtime, on this desktop through `systemd-run` with `RemainAfterExit`
  (memory: test builds on the desktop), headless screenshots per memory
  (no GPU Chrome previews):
  - News stage at size 0.5, 0.75, 1.25: headline height in the
    screenshot ≈ the terminal's line text height (±2 px).
  - `nixi-companion text up` ×3, `reset`: card grows, then returns.
  - Approval card, password box, mail pop, music card, code sheet,
    notification: each larger, nothing clipped, clicks land on buttons
    and pass through the transparent space (checked with `wev`, memory:
    verify focus with wev).
  - Collapse to tab / restore / close; docked, hover and calm modes
    hide stages as before; move Nixi to the other monitor.
- The plugin sandbox tests from README "Working on it" if the plugin
  stage path is touched; the PR states the result.
