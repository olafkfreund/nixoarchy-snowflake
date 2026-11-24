---
status: draft
issue: 118
author: olafkfreund
---

# Intent: two new characters, Einstein and a white-bone Skull

## Problem

Settings → Look → Character offers four bodies: Snowflake, Terminal, Robot and
Devil (`CHARACTERS` in `app/server.py:437` and `app/static/index.html:1429-1446`).
The owner wants two more:

1. **Albert Einstein**: a cartoon caricature, recognisable by the white
   wild hair and the moustache.
2. **Skull**: a white-bone skull.

Plugin characters (`plug:<id>`, #213) can already add a body without code, but
they are limited to flat colours, the Devil's sizes, and no reactions of their own.

## Proposed outcome

- Settings → Look → Character shows **Einstein** and **Skull** next to the
  other four, with previews drawn from the same registry, and the choice is
  saved in `look.character` like the others.
- Both wear the live eye rig: pupils, moods, blinking, talking and the reaction
  props work as they do on the Devil. The face stays readable, so the
  skull's eye sockets hold Nixi's eyes, not empty holes.
- Each has a fitting set of skins (`fits`). Each can have its own voice under
  Voice for the … (`voice_by_character`), like the other four.
- The Skull reads as white bone on both a light and a dark desktop.

## Affected users and systems

- `app/static/index.html`: the `CHARACTERS` registry, gradients, character CSS
  and the Settings grid.
- `app/server.py`: the `CHARACTERS` tuple that validates `look.character`.
- Tests: `tests/test_character_fit.py`, `tests/react_fit.mjs`,
  `tests/test_react_art.py`, `tests/test_look_character.py`.
- `docs/GUIDE.md` character table.
- Runs on p620 and razer, with no Nix or system changes.

## Constraints

- Existing characters and saved configs must not change. An unknown character
  still falls back to Snowflake.
- No new dependencies. The art is inline SVG like the other bodies.
- Einstein is a caricature, not a photo or a copied piece of art.
- Previews follow the memory rule: headless Chromium with `--disable-gpu`, never
  a GPU Chrome on the desktop.
- Codex and agy implement the steps in the approved plan. Their output is advice
  until I review it.

## Open questions

1. **Built-in or plugin?** I recommend built-in like the Devil: it allows
   gradients, its own reactions and the full test harness. A plugin would be
   smaller but stuck with flat colours and the Devil's sizes.
2. **Label:** "Einstein", or a generic "Professor" with the same look?
   Einstein's name and likeness are licensed commercially. For a personal
   open-source app the risk is small, but it is your call.
3. **Reactions:** add a signature motion for each one (Einstein's hair shakes
   when he is working; the Skull's jaw chatters when he talks), or reuse
   the default reactions only? I recommend one small motion each.
4. **Default voices:** leave them on "My voice", or set Einstein → `deep` and
   Skull → `story`? I recommend leaving them alone (see the memory note on
   voices) unless you want this.
