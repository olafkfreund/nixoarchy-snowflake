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
   - `.py`: one throwaway environment, built once and passed to **both**
     children: a copy of `os.environ` without `WAYLAND_DISPLAY`,
     `DISPLAY`, `DBUS_SESSION_BUS_ADDRESS` and
     `HYPRLAND_INSTANCE_SIGNATURE`, with `HOME`, `XDG_CONFIG_HOME`,
     `XDG_DATA_HOME`, `XDG_STATE_HOME`, `XDG_CACHE_HOME` in a
     `tempfile.mkdtemp` home, through `nixi_env.server_env(env, home)`
     (adds `XDG_RUNTIME_DIR`). `start_browser(chromium, cdp, dir, env=env)`
     and `app/server.py` with that env. The config holds
     `{"port": N, "update_check": false}`. Wait for both like
     `tests/test_character_fit.py:_serve`, read the token from the
     throwaway `data/nixi-companion/runtime.json`, run
     `node capture.mjs <cdp> <url> <outdir>`, then terminate both and
     remove the home in `finally`.
   - `.mjs`: open a tab at `url` with `/?native=1#`, wait 4.5 s, set
     `nextFidAt=1e15` and `idle_mode:'off'` like `tests/handset_fit.mjs:23`;
     then for each id in `snowflake terminal robot devil einstein skull`
     `setCharacter(id)` at 340×460 and screenshot `char-<id>.png`.
   - WhatsApp: a `wa_thread` fixture like `tests/stages_fit.mjs:734` with
     made-up names, shown the way `stages_fit.mjs:55` `show` does
     (`stageClose`, `onEvent`, resize to `340+stageWant[0]`, then
     `nixiLayout(0,0)`, wait 700 ms); **assert** `stgState==='open'`, the
     `#stg` box is inside the viewport and holds the fixture text, then
     save `whatsapp.png`.
   - Handset: the `base` "host ringing" event from
     `tests/handset_fit.mjs:29` (who "Ada Lovelace", an incoming call),
     shown like `handset_fit.mjs:44` `show` (`onEvent`, resize to
     `340+callWant[0]`, `nixiLayout`, wait 500 ms); **assert** `#handset`
     is visible, in the viewport and shows "Ada Lovelace", then save
     `handset.png`. Any failed assert exits non-zero and saves nothing
     for that card.
   → verify: `nix develop -c python3 docs/media/capture.py` writes 8 PNGs
   in `docs/media/`; view each.
   Traps: never a GPU browser or the live desktop; never the real HOME,
   runtime folder or `runtime.json` (memories: no GPU Chrome, test
   servers use nixi_env); no network update request.

2. **README** `README.md`: after **What it is** (line 17), a `## See him`
   section: an HTML row of the six `char-*.png` at width 120 with alt
   text, a caption line naming the characters and linking
   `docs/GUIDE.md#characters-and-their-voices`; then a row of
   `docs/media/message.png`, `whatsapp.png`, `handset.png` with captions
   (the handset caption says an incoming call).
   In **Next**, add WhatsApp and placing calls lines linking the new
   Guide anchors.
   → verify: the link check under Tests.
   Traps: README is the setup guide; the gallery stays short.

3. **Guide** `docs/GUIDE.md`:
   - after **Take calls on Nixi** (ends line 192), `### Place calls`:
     needs Phone on, the computer unlocked and the phone's Bluetooth
     hands-free link (the Host path); "call Anna" / "dial <number>";
     with several phones a "Which phone?" card; a name is looked up in
     the phone's contacts (needs **Contact sharing** in the phone's
     Bluetooth settings) and several matches give a "Which number?"
     card; a number goes straight to the confirmation card; only the
     click on **Call** dials; emergency and short numbers are refused;
     the handset shows **Calling…** with hang-up, then the in-call
     controls;
   - then `### WhatsApp`: option `services.nixi.companion.whatsapp.enable`
     (nixi-nixarchy's Home Manager module), the **WhatsApp** switch,
     **Pair** and **Unlink and forget** on the Phone tab (the switch shows
     only once the option is on; WhatsApp does not need Phone on), pairing by QR from "read my whatsapp" when unpaired, phrases
     from `app/lang/en.json` `wa_read`/`wa_open`/`wa_summary`/`wa_file`/
     `wa_reply`, the card buttons, the limits (sending to direct chats
     only, groups read and download only, every send is a click, voice
     notes not played; "summarise my whatsapp with X" only opens the chat,
     and the **Summarise** click sends at most 50 messages or 8,000
     characters of that one open direct chat to Claude, never saved to
     session history; cards hidden from agent captures), and **Unlink and
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
   → verify: `git ls-files assets/demo assets/void.png` is empty, and
   `grep -n 'assets/demo\|void.png' README.md docs/*.md app nix bin` finds
   nothing.
   Traps: keep the fork credit line in the README.

## Tests

- Link check: each new image path in README exists (`test -f` on the
  eight `docs/media/*.png`), and each new `GUIDE.md#anchor` the README
  links matches a heading in `docs/GUIDE.md` (GitHub slug: lower case,
  spaces to `-`, punctuation dropped).
- `nix develop -c python3 -m unittest discover -s tests`: no failures that
  `main` does not also have. No code behaviour changes, so the plugin
  sandbox run is not required (README "Working on it").

## After merge

The release is safe for existing installs (`app/server.py` `Updates`):
bridged installs (the nixi setup) never check; Nix installs are
"manual" and only get a banner linking the release page; git installs
`git pull --ff-only` main. The release carries no package assets, so
`.deb`/`.rpm`/Arch installs see the link only.

`git tag v1.7.0 <merge commit> && git push origin v1.7.0`, then
`gh release create v1.7.0` with a short feature list.

## Review

Codex (gpt-6.2-astra) plan review, 2026-11-28: findings 1 (env to both
children), 2 (assert the cards rendered), 4 (call flow), 5 (summary and
module wording), 6 (checks), 7 (`update_check: false`) confirmed and
folded in. Finding 3 (release) checked against `Updates`: confirmed for
package installs (banner link only), refuted as a breakage risk; noted
under After merge.

## Rollback

Revert the PR. If released, `gh release delete v1.7.0 --cleanup-tag`.
