---
status: approved
issue: 118
intent: intent/2026-11-24-118-einstein-skull.md
---

# Spec: two new characters, Einstein and a white-bone Skull

## Design

Two built-in characters, `einstein` (label "Einstein") and `skull` (label
"Skull"), are added after `devil` in the same registry. They have a fixed
palette like the Devil and one `touch` part each, and their voices stay on My
voice. (These were the intent's recommendations, approved in `56791d5`.)

### Facts this design is built on

- **Layer order**, the same in both renderers. Live
  (`app/static/index.html:880-890`): `path.ball` → `.nix` (`back`) → `#face`
  (the eyes) → gloss → `#rim` → `.bfront` (`front`). `miniNixi` (`:1402-1409`):
  ball → `layer('back')` → eyes → `layer('front')`. So **`back` draws over the
  ball and under the eyes**, and **`front` draws over the eyes**.
- **Fit contract** (`tests/character_fit.mjs`), which every new body must pass:
  - Body art stays within x ±96, y -120…+100 (`:201-204`).
  - Both eyes stay inside `faceBox` and clear of every `.avoid`, in each mood,
    at the full talk swell and at the gaze extremes. `.avoid` goes only on leaf
    shapes, because the test calls `isPointInFill` (`:150-164`).
  - The headphone cups clear the face (`:170-199`).
  - The `touch` part animates at rest, using only transform and opacity. It is
    paused under `body.still` and stops under reduced motion (`:282-300`).
  - At least one `.accent` with a literal fill and a stroke at ≥ 3:1 contrast
    (`:310-320`).
- **`REACT` budget**: 36,228 bytes today, and the test needs it under 40,960
  (`tests/test_react_art.py:41`). That leaves 4,732 bytes for both new
  characters' 28 `touch` entries, in the file's pretty-printed format (about
  55 bytes for an entry with empty strings).

### 1. A fixed palette for any character, not only the Devil

Today the Devil's colours are special-cased in `miniNixi` (`:1397-1403`), in
`setCharacter` (`:1912-1913`) and in the static live `<defs>` (`:859-860`).
Both reviewers grepped and found no other colour special-case. Each
fixed-palette character gets one field:

```js
paint:{ball:'devBody', rim:'#5c0a1c', grads:[
  ['devBody','radialGradient',{cx:-24,cy:-30,r:118},['#e0334f','#c81e3a','#7a0f24']],
  ['devWing','linearGradient',{x1:0,y1:-16,x2:0,y2:86},['#e0334f','#c81e3a','#7a0f24']]]}
```

The stops sit at 0, .55 and 1, and every gradient gets
`gradientUnits="userSpaceOnUse"`, as today.

The fill for the ball keeps this order in **both** renderers: a plugin's flat
fill (`nodes`) first, then the fixed palette (`paint`), then the theme fill.

- `miniNixi`: `nodes ? fill : paint ? url(#<id><paint.ball>) : url(#<id>)`.
  The rim is `paint.rim` when `paint` is set, and the existing rule otherwise.
  Every `url(#<grad>)` of `paint.grads` and `var(--rim)` is rewritten to the
  preview's own ids.
- `setCharacter`: `nodes ? fill : paint ? url(#<paint.ball>) : url(#ballG)`.
  It sets `--rim` from `paint.rim`, and removes it when the character has no
  `paint` (a plugin too). `#rim` stays unfilled.
- Live `<defs>`: the gradients are built from the registry once, before the
  first `setCharacter`, into `<g id="paintDefs">` inside the existing `<defs>`.
  The static `devBody` / `devWing` lines are removed. The ids, stops and
  coordinates are the same, so the Devil stays pixel-identical.
- `plugChars` (`:1454`) sets `paint:null`, because it spreads
  `...CHARACTERS.devil`.
- The fork and tail CSS (`:31-32`) stay Devil-only.

### 2. Einstein

A caricature. Every shape is drawn here and is not copied from existing art.
All art stays within x ±96, y -120…+100.

- **ball**: a slightly tall rounded head (about x ±80, y -80…84).
- **paint**: `einSkin` radial (`#f8d9bd`, `#eab894`, `#b47a55`) for the head,
  `einHair` linear (`#ffffff`, `#e4e7ec`, `#aeb4bf`), rim `#6e4328`.
- **back** (over the head, under the eyes): a bumpy white cloud of hair across
  the top and down both sides, out to x ±96. It may cover the top of the head
  down to about y -64, but not inside `faceBox`. Two ears sit at the eye line,
  partly outside the head. A tuft on top is the `touch` part,
  `<g class="tHair">`.
- **front** (over the eyes): grey-white bushy eyebrows above the eyes (about
  y -60) and a big drooping moustache under them (about y 38-60). Both are
  leaf paths with `class="avoid"`. The **accent** is the nose: a small rounded
  shape between the eyes and the moustache, fill `#e9a184`, stroke `#6e4328`
  (about 4:1).
- **fits**: `none, halo, bow, scarf, tie, headphones, shades, glasses, chat,
  feed, plug`. No hats: they would float on the hair, as on the Robot.
- **geometry**: `faceBox`, `anchors`, `pivot` and `shadow` start from the
  Devil's. `cupX` and `band` sit the cups on the hair at about x ±96. The fit
  test sets the final values, including the cup checks in happy and roll.
- **voice label**: Settings reads "Voice for the Snowflake", so it would say
  "Voice for the Einstein". A registry field `the:false` drops the "the" for
  him, and only him (`:4447`).

### 3. Skull

White bone, cartoon-friendly (no gore). All art stays within x ±96,
y -120…+100.

- **ball**: a skull outline: a round cranium (about x ±86), cheekbones at the
  eye line, and a narrower jaw (about x ±58), y -84…88.
- **paint**: `sklBone` radial (`#fdfaf2`, `#ece3cc`, `#b3a68a`), rim
  `#5f533f`. On a white desktop the rim and the shade on the bottom edge set
  the shape apart, and on a dark desktop the bone stands out.
- **back** (over the bone, under the eyes): two filled dark eye sockets
  (`#2f281f`), each a rounded shape a little larger than the eye oval (EYE
  ±25.5, -4.5, 23.5 × 40.5, tilted 9°). Nixi's eyes sit on top. When he
  blinks or squints, the dark socket shows, as a skull should. Not `.avoid`:
  they are meant to sit under the eyes.
- **front** (over the eyes):
  - an upside-down heart nasal hole, around 0,46, below the eyes;
  - a row of teeth with lines between them across the jaw, around y 60-82.
    The teeth are `<g class="tJaw">`; the `.avoid` class goes on the
    shapes inside it, never on the `<g>`;
  - optionally, one small crack on the cranium.

  The **accent** is the nasal hole: fill `#2f281f`, stroke `#d9cfb6`
  (well over 3:1).
- **fits**: `none, halo, crown, bow, nightcap, beanie, party, scarf, tie,
  headphones, shades, glasses, chat, feed, plug`. The cranium is round like
  the Devil's, so hats fit. `sprout` is dropped.
- **geometry**: starts from the Devil's. The fit test sets the final values.

### 4. The touch parts and reactions

In the page stylesheet, next to `.tCursor` / `.tAntenna` / `.tTail`
(`:25-29`):

- Base rules: `.tHair{transform-box:fill-box;transform-origin:50% 100%;animation:hair-sway 3s ease-in-out infinite}`
  and `.tJaw{transform-box:fill-box;transform-origin:50% 0;animation:jaw-rest 4s ease-in-out infinite}`
  (a 1-unit jaw bob). Both animate transform only.
- `.tHair` and `.tJaw` are added to the `body.still` pause rule and to the
  reduced-motion rule.
- Keyframes for the reactions: `fxHair` (fast shake), `fxHairD` (droop),
  `fxJaw` (chatter, translateY 2-3 units) and `fxJawO` (open and hold).

`REACT.touch.einstein` and `REACT.touch.skull` each get all 14 ids in
`test_react_art.IDS` order. The entries use empty strings unless the reaction
does something. Each one that does is a single short rule with no
`transform-box`/`origin` (the base rule has it), for example
`".c-skull.r-load .tJaw{animation:fxJaw .2s infinite alternate}"`:

| Einstein `.tHair` | Skull `.tJaw` |
|---|---|
| `load`, `ask`, `music`, `workout`: fxHair | `load`, `ask`, `music`, `soon`, `notice`: fxJaw |
| `error`: fxHairD | `error`, `memory`: fxJawO |
| `meeting`: `animation:none` | `meeting`: `animation:none` |

That is 6 and 8 non-empty entries, about 70 bytes of CSS each. In the file's
own format, all 28 entries measure 2,806 bytes, so `REACT` lands at about
39,000 bytes, under 40,960. If it does not fit, we stop and ask. Other characters' entries
are not trimmed.

### 5. Server, Settings, docs

- `app/server.py:437`: `CHARACTERS` gets `"einstein", "skull"`. `look.character`
  and the `voice_by_character` keys are both checked by `character_ok`
  (`:443`, `:9704`), and `voice_key` (`:5640`) applies the override, so nothing
  else changes on the server.
- Settings → Look builds the Character grid and the voice select from
  `CHARACTERS` (`:4444-4447`). The grid wraps from 4 to 6 tiles.
- `docs/GUIDE.md:326-333`: two rows in the character table.

## Alternatives rejected

- **Plugin characters**: one flat fill, the Devil's geometry, no `touch`
  part.
- **More `devil ||` branches** instead of `paint`: three places, each with
  three branches, and the next character would add more.
- **Stroke rings in `front` for the sockets**: at the gaze extremes and the
  talk swell they would draw over the eye whites, and the two rings would
  collide at the nose bridge. Filled sockets in `back` sit under the eyes
  instead.
- **Filled sockets with no Nixi eyes**: the Skull would lose the face rig.
- **Raising the `REACT` cap**: the approved intent keeps it.
- **Theme-following colours**: a theme-coloured skull stops being bone.
- **Rewording "Voice for the …" for everyone**: `the:false` changes only
  Einstein's label.

## Risks

- **The Devil's look changes** through `paint`, in the preview or live, on
  p620 and razer alike. Covered by zero-diff pixel checks against
  `origin/main` (Verification).
- **Plugins pick up the Devil's palette or rim.** The existing fixture checks
  only the fill. Covered by `paint:null` and new rim checks.
- **`REACT` goes over 40 KB.** We stop and ask.
- **Einstein's hair** clips at ±96 or blocks the headphones or the weather.
  The fit test catches it, and the fix is a narrower hair cloud.
- **Settings grid** with 6 tiles at small sizes.
- **Code screen** (Nixi at work): it fits into `faceBox`. The moustache and
  teeth must not cover it.

## Verification

All browser checks use headless Chromium with `--disable-gpu` (#138), through
each test's own launcher.

- `tests/test_character_fit.py`: new `test_einstein` and `test_skull` run the
  full `char` cases (registry, eyes against `.avoid`, cups, bounds, touch,
  accent, grid pick and save, reload) and do not skip. The existing four and
  `plug:fixture` still pass.
- `plugpage` (`character_fit.mjs:80-106`) also checks two things: after
  switching from the Devil to `plug:fixture`, `#stage` has no `--rim` and the
  live rim stroke is not `#5c0a1c`; and the plugin's Settings tile ball uses
  its flat fill.
- `pixels` mode takes a character id and also captures the Settings grid
  tile. For the Devil, both the live body and the tile match `origin/main`
  with zero differing pixels. Snowflake keeps its current check.
- `tests/react_fit.mjs`: the three character lists (`:29`, `:50`, `:214`)
  include the new ids. Step 5 (`:174-199`, fixed palette ignores body colour
  in the live body and in all three previews) also runs for `einstein` and
  `skull`. A new check: during `r-load` the `.tHair` / `.tJaw` animation name
  is `fxHair` / `fxJaw`.
- `tests/test_react_art.py` with `CHARS` extended: passes, and `REACT` is
  under 40,960 bytes. A new test runs the same `BAD` regex over the new
  registry art strings in `CHARACTERS` (back and front for `einstein` and
  `skull`).
- `tests/stage_focus_fit.mjs` (`:104`, `:123`) includes the new ids.
- `tests/settings_fit.mjs` passes. The Character grid shows all 6 tiles
  without clipping at the 60% and 100% sizes.
- `tests/test_look_character.py` and `tests/test_character_voice.py`: the new
  ids are accepted, saved and still there after a reload. A
  `voice_by_character` override for `skull` is what `voice_key()` returns,
  and without one the voice from the Voice tab applies.
- Full `python -m pytest tests` passes.
- A visual check: headless PNGs of both previews and both live bodies on light
  and dark backgrounds (neutral, happy, talking, blinking, with headphones and
  with a hat on the Skull). I look at them and attach them to the PR.
- No plugin sandbox run is needed: `app/plugins.py`, the sandbox test and
  `nix/package.nix` are untouched (README "Working on it").
