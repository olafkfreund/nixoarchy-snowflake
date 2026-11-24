---
status: approved
issue: 118
author: olafkfreund
---

# Intent: two new characters, Einstein and a white-bone Skull

## Problem

Settings → Look → Character offers four bodies: Snowflake, Terminal, Robot and
Devil (`CHARACTERS` in `app/server.py:437` and `app/static/index.html:1429-1447`).
The owner wants two more:

1. **Albert Einstein**: a cartoon caricature, recognisable by the white
   wild hair and the moustache.
2. **Skull**: a white-bone skull.

Plugin characters (`plug:<id>`, #213) can already add a body without code, but
they take one flat fill, the Devil's geometry, `touch: null`, and no
plugin-defined reaction art or motion (`index.html:1448-1454`,
`docs/GUIDE.md:482-489`).

## Proposed outcome

- Settings → Look → Character shows **Einstein** and **Skull** next to the
  other four, and the choice is saved in `look.character` like the others.
- The Settings preview (`miniNixi`) and the live body (`setCharacter`) look the
  same, and both show each character's identifying features.
- Both wear the live eye rig: pupils, moods, blinking and talking work as they
  do on the Devil. The Skull's eye sockets frame Nixi's eyes (the fixed eye
  ovals around (±25.5, -4.5)), so the face stays readable.
- The shared reaction props, the headphone cups and band, the weather and the
  skins all sit right on both bodies. Each body gets its own `cupX`, `band`,
  `anchors`, `faceBox` and `fits`. Einstein's hair is wide, so hats and
  headphones need their own fit.
- Each can have its own voice under Voice for the … (`voice_by_character`):
  the override is accepted, saved and used, and without one the voice in the
  Voice tab applies.
- The Skull reads as white bone on both a light and a dark desktop.

## Affected users and systems

- `app/static/index.html`: the `CHARACTERS` registry, gradients and rim,
  `miniNixi` (`:1393-1403`) and `setCharacter` (`:1910-1920`). Both hard-code
  the Devil as the only character with a fixed palette. Also the character CSS,
  the `REACT` entries per character, and the Settings Character grid and voice
  select.
- `app/server.py`: the `CHARACTERS` tuple, which validates `look.character`
  and `voice_by_character`.
- Tests: `tests/test_character_fit.py` with `tests/character_fit.mjs` (one
  test per character), `tests/react_fit.mjs`, `tests/test_react_art.py`
  (`CHARS`, safe-SVG rules, 40 KB cap on `REACT`),
  `tests/test_look_character.py`, `tests/test_character_voice.py`.
- `docs/GUIDE.md` character table.
- Runs on p620 and razer, with no Nix or system changes.

## Constraints

- Existing characters and saved configs must not change. An unknown character
  still falls back to Snowflake.
- No new dependencies. The art is inline SVG like the other bodies, and it
  passes the safe-SVG rules in `tests/test_react_art.py`. `REACT` stays under
  its 40 KB cap.
- Einstein is a drawn caricature, not a photo or a copy of existing art.
- Fit tests and previews use software rendering only (`--disable-gpu`): GPU
  Chrome previews hung the AMD GPU twice (#138).
- Both new ids get a passing fit test and a saved-config test; a test that
  skips on missing art does not count.
- Codex and agy implement the steps in the approved plan. Their output is advice
  until I review it.

## Open questions

1. **Built-in or plugin?** I recommend built-in like the Devil. A plugin can't
   have gradients, its own geometry (for Einstein's hair) or its own motion.
2. **Name and saved id:** `einstein` / "Einstein", or `professor` /
   "Professor" with the same look? The id is stored in configs, so it can't
   change later without a migration. I haven't checked whether licensing his
   name or likeness matters for this app, so this is your call.
3. **Palette:** do both ignore the body colour and Follow desktop theme like the
   Devil (white bone stays white; Einstein keeps his skin and white hair)? I
   recommend yes, because a theme colour would turn the Skull into something
   other than bone.
4. **Motion:** besides the shared reactions, give each one a `touch` part
   that moves like the Devil's tail does (Einstein's hair tuft, the Skull's
   jaw)? I recommend yes for `touch` only, with no new per-state animations,
   to stay within the `REACT` budget.
5. **Default voices:** I recommend leaving both on My voice. You chose
   ElevenLabs for Nixi and turned down per-character voices before.
