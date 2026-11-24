---
status: draft
issue: 118
spec: spec/2026-11-24-118-einstein-skull.md
coders:
  1: codex   # paint refactor: small, subtle logic where the Devil must stay pixel-identical and plugins must not change
  2: agy     # Einstein body: art plus a registry entry; you asked for agy on this
  3: codex   # Skull body: sockets under moving eyes and the jaw against .avoid, tight geometry
  4: agy     # REACT touch entries and test lists: large and mechanical, plus two small test checks
  5: agy     # look/voice test cases and GUIDE rows: mechanical text edits
reviewers:
  - codex    # reads the branch diff natively (codex review --base main)
  - agy      # an independent second read of the same diff
---

# Plan: two new characters, Einstein and a white-bone Skull

## Summary of the approved decisions

This plan is self-contained. Implement from it, not from the spec.

- Two built-in characters, `einstein` (label "Einstein") and `skull` (label
  "Skull"), go after `devil` in `CHARACTERS` in `app/static/index.html:1429-1447`
  and in `app/server.py:437`. Voices stay on My voice. Colours are fixed (they
  ignore the body colour and Follow desktop theme). Each has one `touch` part.
- **Layer order** (both renderers): `back` draws over the ball and under the
  eyes, and `front` draws over the eyes. Live `index.html:880-890`
  (`path.ball` → `.nix` → `#face` → gloss → `#rim` → `.bfront`); `miniNixi`
  `:1402-1409`.
- **Fit contract** (`tests/character_fit.mjs`):
  - Body art stays within x ±96, y -120…+100 (`:201-204`).
  - Eyes stay inside `faceBox` and clear of `.avoid` at every mood, the talk
    swell and the gaze extremes. `.avoid` goes only on leaf shapes, never on
    `<g>` (`:150-164`).
  - The headphone cups clear the face (`:170-199`).
  - The `touch` part animates at rest, transform and opacity only. It is paused
    under `body.still` and stops under reduced motion (`:282-300`).
  - At least one `.accent` with a literal fill and a stroke at ≥ 3:1 (`:310-320`).
- **`paint`** replaces the Devil's colour special-case. Fill order everywhere:
  plugin `nodes` → `fill`; else `paint` → its gradient; else the theme
  gradient. `--rim` is set from `paint.rim` and removed without `paint`.
  `plugChars` sets `paint:null`. The Devil stays pixel-identical.
- **`REACT`** stays under 40,960 bytes (36,228 now; the 28 new entries
  measure 2,806 bytes in the file's format, so about 39,000 after). Keyframes
  and `transform-box`/`origin` go in the page stylesheet, not in `REACT`. If it
  does not fit: stop and ask, and don't trim other characters.

## Rules for every coder

- Never stage, commit, push, switch branches, deploy or restart anything. Never
  touch `~/.config/nixos` or `main`. Claude commits each step.
- Browser tests use only the repo's launchers (headless Chromium, GPU off,
  #138). Never open a GPU Chrome or a visible window.
- Tests start the server through `nixi_env` in a temporary HOME, never under the
  real HOME (#176).
- `index.html` is one large file: edit only the lines named, and keep the
  formatting of what is around them. `REACT` must stay valid JSON
  (`json.JSONDecoder().raw_decode`). Every `id=` inside `REACT` starts with `fx-`.
- New art is inline SVG with flat colours or `url(#<paint grad>)` /
  `var(--rim)`. No `<script|image|foreignObject|iframe|use|a|style>`, no
  `on*=`, no URLs, no `filter`.
- Run one test file as `nix develop -c python3 -B tests/<file>.py` (add
  `-k <name>` to pick one test).

## Steps

1. **`paint` for fixed palettes** (codex). In `app/static/index.html`:
   - `:1441` Devil entry: add
     `paint:{ball:'devBody',rim:'#5c0a1c',grads:[['devBody','radialGradient',{cx:-24,cy:-30,r:118},['#e0334f','#c81e3a','#7a0f24']],['devWing','linearGradient',{x1:0,y1:-16,x2:0,y2:86},['#e0334f','#c81e3a','#7a0f24']]]}`.
     The stops sit at 0, .55 and 1, and every gradient gets
     `gradientUnits="userSpaceOnUse"`.
   - `:1397-1403` `miniNixi`: replace the `devil` branch. Build
     `character.paint?.grads` with id `id+name`. The ball fill is
     `nodes ? fill : paint ? url(#<id><paint.ball>) : url(#<id>)`. The rim is
     `paint ? paint.rim : <existing rule>`. `art()` rewrites `url(#<name>)`
     for every name in `paint.grads`, and `var(--rim)`.
   - `:1912-1913` `setCharacter`: the ball fill is
     `nodes ? fill : paint ? url(#<paint.ball>) : url(#ballG)`. Set `--rim`
     from `paint.rim`, and remove it otherwise. `#rim` stays unfilled.
   - `:859-860`: delete the static `devBody`/`devWing`. Add an empty
     `<g id="paintDefs"></g>` in the same `<defs>`. Right after `CHARACTERS` is
     defined, and before the first `setCharacter`, fill it once from every
     `CHARACTERS[k].paint.grads`.
   - `:1454` `plugChars`: add `paint:null` to the spread.
   - `tests/character_fit.mjs` `plugpage` (`:80-106`): after `setCharacter('devil')`
     → `plug:fixture`, assert that `#stage` has no `--rim`, that the `#rim`
     stroke is not `rgb(92, 10, 28)`, and that the plugin's Settings tile ball
     fill is its flat fill.
   - `pixels` mode (`:30-77`, and `tests/test_character_fit.py:104-117`): take
     a character id and also capture the Settings grid tile. Add
     `test_devil_pixels_match_origin_main`: for the Devil, the live body and
     the tile must have **zero** differing pixels. Snowflake keeps its current
     tolerance.

   → verify: `nix develop -c python3 -B tests/test_character_fit.py` (all pass,
   including both pixel tests) and `nix develop -c python3 -B tests/test_react_fit.py`.
   Traps: the plugin flat fill must win over `paint`. The gradients must exist
   before the first paint. `miniNixi` previews must keep unique ids.

2. **Einstein body** (agy).
   - `app/server.py:437`: add `"einstein"`.
   - `app/static/index.html`, the `CHARACTERS` entry after `devil`:
     - `label:'Einstein'`, `the:false`.
     - `paint`: `einSkin` radial (`#f8d9bd`, `#eab894`, `#b47a55`, cx -24
       cy -30 r 118), `einHair` linear (`#ffffff`, `#e4e7ec`, `#aeb4bf`,
       y -120→0), `ball:'einSkin'`, `rim:'#6e4328'`.
     - **ball**: a slightly tall rounded head, about x ±80, y -80…84.
     - **back**: a bumpy white hair cloud (`url(#einHair)`, stroke
       `var(--rim)`) across the top and down both sides to x ±96, covering the
       head down to about y -64 but not inside `faceBox`. Two ears at the eye
       line, partly outside the head. A top tuft in `<g class="tHair">`.
     - **front**: bushy grey-white brows (about y -60) and a drooping
       moustache (about y 38-60), each a leaf path with `class="avoid"`. The
       nose is `class="accent avoid"`, fill `#e9a184`, stroke `#6e4328`.
     - `gloss:false`, `touch:'tHair'`.
     - `fits`: `none, halo, bow, scarf, tie, headphones, shades, glasses,
       chat, feed, plug`.
     - `faceBox`, `anchors`, `pivot` and `shadow` start from the Devil's.
       `cupX`/`band` sit the cups on the hair (about x ±96).
   - `:4447`: the label reads ``Voice for ${c.the===false?'':'the '}${label}``.
   - Stylesheet `:25-29`: add
     `.tHair{transform-box:fill-box;transform-origin:50% 100%;animation:hair-sway 3s ease-in-out infinite}`
     and a `hair-sway` keyframe (a small rotate). Add `.tHair` to the
     `body.still` pause rule and the reduced-motion rule.
   - `tests/test_character_fit.py`: add `test_einstein`, which runs
     `self.node("char","einstein")` and asserts exit code 0. It must not use
     `_char`, which skips.

   → verify: `nix develop -c python3 -B tests/test_character_fit.py -k einstein`
   passes. Tune the numbers until it does.
   Traps: bounds ±96, `.avoid` only on leaves, the accent ≥ 3:1. `test_react_art`
   fails until step 4, as expected.

3. **Skull body** (codex).
   - `app/server.py:437`: add `"skull"`.
   - `index.html`, the `CHARACTERS` entry after `einstein`:
     - `label:'Skull'`.
     - `paint`: `sklBone` radial (`#fdfaf2`, `#ece3cc`, `#b3a68a`), `ball:'sklBone'`,
       `rim:'#5f533f'`.
     - **ball**: a skull outline: a round cranium (about x ±86), cheekbones at
       the eye line, and a narrower jaw (about x ±58), y -84…88.
     - **back**: two filled dark sockets (`#2f281f`), each a little larger than
       the eye oval (EYE ±25.5, -4.5, 23.5 × 40.5, tilted 9° in at the top),
       not `.avoid`.
     - **front**: an upside-down heart nasal hole near 0,46, which is
       `class="accent avoid"`, fill `#2f281f`, stroke `#d9cfb6`. Teeth with
       lines between them across y 60-82, in `<g class="tJaw">`, with `avoid`
       on each leaf. One small crack on the cranium is optional.
     - `gloss:false`, `touch:'tJaw'`.
     - `fits`: `none, halo, crown, bow, nightcap, beanie, party, scarf, tie,
       headphones, shades, glasses, chat, feed, plug`.
     - The geometry starts from the Devil's.
   - Stylesheet: add
     `.tJaw{transform-box:fill-box;transform-origin:50% 0;animation:jaw-rest 4s ease-in-out infinite}`
     and a `jaw-rest` keyframe (translateY of 1 unit). Add `.tJaw` to the
     still and reduced-motion rules.
   - `tests/test_character_fit.py`: add `test_skull`, like `test_einstein`.

   → verify: `nix develop -c python3 -B tests/test_character_fit.py -k skull`
   passes.
   Traps: the sockets must not hide the eyes (they are in `back`). Hats must
   sit on the cranium.

4. **Reactions and test lists** (agy).
   - `REACT.touch` (after `"devil"`, `index.html:~1837`): add `"einstein"` and
     `"skull"`, each with all 14 ids in this order: `load memory error soon
     meeting notice ask done open music rain snow wind workout`. Each entry is
     `{"back": "", "front": "", "css": …}` in the file's pretty format. The
     `css` is empty except for these:
     - Einstein: `load`, `ask`, `music`, `workout` →
       `.c-einstein.r-<id> .tHair{animation:fxHair .2s infinite alternate}`;
       `error` → `fxHairD`; `meeting` → `animation:none`.
     - Skull: `load`, `ask`, `music`, `soon`, `notice` →
       `.c-skull.r-<id> .tJaw{animation:fxJaw .2s infinite alternate}`;
       `error` and `memory` → `fxJawO`; `meeting` → `animation:none`.
   - Page stylesheet: `@keyframes fxHair` (a fast shake), `fxHairD` (a droop,
     held), `fxJaw` (translateY 0→3) and `fxJawO` (open 4, held).
     Transform only.
   - `tests/test_react_art.py:12`: `CHARS` gets `"einstein", "skull"`. Add a
     test: the `BAD` regex finds nothing in the `back`/`front` strings of the
     `einstein` and `skull` registry entries (extracted from `index.html` by
     text).
   - `tests/react_fit.mjs`:
     - add the ids to the lists at `:29`, `:50` and `:214`;
     - run step 5 (`:174-199`) for `einstein` and `skull` as well as `devil`;
     - add a check that during `r-load` the touch element's animation name is
       `fxHair` / `fxJaw`.
   - `tests/stage_focus_fit.mjs:104,123`: add the ids.

   → verify: `nix develop -c python3 -B tests/test_react_art.py`, then
   `tests/test_react_fit.py` and `tests/test_stage_focus_fit.py`, all pass,
   and `REACT` is under 40,960 bytes.
   Traps: JSON validity, the `fx-` id rule, and the byte cap (stop if it is
   over).

5. **Config tests and docs** (agy).
   - `tests/test_look_character.py:15`: add the ids.
   - `tests/test_character_voice.py`: `look.character` `einstein` and `skull`
     are accepted and saved. With `voice_by_character={"skull":"deep"}`,
     `voice_key()` returns `deep` while the Skull is chosen, and the Voice tab
     preset otherwise.
   - `docs/GUIDE.md:326-333`: add the rows `| **Einstein** | \`einstein\` |`
     and `| **Skull** | \`skull\` |`.

   → verify: `nix develop -c python3 -B tests/test_look_character.py` and
   `tests/test_character_voice.py` pass.
   Traps: no server import under the real HOME.

6. **Integration and visual check** (Claude, no file edits beyond fixes).
   - The full suite:
     `nix develop -c python3 -B -m unittest discover -s tests -p 'test_*.py'`.
   - `tests/test_settings_fit.py` passes. The Character grid shows all 6 tiles
     without clipping at the 60% and 100% sizes.
   - Headless PNGs (`--disable-gpu`) of both previews and both live bodies, on
     light and dark backgrounds: neutral, happy, talking, blinking, with
     headphones, and with a hat on the Skull. I look at them and attach them
     to the PR.
   - The Opus review (a fresh agent with only this plan and `git diff main`),
     plus `codex review --base main` and agy on the same diff.
   - The PR links the intent, spec and plan, says which steps Codex and agy
     did, and says no plugin sandbox run was needed (no `app/plugins.py`,
     sandbox test or `nix/package.nix` change). Then comment "@codex review".

## Tests

| Command (`nix develop -c python3 -B …`) | Expected |
|---|---|
| `tests/test_character_fit.py` | all pass, none skipped; both pixel tests zero/within tolerance |
| `tests/test_react_art.py` | pass, `REACT` < 40,960 bytes |
| `tests/test_react_fit.py`, `tests/test_stage_focus_fit.py`, `tests/test_settings_fit.py` | pass |
| `tests/test_look_character.py`, `tests/test_character_voice.py` | pass |
| `-m unittest discover -s tests -p 'test_*.py'` | everything passes |

## Rollback

Revert the merge commit. Saved configs with `einstein` or `skull` then fall
back to Snowflake through `character_ok` (`app/server.py:443`), and a
`voice_by_character` entry for them is ignored. No migration and no host
changes are needed.
