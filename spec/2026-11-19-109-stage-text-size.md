---
status: draft
issue: 109
intent: intent/2026-11-19-109-stage-text-size.md
---

# Spec: companion cards readable at the shell's text size

Revision 3. Revision 1 put a CSS `zoom` on each card; Codex and agy found
it needed new placement code for every card, and on 2026-11-19 the user
chose the inverse: zoom the page to the card size and draw only Nixi
smaller. Revision 3 fixes what both reviewers found in revision 2 (the code
sheet inheriting Nixi's scale, the 1.25 zoom clamp, small monitors, one
source of truth for the zoom, click-through, things drawn next to Nixi).

## Design

### 1. Two numbers: page zoom `P` and Nixi's scale `n`

Today WebKit zooms the whole page by Nixi's size `z` (`app/window.py:402`,
`:466`), and every card, window request, click region and docked notch is
computed in page CSS px times that zoom (`_px`/`_css`,
`app/window.py:449-453`; `set_wide`, `split_room`, `set_bar`, `Ghost`).
Those paths already work at any zoom in 0.5-1.25.

New:

```text
T     = clamp(term_px or 16, 10, 28) · card_text      # target text, logical px
C     = T / 14                                        # card CSS is designed around 14 px text
P_fit = min(mon_w / 750, mon_h / 460)                 # strip + stage card fit on Nixi's monitor
P     = clamp(min(max(C, z), P_fit), 0.5, 2.5)        # WebKit page zoom
n     = z / P                                         # Nixi's own scale inside the page
```

Default (kitty 12 pt → 16 px, `card_text` 1.0, `z` 0.75, 2560x1440):
`P = C ≈ 1.14`, `n ≈ 0.66`. News headlines show at 16 px instead of
10.5 px; Nixi draws at `P · n = z`, the same size as today.

Monitor scale is not in the formula: GDK, WebKit and Hyprland work in
logical px (`app/window.py:253`).

**Two deliberate limits on the intent's outcomes** (for approval):

- **`max(C, z)`:** when Nixi is set larger than the cards would be
  (`z > C`, e.g. size 1.25 with a 16 px terminal), `P = z` and cards are
  drawn at Nixi's size: up to 9 % larger than the terminal text at
  today's settings, never smaller, and `text down` has no visible effect
  until `C > z`. The alternative, `n > 1`, draws Nixi larger than his
  340x460 strip and clips him.
- **`P_fit`:** on a monitor too small for the 340 px strip plus a 410 px
  stage card at `P`, the text is the largest that fits rather than
  scrolling sideways. On a 1280x720 monitor `P_fit ≈ 1.56` (about 22 px
  text), so it binds only above that. Vertically, cards keep their own
  `max-height` and scroll as today.

### 2. One source of truth: the window

`app/window.py` owns `(P, n)`. It keeps Nixi's size (`self.size`, from
`saved_size()` at `:339`) separate from the page zoom (`self.z`, now `P`),
plus `self.card_text` and `self.term_px`. One method, `_apply_zoom()`:

1. `P, n = size.zooms(self.size, self.card_text, self.term_px, mon_w, mon_h)`
   (new pure function in `app/size.py`, unit-tested).
2. If `P` changed, the body of today's `set_zoom` (`:461-470`): set the
   zoom level, re-request the extra space, re-apply the bar and region.
   The clamp is a new `page_zoom()` (0.5-2.5); `window_size()` keeps its
   0.5-1.25 meaning for Nixi's size.
3. Always push to the page: `nixiZoom(P, n, card_px)`, which sets
   `info.page_zoom`, `info.nk`, `info.card_px`, `--nk`, re-runs the
   placement that depends on Nixi's drawn size (`cardPlace()` and
   `fitCard()` if an approval is open, `stagePlace()`, `sizeWindow()`),
   `sendRegion(true)`, and `renderSettings()` if Settings is open.

It runs at start, on `zoom:<z>` and `text:<v>` from both the socket
(`:1441`) and the page (`_on_msg`, `:1393`), on a monitor change
(`P_fit` changes), and on `rezoom` from the page (sent when Settings
opens), which re-reads the terminal font first. The server never computes
`n`: `/api/state` carries `size`, `card_text` and `card_px` for display
only. In the browser fallback (`!NATIVE`) the page keeps `--nk` at 1 and
draws as today.

### 3. The page: what scales with `--nk`

- **`#stage`** (`app/static/index.html:36`, `transform-origin:170px
  165px`, the ball centre): resting `transform:scale(var(--nk))`; the
  hover rule (`:38`) becomes `scale(calc(.17 * var(--nk)))`. Peek
  (`:39`) becomes `scale(calc(.4 * var(--nk)))`, and `nixiCorner`
  (`:4770`) sets the corner offsets to `±(170 − 68·n)` and
  `±(165 − 66·n)` so the smaller body still sits in the corner. Docked
  (bar) mode (`:80-83`) keeps page scale: the notch and Nixi in it grow
  together with `P`, and the notch geometry is already in `_px`.
  Plugin props live in `#accBack`/`#accFront` inside `#stage` and follow
  automatically.
- **Props held next to Nixi** (`#chalk`, `#hat`, `#pop`, `#wtc`,
  `:381-391`): each gets the ball-relative offset and scale folded into
  its `transform`:
  `transform: translate(var(--ox), var(--oy)) <today's transform> scale(var(--nk))`,
  with `--ox`/`--oy` = (prop centre − ball centre) · (`--nk` − 1),
  computed from each prop's `left`/`top`/size (and `.l` variants). The
  individual `translate` property stays free for `#chalk.pt`'s keyframes
  (`:392-395`).
- **Controls attached to Nixi** (`#musChip` `:427`, `#remChip` `:432`):
  page size (readable), positioned toward the ball by the same offset
  rule, so they stay next to him.
- **The menu sparks** (`MENU_XY`, `:3867`): the menu buttons are at page
  scale, the sparks fly inside `#stage`; their targets are converted to
  stage coordinates (`ball + (xy − ball) / n`) so they still reach the
  buttons.
- **The code sheet** reads `#stage`'s scale (`:4897`,
  `k=SHEET_K*clamp(st,.4,1)`). It divides `st` by `n` so only the
  peek/hover mode scale counts, and `SHEET_K` goes from 0.7 to `14/15`
  so its 15 px text shows at `T`.
- **`screen.*` in page px** (`--apprMax` `:3585`, `setDefaultSize`
  `:3739`, Settings resize limits `:4096`, `:4106`): divided by
  `info.page_zoom`. Plan step 1 checks whether WebKit already reports
  `screen.*` in zoomed CSS px; if it does, no change.

Everything else (cards, bubble `#cap`, chips, menu, panels, approval and
password boxes, mail pop, music card) is drawn at `P` with no change: its
placement, window space and click region already scale with the zoom.
Cards stay beside the 340 px strip, so the gap between Nixi's drawn body
and a card grows by about `(1 − n) · 100 · P ≈ 40` logical px. Accepted.

### 4. Clicks: the window does not catch more than today

`click_through` defaults to off (`app/server.py:280`): the page then
sends `region:null` (`:4730`) and the whole window catches clicks. With a
larger window that would block more of the desktop. New: with
click-through off, the page sends the region it measures today for
click-through mode, plus Nixi's strip drawn at his scale (the 340x460
box scaled by `n` around the ball). So the clickable area is today's
window area plus whatever cards are open, not the larger transparent
window. Click-through on is unchanged.

### 5. Step-aside and dragging

- `aside.plan()` (`app/aside.py:36`) assumes a 340 px strip and 290 px
  of room. It takes the strip and visible widths as arguments instead,
  passed as `340·P` and Nixi's visible width `·z` from
  `app/window.py:782-785`.
- The drag threshold for docking (`app/window.py:1169-1171`,
  `self._px(40)`) uses Nixi's size (`40 · self.size`), so docking needs
  the same push as today.

### 6. Where `term_px` comes from: `app/termfont.py`

`term_px(env, config_home) -> float | None`, all logical px:

1. **Which terminal:**
   - `$TERMINAL` if set, non-empty and not `xdg-terminal-exec`: its
     basename, with `client` stripped (`footclient` → `foot`).
   - Else the first entry in `xdg-terminals.list` files in
     `xdg-terminal-exec`'s order: for each name in `$XDG_CURRENT_DESKTOP`
     split on `:`, lowercased, `<name>-xdg-terminals.list`, then
     `xdg-terminals.list`, under `$XDG_CONFIG_HOME`. Blank and `#` lines
     skipped; `:action` suffixes dropped; matched case-insensitively:
     `kitty.desktop`, `Alacritty.desktop`, `com.mitchellh.ghostty.desktop`,
     `foot.desktop`, `footclient.desktop`.
   - Else, or an unsupported terminal: `None`. No guessed default.
   Here `$TERMINAL` is unset and the list names `kitty.desktop`.
2. **Its font size.** The main config only, last value wins; includes are
   not followed (a font set only in an included file gives `None`):
   - kitty `kitty.conf`: `font_size N` (pt)
   - ghostty `ghostty/config`: `font-size = N` (pt)
   - alacritty `alacritty.toml`: `[font] size` (pt, `tomllib`; a bool
     is rejected)
   - foot `foot.ini`: `font` in the main section (keys before any
     section are main), first font of the comma list, `size=N` (pt) or
     `pixelsize=N` (px). Hand-parsed: foot allows keys before a section
     and repeated keys.
3. **To px:** points `· 96 / 72`; `pixelsize` as is. A result outside
   5-96 px, non-finite, or anything unreadable gives `None` (the page
   default, 16 px, applies).

Only files under `$XDG_CONFIG_HOME` (default `~/.config`) are opened;
Home Manager's store symlinks are followed by `open()`.

### 7. The keyboard step: `card_text`

A new setting handled like `size` in `app/server.py`: default 1.0 in
`DEFAULTS` (next to `size`, `:251`); a range rule `("card_text", 0.6,
2.0)` next to `("size", 0.5, 1.25)` (`:313`), so it is shareable through
`SHARED_RULES`/`SHARED_OK` (`:298-299`) and settable from Nix (#99); the
POST branch next to `:9548` with a `card_text_value()` like `size_value()`
(`:6257`): an invalid value becomes the default 1.0. Steps of 0.1 via
`text_step(current, direction)` in `app/size.py`, the same shape as
`step`.

Keys:

- **Global:** `nixi-companion text up|down|reset`, a copy of the `size`
  branch (`bin/nixi-companion:153-183`): read `shared.json` then
  `config.json`, step, POST `/api/settings`, send `text:<value>` on the
  socket. Hyprland binds live in `nixos_config`, outside this repo:
  proposed SUPER+CTRL+ALT+SHIFT `=` / `-` / `0`, next to the size binds
  (`docs/GUIDE.md:584`). This repo documents them; the binds are a
  separate PR there.
- **When Nixi has the keyboard:** Ctrl+`=` or Ctrl+`+`, Ctrl+`-`,
  Ctrl+`0` in the page's key handler (`:4864-4867`): step with the same
  rule as `text_step`, POST `{card_text}` with `setSetting`, then
  `native('text:'+v)`. Let through by Settings' `stopPropagation` filter
  (`:4635`) like Ctrl+`,`. Listed in the keys help (`:1056`).

### 8. Settings and docs

- Settings → Look: "Card text" chips (80, 100, 120, 150 %) under the Size
  chips (`#sizeChips`, `:4328`), showing the resulting px; a chip posts
  `card_text` and sends `native('text:…')`.
- `docs/GUIDE.md`: the `text` command, the keys, and what Size now means
  (Nixi's own size; the window follows the cards).

## Alternatives rejected

- **CSS `zoom` on each card** (revision 1): new placement, window-space
  and docking code for about eight cards.
- **`n > 1` instead of `max(C, z)`:** Nixi outgrows his strip and clips.
- **Horizontal scrolling instead of `P_fit`:** a stage card wider than
  the monitor hides its close and action buttons.
- **Raise Nixi's size default:** he grows too, and 1.25 is still below
  the terminal size.
- **`transform: scale` on cards; a second WebView per card:** blurrier,
  or a much larger change.
- **Monitor scale or DPI in the formula:** double-scales on HiDPI.
- **Server computes `n`:** two processes with different caches disagree;
  the window owns the zoom.

## Risks

- **Bigger transparent window.** About 1.5x today's at the default size
  (388x524 logical instead of 255x345). Section 4 keeps the clickable
  area as today; Nixi cannot sit as close to a monitor edge, and
  `screens.clamp_on` (`app/window.py:653`) and saved margins move him
  inward on the first start.
- **Things drawn next to Nixi** that section 3 does not list. The plan
  enumerates every absolutely positioned element in the 340x460 strip
  and checks each at `n = 0.4`.
- **Bar mode grows** about 1.5x at the default size. Intended, but
  visible.
- **Peek and hover** animate `--nk` together with their own scale.
- **`screen.*` under page zoom** and **individual transform properties**
  in the packaged `webkitgtk_4_1` (`nix/package.nix:9`): plan step 1
  probes both.
- **Tests that assume the window zoom equals the size setting.**
  `tests/test_shared_size.py` checks `saved_size()`, which keeps its
  meaning; any test of the window's zoom is updated to `P`.
- **Hosts:** every host running the companion; no host-specific code.

## Verification

- `python3 .github/ci/run_tests.py` passes, with new tests:
  - `tests/test_termfont.py` (temp HOME via `nixi_env`): each terminal's
    format; `$TERMINAL` set, empty, `xdg-terminal-exec`, `footclient`,
    a path; desktop-prefixed lists from `XDG_CURRENT_DESKTOP=Hyprland:wlroots`;
    `Alacritty.desktop`, `com.mitchellh.ghostty.desktop`,
    `footclient.desktop`, `:action`, blank lines; foot keys before
    `[main]`, repeated keys, a font fallback list, `pixelsize`; alacritty
    `size = true`; missing, garbled, non-finite, 2 pt and 200 px → `None`.
  - `zooms()`: the default case; `z = 1.25` → `P = 1.25, n = 1`;
    `term_px None` → 16 px; 1280x720 → `P_fit` binds; `card_text 2.0`
    with 28 px → clamped.
  - `text_step` steps and clamps; `/api/settings` replaces a bad
    `card_text` with 1.0; a shared `card_text` is taken like `size`.
  - `aside.plan()` with scaled widths.
- Plan step 1: WebKitGTK probe (individual transform properties;
  `screen.*` under `set_zoom_level`).
- Runtime on this desktop, through `systemd-run` with `RemainAfterExit`
  (memory: test builds on the desktop):
  - News stage with kitty at 12 pt: headline cap height in a screenshot
    within ±10 % of kitty's, at Nixi size 0.5 and 0.75.
  - Nixi's drawn size equal to today's (screenshot box ±2 px) at sizes
    0.5, 0.75 and 1.0; menu sparks reach the menu buttons; chalk, pop,
    hat, watch, ♪ and reminder chips sit where they do today relative to
    him.
  - `nixi-companion text up` ×3 and `reset`, Ctrl+`=`/`-`/`0`, and
    `nixi-companion size up/down`, each with a stage and an approval open
    and with Settings open: live, nothing clipped, chips and px update.
  - Each card (stage on both sides, its tab, approval, password, mail
    pop, music, code sheet including its text size, notification),
    docked on all four edges, peek, hover, calm, step-aside: placed as
    before; clicks land on controls; with click-through off, clicks
    outside Nixi and open cards reach the desktop (`wev`, memory: verify
    focus with wev).
  - `card_text` 2.0 on the 1280x720-sized monitor (or a scaled one):
    text capped by `P_fit`, no clipping, every control reachable.
  - Move Nixi to the other monitor and near each screen edge.
- If the plugin stage path is touched, the plugin sandbox tests from
  README "Working on it"; the PR states the result.
