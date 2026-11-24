---
status: draft
issue: 118
intent: intent/2026-11-24-118-einstein-skull.md
---

# Spec: two new characters, Einstein and a white-bone Skull

## Design

Two built-in characters, `einstein` (label "Einstein") and `skull` (label
"Skull"), are added after `devil` in the same registry. They have a fixed
palette like the Devil and one `touch` part each, and their voices stay on My
voice. (These were the intent's recommendations, approved in `56791d5`.)

### 1. A fixed palette for any character, not only the Devil

Today the Devil's colours are special-cased in three places:

- `miniNixi` (`app/static/index.html:1397-1403`): `devil` builds `devBody` /
  `devWing` gradients per preview, sets the rim to `#5c0a1c`, and rewrites
  `url(#devBody)`, `url(#devWing)` and `var(--rim)` in the art.
- `setCharacter` (`:1912-1913`): `next===CHARACTERS.devil` picks
  `url(#devBody)` for the ball and sets `--rim` on `#stage`.
- the live `<defs>` (`:859-860`): static `devBody` / `devWing` gradients.

Adding two more characters this way would mean three more `||` branches in
each place. Instead each fixed-palette character gets one field:

```js
paint:{ball:'devBody', rim:'#5c0a1c', grads:[
  ['devBody','radialGradient',{cx:-24,cy:-30,r:118},['#e0334f','#c81e3a','#7a0f24']],
  ['devWing','linearGradient',{x1:0,y1:-16,x2:0,y2:86},['#e0334f','#c81e3a','#7a0f24']]]}
```

(stops sit at 0, .55 and 1, as today).

- `miniNixi` builds `character.paint.grads` with the preview's id prefix,
  fills the ball with `url(#<id><paint.ball>)`, uses `paint.rim`, and rewrites
  every `url(#<grad>)` and `var(--rim)` in the art. Without `paint`, the
  behaviour is unchanged.
- `setCharacter` fills the ball with `url(#<paint.ball>)` and sets `--rim`
  from `paint.rim`. Without `paint`, it uses `url(#ballG)` and removes `--rim`,
  as today.
- The live `<defs>` builds the gradients from the registry once at load, into
  one `<g id="paintDefs">` inside the existing `<defs>`. The static
  `devBody` / `devWing` lines are removed. The Devil keeps the same ids, stops
  and coordinates, so his pixels do not change.
- `plugChars` (`:1454`) spreads `...CHARACTERS.devil`, so it must set
  `paint:null`. Otherwise every plugin character would inherit the Devil's
  palette.
- Any other `CHARACTERS.devil` check that is about colour (not the tail or the
  fork) moves to `paint`. The fork and tail CSS (`:31-32`) stay Devil-only.

### 2. Einstein

A caricature. Every shape is drawn here and is not copied from existing art.

- **ball**: a slightly tall rounded head, about the Devil's size (x ±84,
  y -80…84).
- **paint**: skin `einSkin` radial (`#f8d9bd`, `#eab894`, `#b47a55`), hair
  `einHair` linear (`#ffffff`, `#e4e7ec`, `#aeb4bf`), rim `#6e4328`.
- **back** (behind the head): a wide, bumpy white cloud of hair, on the top
  and both sides, wider than the head (to about x ±100, y -112), plus two ears
  at the eye line. A tuft on top is the `touch` part, `<g class="tHair">`.
- **front** (over the eyes): bushy grey-white eyebrows above the eyes (around
  y -62) and a big drooping moustache under them (around y 40-62). They carry
  `class="avoid"` like the Devil's brows and mouth. A few forehead lines are
  optional.
- **fits**: `none, halo, bow, scarf, tie, headphones, shades, glasses, chat,
  feed, plug`. Hats are dropped, as for the Robot: they would float on the
  hair.
- **geometry**: `faceBox`, `anchors`, `cupX`, `band`, `pivot` and `shadow`
  start from the Devil's values. `cupX` and `band` widen so the headphone
  cups sit on the hair, not inside it. The fit test sets the final values.
- **touch**: the hair tuft sways (`fxHair`). It shakes faster while he is
  working (`load`, `ask`, `music`, `workout`), droops on `error`, and is
  still on `meeting`.

### 3. Skull

White bone, cartoon-friendly (no gore).

- **ball**: a skull outline: a round cranium, cheekbones that bulge slightly at
  the eye line, and a narrower jaw (x ±86 at the cranium, about ±60 at the jaw,
  y -82…88).
- **paint**: bone `sklBone` radial (`#fdfaf2`, `#ece3cc`, `#b3a68a`), rim
  `#5f533f`. On a white desktop the rim and the shade on the bottom edge set
  the shape apart, and on a dark desktop the bone stands out.
- **eye sockets**: Nixi's eyes stay. The front layer draws a dark socket ring
  around each eye: an ellipse a few units larger than the eye oval (EYE: ±25.5,
  -4.5, 23.5 × 40.5, tilted 9°), stroke `#3a3226` 6-7 wide, no fill. The eye
  whites and pupils stay visible inside. (The front layer is drawn after the
  eyes in both `miniNixi` and the live body, so a filled socket would hide
  them. A stroke ring is the only way.)
- **front**: an upside-down heart nasal hole (dark, around 0,44), and a row of
  teeth with lines between them in the jaw (around y 60-80). The teeth are the
  `touch` part, `<g class="tJaw">`, and all of it carries `class="avoid"`. One
  small crack on the cranium is optional.
- **fits**: `none, halo, crown, bow, nightcap, beanie, party, scarf, tie,
  headphones, shades, glasses, chat, feed, plug`. The cranium is round like
  the Devil's, so hats fit. `sprout` is dropped.
- **geometry**: starts from the Devil's. The fit test sets the final values.
- **touch**: the jaw chatters (`fxJaw`, a small translateY of 2-3 units) on
  `load`, `ask`, `music`, `soon` and `notice`, drops open on `error` and
  `memory`, and is still on `meeting`.

### 4. Reactions within the 40 KB cap

`REACT` is 36.2 KB today, and each character's `touch` block takes about
3.2 KB, because each entry repeats its own `@keyframes`. Two more at that size
would break the cap. So:

- The new keyframes (`fxHair`, `fxHairF`, `fxJaw`, `fxJawF`) go in the
  page's main stylesheet, next to the Devil's fork rules (`:31-32`), and not
  inside `REACT`.
- Each `REACT.touch.einstein.<id>` and `REACT.touch.skull.<id>` entry is
  `{"back":"","front":"","css":"<one selector>{animation:…}"}`. That is about
  100-150 bytes each, about 2 KB per character, so `REACT` ends up at about
  40 KB or less. If it does not fit, we stop and ask. We don't trim other
  characters' entries.
- All 14 reaction ids get an entry for both, in the same order as
  `test_react_art.IDS`.

### 5. Server, Settings, docs

- `app/server.py:437`: `CHARACTERS` gets `"einstein", "skull"`. `look.character`
  and the `voice_by_character` keys are both checked against that tuple
  (`:443`), so nothing else changes on the server.
- Settings → Look builds the Character grid from `CHARACTERS` (`:4444`), so
  the two tiles and the Voice for the … select appear without changes. The
  grid wraps from 4 to 6 tiles, and this is checked at 60% and 100% size.
- `docs/GUIDE.md:326-333`: two rows in the character table.

## Alternatives rejected

- **Plugin characters** (`plug:<id>`): one flat fill, the Devil's geometry, no
  `touch` part. That cannot draw Einstein's wide hair or a two-tone skull.
- **More `devil ||` branches** instead of `paint`: three places, each with
  three branches, and the next character would add more. `paint` is one field
  and removes the existing special case.
- **Filled eye sockets with no Nixi eyes**: the face rig (moods, blinking,
  talking) is the product. Empty holes would make the Skull the only
  character without it.
- **Raising the `REACT` cap**: the approved intent keeps it, and short entries
  plus keyframes in the stylesheet fit.
- **Theme-following colours**: a theme-coloured skull stops being bone.

## Risks

- **The Devil's look changes** through the `paint` refactor, in the preview or
  live, on p620 and razer alike. Covered by a pixel check of the Devil against
  `origin/main` (see Verification).
- **Plugin characters inherit `paint`** through `...CHARACTERS.devil`. Covered by
  `paint:null` in `plugChars` and the existing `plug:fixture` test.
- **`REACT` goes over 40 KB.** `test_react_art` fails, and we stop and ask.
- **Art outside the body box**: Einstein's hair is wider than the other
  bodies, so it can be clipped at the window edge or overlap the headphones
  and weather. `character_fit.mjs` checks the bounds. If the hair is clipped,
  it gets narrower; the window does not grow.
- **Settings grid layout** with 6 tiles at small sizes. Checked by
  `settings_fit.mjs` and the grid case in `character_fit.mjs` (it counts
  `Object.keys(CHARACTERS)`).
- **Code screen** (Nixi at work): it fits into `faceBox`. The Skull's sockets
  and Einstein's moustache must not cover it. Checked by `stage_focus_fit.mjs`
  once it lists the new ids.

## Verification

All browser checks use headless Chromium with `--disable-gpu` (#138), through
each test's own launcher.

- `python -m pytest tests/test_character_fit.py`: new `test_einstein` and
  `test_skull` pass and do not skip. The existing four and `plug:fixture`
  still pass.
- The `pixels` mode of `character_fit.mjs` (Snowflake vs `origin/main`) is
  extended to the Devil, preview and live, and both are identical.
- `tests/test_react_art.py` with `CHARS` extended: passes, `REACT` < 40 KB.
- `tests/react_fit.mjs`, `tests/stage_focus_fit.mjs`: the character lists
  include the new ids, and all pass.
- `tests/test_look_character.py`, `tests/test_character_voice.py`: the new
  ids are accepted and saved, a `voice_by_character` override is used, and
  without one the voice from the Voice tab applies.
- Full `python -m pytest tests` passes.
- A visual check: headless PNGs of both previews and both live bodies (light
  and dark backgrounds, neutral, happy and talking faces, with headphones).
  I look at them and attach them to the PR.
- No plugin sandbox tests are needed: no plugin or stage code changes (README
  "Working on it").
