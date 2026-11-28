---
status: draft
issue: 133
spec: spec/2026-11-28-133-showcase-docs-version.md
coders:
  1: claude   # manager: the capture harness facts were gathered in-session; a handoff re-reads them
  2: claude   # manager: README prose needs the captures from step 1 viewed first
  3: claude   # manager: Guide prose drawn from specs #121/#126 already read in-session
  4: claude   # manager: two-line version change
  5: claude   # manager: git rm only
reviewers:
  - codex     # plan review (agent-team default)
  - codex     # diff review: a provider other than the implementer (Claude)
---

# Plan: a current showcase, docs for the latest features, one version

Decisions carried from the approved spec:

- New pictures are page renders from a headless Chromium with the GPU
  off, a throwaway home and runtime folder, and fixture data only. They
  are made by a committed script so they can be made again.
- README gets a **See him** gallery after **What it is**, and two **Next**
  lines (WhatsApp, placing calls).
- Guide gets `### WhatsApp` and `### Place calls` under **Your phone**,
  and `card_text` in the settings reference.
- Version 1.7.0 in `app/VERSION`; `nix/package.nix` reads that file.
  After merge, tag `v1.7.0` and publish a release (the update check reads
  this repo's `releases/latest`).
- Void's `assets/demo/*.webp` and `assets/void.png` are deleted.
- Stills, not animations; no montage tool.

## Steps

1. **Captures.** New `docs/media/capture.py` and `docs/media/capture.mjs`.
   - `.py`: like `tests/test_character_fit.py` `setUpClass`/`_serve`:
     `sys.path` gets `tests/`, start `start_browser(chromium, cdp, dir)`
     and `app/server.py` with `nixi_env.server_env(env, home)` in a
     `tempfile.mkdtemp` home holding only `{"port": N}`; read the token
     from `runtime.json`; run `node capture.mjs <cdp> <url> <outdir>`;
     terminate both and remove the home in `finally`.
   - `.mjs`: open a tab at `url` with `/?native=1#`, wait 4.5 s, set
     `nextFidAt=1e15` and `idle_mode:'off'` like `tests/handset_fit.mjs:23`;
     then for each id in `snowflake terminal robot devil einstein skull`
     `setCharacter(id)` at 340×460 and screenshot `char-<id>.png`; then
     the `wa_thread` fixture from `tests/stages_fit.mjs:734` with
     `onEvent`, viewport `340+stageWant[0]`, `nixiLayout(0,0)`, save
     `whatsapp.png`; then `stageClose()` and the handset `base` event
     from `tests/handset_fit.mjs:29` (who "Ada Lovelace"), viewport
     `340+callWant[0]`, save `handset.png`.
   → verify: `nix develop -c python3 docs/media/capture.py` writes 8 PNGs
   in `docs/media/`; view each.
   Traps: never a GPU browser or the live desktop; never the real HOME or
   `XDG_RUNTIME_DIR` (memories: no GPU Chrome, test servers use nixi_env).

2. **README** `README.md`: after **What it is** (line 17), a `## See him`
   section: an HTML row of the six `char-*.png` at width 120 with alt
   text, a caption line naming the characters and linking
   `docs/GUIDE.md#characters-and-their-voices`; then a row of
   `docs/media/message.png`, `whatsapp.png`, `handset.png` with captions.
   In **Next**, add WhatsApp and placing calls lines linking the new
   Guide anchors.
   → verify: the link check under Tests.
   Traps: README is the setup guide; the gallery stays short.

3. **Guide** `docs/GUIDE.md`:
   - after **Take calls on Nixi** (ends line 192), `### Place calls`;
   - then `### WhatsApp`: option `services.nixi.companion.whatsapp.enable`
     (nixi's Home Manager module), the **WhatsApp** switch on the Phone
     tab, pairing by QR from "read my whatsapp" when unpaired, phrases
     from `app/lang/en.json` `wa_read`/`wa_open`/`wa_summary`/`wa_file`/
     `wa_reply`, the card buttons, the limits (sending to direct chats
     only, groups read and download only, every send is a click, voice
     notes not played, summaries use Claude on one open direct chat and
     are never saved, cards hidden from agent captures), and **Unlink and
     forget**;
   - in the settings table, `card_text` `1.0`: card text scale, 0.6–2.0,
     also `nixi-companion text up|down|reset`.
   → verify: the link check under Tests.
   Traps: facts only from specs #121/#126 and the code; no invented
   options.

4. **Version** `app/VERSION` → `1.7.0`; `nix/package.nix:54`
   `version = lib.fileContents ../app/VERSION;`.
   → verify: `nix eval .#default.version` prints `"1.7.0"`;
   `nix build .#default` succeeds.
   Traps: none.

5. **Remove Void demos**: `git rm assets/demo/*.webp assets/void.png`.
   → verify: `grep -rn 'assets/demo\|void.png'` outside `.git` and
   `graphify-out` finds nothing.
   Traps: keep the fork credit line in the README.

## Tests

- Link check: every `src=`/`](...)` path in README and GUIDE exists:
  `grep -oE '(src="|\]\()[^")#]+' README.md docs/GUIDE.md` then `test -f`.
- `nix develop -c python3 -m unittest discover -s tests`: no failures that
  `main` does not also have. No code behaviour changes, so the plugin
  sandbox run is not required (README "Working on it").

## After merge

`git tag v1.7.0 <merge commit> && git push origin v1.7.0`, then
`gh release create v1.7.0` with a short feature list.

## Rollback

Revert the PR. If released, `gh release delete v1.7.0 --cleanup-tag`.
