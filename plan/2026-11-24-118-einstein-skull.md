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
  eyes, and `front` draws over the eyes. Live `index.html:880-891`
  (`path.ball` → `.nix` → `#face` → gloss → `#rim` → `.bfront`); `miniNixi`
  `:1402-1409`.
- **Eyes**: `const EYE={rx:23.5, ry:40.5, cx:27.5, cy:-4.5, tilt:0.157}`
  (`:1930`). The centres are at **±27.5**, -4.5, tilted 9° in at the top. (The
  comment at `:1418` and the spec say ±25.5, but the code is right.)
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
- **Art**: Einstein is drawn here, as a caricature, and copies no existing
  art. The Skull is white bone and cartoon-friendly (no gore). Its dark sockets
  show when Nixi blinks or squints. On both a light and a dark desktop the
  bone still reads as bone.

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
- **Test command.** pytest is not in the dev shell, and some files have no
  `unittest.main()`. Always run:
  `nix develop -c python3 -B -m unittest discover -s tests -p '<file>' [-k <name>]`
  (there is no `tests/__init__.py`, so `tests/` is on the path). Read the
  "Ran N tests" line: a named test must run (N ≥ 1) and must not be skipped.
  The spec's `python -m pytest tests` means this same discover run.

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
     defined, and before the first `setCharacter`, fill it once from the
     entries that **have** a `paint` (`Object.values(CHARACTERS).filter(c=>c.paint)`).
     The live ids stay `devBody` / `devWing`.
   - `:1454` `plugChars`: add `paint:null` to the spread.
   - `tests/character_fit.mjs` `plugpage` (`:80-106`): after `setCharacter('devil')`
     → `plug:fixture`, assert that `#stage` has no `--rim`, that the `#rim`
     stroke is not `rgb(92, 10, 28)`, and that the plugin's Settings tile ball
     fill is its flat fill.
   - `pixels` mode (`:30-77`): it takes a 5th argument, a character id
     (default `snowflake`). Pass `character:<id>` to `applyLook` (`:54`) on
     both pages, and assert `BODY===CHARACTERS[<id>]` on both before
     capturing. Also capture the Settings grid tile, clipped to the bounding
     box of `#characterGrid [data-character="<id>"]` only. The grid grows to 6
     tiles in steps 2-3 while `origin/main` has 4.
   - `tests/test_character_fit.py:104-117`: let the pixel helper take the id,
     and add `test_devil_pixels_match_origin_main`. For the Devil, the live body
     and the tile must have **zero** differing pixels. Snowflake keeps its
     current tolerance.

   → verify:
   `nix develop -c python3 -B -m unittest discover -s tests -p 'test_character_fit.py'`
   passes all tests with both pixel tests run, not skipped (`origin/main`
   exists locally), and `-p 'test_react_fit.py'` passes.
   Traps: the plugin flat fill must win over `paint`. The gradients must exist
   before the first paint. `miniNixi` previews must keep unique ids.
   `react_fit.mjs` Step 5 reads `#devBody stop`, so the live id must not
   change.

2. **Einstein body** (agy).
   - `app/server.py:437`: add `"einstein"`.
   - `app/static/index.html`, the `CHARACTERS` entry after `devil`:
     - `label:'Einstein'`, `the:false`.
     - `paint`: `ball:'einSkin'`, `rim:'#6e4328'`, and two gradients:
       - `['einSkin','radialGradient',{cx:-24,cy:-30,r:118},['#f8d9bd','#eab894','#b47a55']]`
       - `['einHair','linearGradient',{x1:0,y1:-120,x2:0,y2:0},['#ffffff','#e4e7ec','#aeb4bf']]`
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
   - `:4447`: change it to
     ``$('#charVoiceLabel').textContent=`Voice for ${bodyL.the===false?'':'the '}${bodyL.label}`;``.
     It says "Voice for Einstein", and every other label stays as it is.
   - Stylesheet: after the keyframes at `:24-26`, add
     `.tHair{transform-box:fill-box;transform-origin:50% 100%;animation:hair-sway 3s ease-in-out infinite}`
     and `@keyframes hair-sway` (a small rotate). Add `body.still .tHair` to
     the pause rule at `:21` and `.tHair` to the reduced-motion rule at `:22`.
   - `tests/test_character_fit.py`: add `test_einstein`. It runs
     `self.node("char","einstein")` and asserts exit code 0. Don't use
     `_char`, which skips.

   → verify:
   `nix develop -c python3 -B -m unittest discover -s tests -p 'test_character_fit.py' -k einstein`
   (1 test run, not skipped, and it passes; tune the numbers until it does),
   then the whole of `test_character_fit.py` (the Devil pixel test still at
   zero).
   Traps: bounds ±96, `.avoid` only on leaves, the accent ≥ 3:1.
   `test_react_art` stays green, because it reads only `REACT` and its own
   `CHARS`.

3. **Skull body** (codex).
   - `app/server.py:437`: add `"skull"`.
   - `index.html`, the `CHARACTERS` entry after `einstein`:
     - `label:'Skull'`.
     - `paint`: `ball:'sklBone'`, `rim:'#5f533f'`,
       `['sklBone','radialGradient',{cx:-24,cy:-30,r:118},['#fdfaf2','#ece3cc','#b3a68a']]`.
     - **ball**: a skull outline: a round cranium (about x ±86), cheekbones at
       the eye line, and a narrower jaw (about x ±58), y -84…88.
     - **back**: two filled dark sockets (`#2f281f`), each a rounded shape a
       little larger than the eye oval (centres **±27.5**, -4.5, 23.5 × 40.5,
       tilted 9° in at the top), not `.avoid`.
     - **front**: an upside-down heart nasal hole near 0,46, which is
       `class="accent avoid"`, fill `#2f281f`, stroke `#d9cfb6`. Teeth with
       lines between them across y 60-82, in `<g class="tJaw">`, with `avoid`
       on each leaf shape. One small crack on the cranium is optional.
     - `gloss:false`, `touch:'tJaw'`.
     - `fits`: `none, halo, crown, bow, nightcap, beanie, party, scarf, tie,
       headphones, shades, glasses, chat, feed, plug`.
     - The geometry starts from the Devil's.
   - Stylesheet: add
     `.tJaw{transform-box:fill-box;transform-origin:50% 0;animation:jaw-rest 4s ease-in-out infinite}`
     and `@keyframes jaw-rest` (translateY of 1 unit). Add `.tJaw` to the rules
     at `:21` and `:22`.
   - `tests/test_character_fit.py`: add `test_skull`, like `test_einstein`.

   → verify: `… -p 'test_character_fit.py' -k skull` (1 test run, not skipped,
   and it passes), then the whole file.
   Traps: the sockets must not hide the eyes (they are in `back`). Hats must
   sit on the cranium.

4. **Reactions and test lists** (agy).
   - `REACT.touch`, in `index.html` after the Devil block closes at `:1838`
     and before `touch` closes at `:1839`: add `"einstein"` and `"skull"`, each
     with all 14 ids in this order: `load memory error soon meeting notice ask
     done open music rain snow wind workout`. Each entry is
     `{"back": "", "front": "", "css": …}` in the file's pretty format. The
     `css` is empty except for these:
     - Einstein: `load`, `ask`, `music`, `workout` →
       `.c-einstein.r-<id> .tHair{animation:fxHair .2s infinite alternate}`;
       `error` → `.c-einstein.r-error .tHair{animation:fxHairD .4s forwards}`;
       `meeting` → `.c-einstein.r-meeting .tHair{animation:none}`.
     - Skull: `load`, `ask`, `music`, `soon`, `notice` →
       `.c-skull.r-<id> .tJaw{animation:fxJaw .2s infinite alternate}`;
       `error` and `memory` → `.c-skull.r-<id> .tJaw{animation:fxJawO .3s forwards}`;
       `meeting` → `.c-skull.r-meeting .tJaw{animation:none}`.
   - Page stylesheet: `@keyframes fxHair` (a fast rotate shake), `fxHairD`
     (`to{transform:rotate(18deg)}`), `fxJaw` (translateY 0→3) and `fxJawO`
     (`to{transform:translateY(4px)}`). Transform only.
   - `tests/test_react_art.py:12`: append `"einstein", "skull"` to `CHARS` in
     the same edit as the `REACT` blocks. Add a test that the `BAD` regex finds
     nothing in the `back`/`front` art of the `einstein` and `skull` registry
     entries. Trap: `CHARACTERS` is JS, not JSON (single quotes, `+`
     concatenation, `new Set`), so don't parse it. Cut the text from
     `einstein:{` to `skull:{`, and from `skull:{` to the closing `}};` of
     `CHARACTERS`, and run `BAD` on those slices.
   - `tests/react_fit.mjs`:
     - add the ids to the lists at `:29`, `:50` and `:214`;
     - fix the asserts that count four characters: `:172` gets 12 `true`
       values before `false, true, true`, and `:299` gets six `"none"`;
     - leave the Devil checks in Step 5 (`:174-199`) as they are. Add a
       separate block that runs the same two body colours for `einstein` and
       `skull`. For each, the live ball fill is `url(#einSkin)` /
       `url(#sklBone)`, the `#rim` stroke is the `paint.rim` colour, and the
       stops of `#<paint.ball>` are the fixed ones. In `#lookPrev`, the grid
       tile and the header logo, the body fill points to a radialGradient whose
       id ends in `einSkin` / `sklBone`, with the fixed stops. The colour
       picked changes none of this;
     - add a check: during `rxPlay('load',true)`, `.tHair` / `.tJaw` has the
       animation name `fxHair` / `fxJaw`.
   - `tests/stage_focus_fit.mjs:104,123`: add the ids.

   → verify: run the discover command with `-p 'test_react_art.py'`,
   `-p 'test_react_fit.py'` and `-p 'test_stage_focus_fit.py'`: all pass,
   `REACT` < 40,960 bytes.
   Traps: JSON validity, the `fx-` id rule, the byte cap (stop if it is over).

5. **Config tests and docs** (agy).
   - `tests/test_look_character.py:15`: add the ids.
   - `tests/test_character_voice.py`, using the existing settings fixture
     (`self.post`, near `:178-240`):
     - POST `look.character` `einstein` and then `skull`. Assert both are
       saved in `CFG` and in the written config file, and still there after
       the config is loaded again.
     - POST `voice_by_character={"skull":"deep"}` while the Skull is chosen.
       Assert it is saved, that `voice_key()` returns `deep`, and that after
       switching to `einstein` it returns the Voice tab preset.
   - `docs/GUIDE.md:326-333`: add the rows `| **Einstein** | \`einstein\` |`
     and `| **Skull** | \`skull\` |`.

   → verify: run the discover command with `-p 'test_look_character.py'` and
   `-p 'test_character_voice.py'`: N ≥ 1, and all pass.
   Traps: no server import under the real HOME. `test_character_voice.py` has
   no `unittest.main()`, so only the discover form runs it.

6. **Integration and visual check** (Claude; only fixes are edited here).
   - The full suite:
     `nix develop -c python3 -B -m unittest discover -s tests -p 'test_*.py'`.
   - `-p 'test_settings_fit.py'` passes. The Character grid shows all 6 tiles
     without clipping at the 60% and 100% sizes. Check it in the same capture
     script as below, with `#characterGrid` bounding boxes against the panel.
   - **Visual capture**: a script in the session scratchpad. It starts the
     server the way `tests/test_character_fit.py` does (`nixi_env`, a temporary
     HOME), and Chromium through `tests/_browser.start_browser`, headless with
     the GPU off. Then it:
     - for each id × {light `#f4f4f4`, dark `#1e1e2e`} page background, calls
       `applyLook({character:id})` and `poke()`s `neutral`, `happy`, `talking`
       and a blink;
     - turns headphones on, and puts `crown` on the Skull;
     - opens Settings → Look for the grid tiles;
     - saves each picture with CDP `Page.captureScreenshot`, clipped to
       `#stage` or the grid.

     I look at every PNG and attach a contact sheet to the PR.
   - The Opus review: a fresh agent with only this plan and `git diff main`.
     Then `codex review --base main` and agy on the same diff. Each one reads
     the other coder's steps.
   - The PR links the intent, spec and plan, says which steps Codex and agy
     did, and says no plugin sandbox run was needed (no `app/plugins.py`,
     sandbox test or `nix/package.nix` change). Then comment "@codex review".

## Tests

All run as `nix develop -c python3 -B -m unittest discover -s tests -p '<file>'`.

| `<file>` | Expected |
|---|---|
| `test_character_fit.py` | all pass, none skipped; Devil pixels zero, Snowflake within tolerance |
| `test_react_art.py` | pass, `REACT` < 40,960 bytes |
| `test_react_fit.py`, `test_stage_focus_fit.py`, `test_settings_fit.py` | pass |
| `test_look_character.py`, `test_character_voice.py` | pass, N ≥ 1 |
| `test_*.py` | everything passes |

## Rollback

Revert the merge commit. Saved configs with `einstein` or `skull` then fall
back to Snowflake through `character_ok` (`app/server.py:443`), and a
`voice_by_character` entry for them is ignored. No migration and no host
changes are needed.
