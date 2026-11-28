---
status: approved
issue: 133
intent: intent/2026-11-28-133-showcase-docs-version.md
---

# Spec: a current showcase, docs for the latest features, one version

## Design

### 1. Captures, reproducible

`docs/media/capture.py` makes every new picture, so they can be made
again when the look changes:

- It reuses the test harness: `tests/_browser.start_browser` (headless,
  `--disable-gpu`, SwiftShader) and `tests/nixi_env.server_env`, with a
  throwaway home like `tests/test_character_fit.py:_serve`.
- `docs/media/capture.mjs` drives the page over CDP (the same `Tab`
  pattern as `tests/character_fit.mjs`) and saves PNGs:
  - `char-<id>.png` for `snowflake terminal robot devil einstein skull`,
    through the page's `setCharacter(id)` at 340×460;
  - `whatsapp.png`: the `wa_thread` fixture from `tests/stages_fit.mjs`
    (made-up names) shown with `onEvent`;
  - `handset.png`: the "host ringing" handset, the same event
    `tests/handset_fit.mjs` uses, with a made-up caller.
- Run by hand, not by the test suite: `nix develop -c python3 docs/media/capture.py`.

### 2. README

- A **See him** section right after **What it is**: a row of the six
  character captures, then the WhatsApp card, the handset and the
  existing `docs/media/message.png`, each with a one-line caption.
- **Next** gains two lines: WhatsApp and placing calls, linking the new
  Guide sections.

### 3. Guide

- A `### WhatsApp` section under **Your phone**: the Nix option
  `services.nixi.companion.whatsapp.enable`, the **WhatsApp** switch on
  the Phone tab, pairing by QR code, what to say (from
  `app/lang/en.json` `wa_*` phrases), what the cards do, and the limits
  from spec #126 (direct chats only for sending, groups read-only, every
  send is a click, summaries use Claude on one open chat, Unlink and
  forget).
- A `### Place calls` section after **Take calls on Nixi**: "call Anna"
  or a number, the pick and confirm cards, a real click places the call,
  host Bluetooth needed.
- `card_text` added to the settings reference table.

### 4. One version

- `app/VERSION` becomes `1.7.0` (new features since 1.6.3).
- `nix/package.nix` reads it: `version = lib.fileContents ../app/VERSION;`.
- After merge: tag `v1.7.0` on the merge commit and publish a GitHub
  release with a short feature list.

### 5. Remove Void's demos

Delete `assets/demo/*.webp` and `assets/void.png`: upstream's look,
unreferenced in code and docs, about 12.8 MB in every package source.
The README keeps the fork credit.

## Alternatives rejected

- **Use the Void animations.** They show a different character.
- **Animated captures (webp).** Needs frame timing and an encoder; stills
  carry the showcase. A later task can add animation.
- **Screenshots from the live desktop.** Risks the GPU hang and real
  personal data.
- **Montage into one image.** Six `<img>` tags need no extra tool and
  stay sharp.

## Risks

- Users with `update_check` on see the update banner once `v1.7.0` is
  out; that is the intended signal.
- `lib.fileContents` fails evaluation if `app/VERSION` is missing; it is
  tracked, and `nix build` proves it.
- Captures could drift from the real window chrome; they are page
  renders at the window's default size.

## Verification

- `nix develop -c python3 docs/media/capture.py` writes the 8 PNGs; each
  is viewed before commit.
- `nix build .#default` succeeds and `result` reports version 1.7.0
  (`nix eval .#default.version`).
- Every image and anchor the README and Guide link exists
  (a grep-and-test-f loop).
- `nix develop -c python3 -m unittest discover -s tests` shows no new
  failures against `main`.
