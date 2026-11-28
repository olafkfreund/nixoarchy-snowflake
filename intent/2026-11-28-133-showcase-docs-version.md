---
status: approved
issue: 133
author: olafkfreund
---

# Intent: a current showcase, docs for the latest features, one version

## Problem

- **No showcase.** The README shows the icon and one Settings screenshot.
  The nine animations in `assets/demo/` were made by the upstream Void
  author (2026-10-12/15) and show Void's black orb, not the snowflake.
  Nothing links them, and they add about 12 MB to the package source.
- **Docs lag the features.** WhatsApp (#126) has one line in the Guide
  and no setup or use. Placing calls (#121) is not documented. The
  `card_text` setting (#109) is missing from the settings reference. The
  README does not mention WhatsApp, placing calls, or the six characters.
- **Versions disagree.** `app/VERSION` is 1.6.3, last bumped 2026-10-23,
  with about 600 commits since. `nix/package.nix` says `0.1.0`. There are
  no tags or releases, so the update check (`UPDATE_URL`, this repo's
  `releases/latest`) never finds one.

## Proposed outcome

- The README opens with a small gallery of current captures: the six
  characters, a WhatsApp chat card and the call handset.
- The Guide explains how to turn WhatsApp on, pair it, and what to say,
  and how to place a call. `card_text` is in the settings reference. The
  README's "Next" list points to both.
- One version number, 1.7.0, read by both the app and the package, with
  a GitHub release `v1.7.0` once merged.

## Affected users and systems

README, `docs/GUIDE.md`, `app/VERSION`, `nix/package.nix`, `assets/`.
Users whose update check is on see "1.7.0 available" once the release is
out, until they update.

## Constraints

- Captures come from a headless Chromium with the GPU off, a throwaway
  home and runtime folder (memory: GPU Chrome hung the AMD GPU; test
  servers use `nixi_env`). Never the live desktop or the live config.
- Captures show only fixture data, no real contacts or messages.
- No code behaviour changes.

## Open questions

None: the owner pre-approved intent, spec and plan (2026-11-28).
