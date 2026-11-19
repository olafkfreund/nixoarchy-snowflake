---
status: draft
issue: 109
intent: intent/2026-11-19-109-stage-text-size.md
---

# Spec: companion cards readable at the shell's text size

Revision 2. The first draft put a CSS `zoom` on each card. Codex and agy
both found it needed new placement, window-space and docking code for
every card (left-side cards growing across Nixi, the code sheet's 0.7
scale, no window request for the password box and music card, clipping on
a live size change). On 2026-11-19 the user chose the inverse design
below: zoom the page to the card size and draw only Nixi smaller.

## Design

### 1. Two numbers: page zoom `P` and Nixi's scale `n`

Today WebKit zooms the whole page by Nixi's size `z` (`app/window.py:402`,
`:466`), and every card, window request, click region and docked notch is
already computed in page CSS px times `z` (`_px`/`_css`,
`app/window.py:449-453`; all of `set_wide`, `split_room`, `set_bar`, the
`Ghost` notch). Those paths work at any zoom today (0.5-1.25).

New:

```text
T = clamp(term_px or 16, 10, 28) · card_text     # target body text, logical px
C = T / 14                                       # card CSS was designed around 14 px text at zoom 1
P = clamp(max(C, z), 0.5, 2.5)                   # WebKit page zoom
n = z / P                                        # Nixi's own scale inside the page, ≤ 1
```

Default `term_px` 16 (kitty 12 pt here), `card_text` 1.0, `z` 0.75:
`C = P ≈ 1.14`, `n ≈ 0.66`. News headlines (14 CSS px) show at 16 px, up
from 10.5 px. Nixi draws at `P · n = z`, so he looks the same size as
today.

- `P ≥ z` keeps `n ≤ 1`, so a big Nixi never outgrows his 340x460 strip.
  When Nixi is set larger than the cards would be (`z > C`), cards follow
  him: a little larger than the terminal text, never smaller.
- Monitor scale is not in the formula: GDK, WebKit and Hyprland already
  work in logical px (`Hypr.monitors()` divides by `scale`,
  `app/window.py:253`).
- One Python function, `zooms(cfg, env, home) -> (P, n)` in
  `app/size.py`, computes both. `app/window.py` (at start: `:339`, where
  `saved_size()` is read today, and on socket messages) and `app/server.py`
  (for `info`) call the same function, so they cannot disagree.

### 2. The page: `--nk` on Nixi only

The window keeps `self.z` as the page zoom (`= P`), so all native
geometry is unchanged in form. The page gets `info.nk` (`n`) and sets
`--nk` on `:root`. CSS uses it in three places:

- **`#stage`** (`app/static/index.html:36`, `transform-origin:170px 165px`
  = the ball centre): a resting `transform:scale(var(--nk))`. The peek
  and hover rules (`:38-39`) multiply their scale by it:
  `scale(calc(.4 * var(--nk)))`, `scale(calc(.17 * var(--nk)))`.
  Their translations are page px to a window corner and stay unscaled.
- **Docked (bar) mode keeps page scale** (`:80-83` unchanged, no
  `--nk`): the notch pill and Nixi in it grow together with `P`, so the
  notch keeps its proportions and its text is readable like the cards.
  The window's notch geometry (`app/window.py:925-928`, `:1054-1055`) is
  already in `_px`.
- **Props held next to Nixi** (`#chalk`, `#hat`, `#pop`, `#wtc`,
  `:381-391`) keep their place relative to him with the individual
  `translate` and `scale` properties, which compose with their existing
  `transform` (rotate, `.l` variants): `scale:var(--nk)` and `translate`
  by `(prop centre − ball centre) · (--nk − 1)`. The centres come from
  each prop's existing `left`/`top`/`width`/`height`, written once as
  custom properties per prop (and per `.l` variant).

Everything else in the page (cards, bubble `#cap`, chips, menu, panels,
approval and password boxes, code sheet, music card, mail pop) is drawn
at `P` with no change: placement, window space and click regions keep
working because they already scale with the page zoom.

Cards stay where they are in the page (`#stg` at `left:350px`, etc.),
which is beside the 340 px strip, not beside Nixi's drawn body. With
`n ≈ 0.66` the gap between Nixi and a card grows by about
`(1 − n) · 100 · P ≈ 40` logical px. Accepted; it keeps every card's
placement code untouched.

### 3. Size changes at runtime

| Change | Window (`app/window.py`) | Page |
|---|---|---|
| `nixi-companion size up/down/reset` → `zoom:<z>` (`:1441`, `socket_zoom` `:472`) | recompute `(P, n)`; `set_zoom(P)` only if `P` changed (when `z > C`) | `info.size=z; info.nk=n;` set `--nk` |
| `nixi-companion text up/down/reset` → `text:<v>` (new, `:1441`) | recompute `(P, n)`; `set_zoom(P)` | `info.card_text=v; info.nk=n;` set `--nk` |
| Settings → Size chips (`:4547`, posts `size`, then `native('zoom:…')`) | same as the first row | same |
| Settings → Card text chips (new) → `native('text:…')` | same as the second row | same |

`set_zoom` (`:461-470`) already re-requests the window's extra space and
re-applies the region after a zoom change; the extra space is stored in
page CSS px (`want_css`), which is right because cards are page px at any
`P`. The page re-runs `sizeWindow()` and `sendRegion(true)` after
setting `--nk` so the region follows Nixi's new drawn size.

### 4. Where `term_px` comes from: `app/termfont.py`

`term_px(env, home) -> float | None`:

1. **Which terminal:** `$TERMINAL` (basename, with a `client` suffix
   stripped: `footclient` → `foot`); else the first non-comment entry of
   `$XDG_CONFIG_HOME/${XDG_CURRENT_DESKTOP}-xdg-terminals.list` or
   `xdg-terminals.list` (the files `xdg-terminal-exec` reads), matched
   case-insensitively on the desktop ID with any `:action` dropped
   (`kitty.desktop`, `Alacritty.desktop`, `com.mitchellh.ghostty.desktop`,
   `foot.desktop`); else `None`. No guessed default terminal. Here
   `$TERMINAL` is unset in the shell and the systemd user environment, and
   the list names `kitty.desktop`.
2. **Its font size, in points.** The main config only, last value wins;
   includes are not followed (a font set only in an included file gives
   `None`, so the 16 px fallback):
   - kitty: `~/.config/kitty/kitty.conf`, `font_size N`
   - ghostty: `~/.config/ghostty/config`, `font-size = N`
   - alacritty: `~/.config/alacritty/alacritty.toml`, `[font] size`
     (`tomllib`)
   - foot: `~/.config/foot/foot.ini`, key `font` in the main section
     (keys before any `[section]` belong to main), first font of the
     comma list, `size=N` in pt or `pixelsize=N` already in px. Parsed by
     hand, not `configparser` (foot allows keys before a section and
     repeated keys).
3. **Points to logical px:** `pt · 96 / 72`. All four terminals size
   fonts in points at 96 logical DPI on Wayland.

Anything unreadable, non-finite or outside 4-72 pt gives `None`. Only
files under `$XDG_CONFIG_HOME` (default `~/.config`) are opened; Home
Manager's store symlinks are followed by `open()`.

The window computes it at start; the server at start and on each
`/api/state` the page fetches (`refresh()`), cached for 60 s. A terminal
font change shows after the next refresh or restart; there is no file
watcher.

### 5. The keyboard step: `card_text`

A new setting handled exactly like `size` in `app/server.py`: a default
of 1.0 in `DEFAULTS` (`:160`, next to `size` at `:251`), a range rule
`("card_text", 0.6, 2.0)` next to `("size", 0.5, 1.25)` (`:313`), so it is
shareable through `SHARED_RULES`/`SHARED_OK` (`:298-299`) and settable
from Nix like `size` (#99). The POST branch (next to `:9548`) clamps like
`size_value`; a non-number is ignored like a bad `size`. `info` (next to
`:9116`) carries `card_text`, `card_px` (the clamped `T`) and `nk`.
Steps of 0.1 via a new `text_step(current, direction)` in `app/size.py`,
the same shape as `step`.

Keys:

- **Global:** `nixi-companion text up|down|reset`, a copy of the `size`
  branch in `bin/nixi-companion:153-183` (reads `shared.json` then
  `config.json`, steps, POSTs `/api/settings`, sends `text:<value>` on
  the socket). Hyprland binds go in `nixos_config`, outside this repo:
  proposed SUPER+CTRL+ALT+SHIFT `=` / `-` / `0`, next to the size binds
  (`docs/GUIDE.md:584`). This repo documents them; the binds are a
  separate PR there.
- **When Nixi has the keyboard:** Ctrl+`=` or Ctrl+`+`, Ctrl+`-`,
  Ctrl+`0` in the page key handler (`:4864-4867`), and let through by the
  Settings panel's `stopPropagation` filter (`:4635`) like Ctrl+`,`.
  Listed in the keys help (`:1056`).

### 6. Settings and docs

- Settings → Look: "Card text" chips (80, 100, 120, 150 %) under the Size
  chips (`#sizeChips`, `:4328`), showing the resulting px.
- `docs/GUIDE.md`: the `text` command row, the keys, and what Size now
  means (Nixi's own size; the window follows the cards).

## Alternatives rejected

- **CSS `zoom` on each card** (revision 1): new placement, window-space
  and docking code for about eight cards; see the review in the commit
  history.
- **Raise Nixi's size default:** he grows too, and 1.25 still leaves
  cards below the terminal size.
- **`transform: scale` on cards:** no reflow, blurrier text, fights each
  card's own transform.
- **A second WebView or surface per card:** much bigger change to window,
  region and focus handling.
- **Monitor scale or DPI in the formula:** double-scales on HiDPI.
- **A guessed default terminal:** the approved decision is the terminal
  actually chosen, else the fixed default.

## Risks

- **Bigger transparent window.** At `P ≈ 1.14` the window is about
  1.5x today's at the default size (388x524 logical instead of 255x345).
  Clicks still pass through the empty part (the region is measured), but
  Nixi cannot sit as close to a monitor edge, and `screens.clamp_on`
  (`app/window.py:653`) and saved margins move him inward on the first
  start. Checked at runtime on both monitors.
- **Nixi's things outside `#stage`.** Anything drawn next to Nixi that
  is not in `#stage` or the four props (for example the `#musChip` ♪
  at `:427`, `#wk`, plugin props in the scene) stays at page scale and
  may sit a little away from him. The plan lists each one and checks it.
- **Bar mode grows.** The docked notch is about 1.5x larger at the
  default size. Intended (readable), but visible.
- **Peek and hover** combine `--nk` with their own scale; the transition
  between modes animates both. Checked at runtime.
- **Tests that assume `window.z == size`** (`tests/test_shared_size.py`
  checks `saved_size()`, which keeps its meaning). Any test asserting the
  window's zoom equals the size setting is updated to `P`.
- **WebKitGTK support for individual `translate`/`scale` properties.**
  WebKitGTK 2.34+ has them; the plan's first step checks the packaged
  `webkitgtk_4_1` (`nix/package.nix:9`). If missing, the props get the
  offset folded into their `transform` instead.
- **Hosts:** every host running the companion; no host-specific code.

## Verification

- `python3 .github/ci/run_tests.py` passes, with new tests:
  - `tests/test_termfont.py` (temp HOME via `nixi_env`): each terminal's
    format; `$TERMINAL` vs `xdg-terminals.list`; desktop-prefixed list;
    `Alacritty.desktop` and `com.mitchellh.ghostty.desktop` IDs;
    `footclient`; foot keys before `[main]`, repeated keys, a font
    fallback list, `pixelsize`; a missing, garbled, non-finite or 2 pt
    value → `None`.
  - `zooms()`: default → `(1.14, 0.66)`; `z = 1.25` → `P = 1.25, n = 1`;
    `term_px None` → 16 px; `card_text` 2.0 with 28 px → `P` clamped to
    2.5.
  - `text_step` steps and clamps; `/api/settings` clamps `card_text`;
    a shared `card_text` is taken like a shared `size`.
- Plan step 1: a WebKitGTK probe for individual transform properties.
- Runtime on this desktop, through `systemd-run` with `RemainAfterExit`
  (memory: test builds on the desktop):
  - News stage with kitty at 12 pt: headline cap height in a screenshot
    within ±10 % of kitty's at the same zoom, at Nixi size 0.5, 0.75 and
    1.25.
  - Nixi's drawn size equal to today's (same screenshot box ±2 px) at
    sizes 0.5, 0.75, 1.0.
  - `nixi-companion text up` ×3 and `reset`, and Ctrl+`=`/`-`/`0`, with a
    card open: it grows and shrinks live, nothing clipped.
  - Each card (stage on both sides of Nixi, its tab, approval, password,
    mail pop, music, code sheet, notification), docked on all four edges,
    peek, hover, calm: placed as before, clicks land on controls and pass
    through empty space (`wev`, memory: verify focus with wev).
  - Move Nixi to the other monitor and near each screen edge.
- If the plugin stage path is touched, the plugin sandbox tests from
  README "Working on it"; the PR states the result.
