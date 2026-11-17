---
status: approved
issue: 99
intent: intent/2026-11-17-99-nixi-settings-sync.md
---

# Spec: keep Nixi's settings and plugins the same on every machine

## Design

The order is **built-in defaults → a shared file from Nix → local
overrides**, for every program that reads Nixi settings: the companion, the
bridge, the bar card and `doctor`. Shared values arrive as read-only files of
their own. A deploy never writes `config.json`, `nixi.json` or
`plugins-state.json`.

### 1. Declaring it: Nixi's own Home Manager module (nixi-nixarchy `nix/hm-module.nix`)

The module already has `services.nixi.companion.plugins` (`:180-200`),
`peers` (`:143`) and `package`. Two options are added next to them:

- `services.nixi.companion.settings` (attrs, default `{}`). When non-empty,
  it is written as `xdg.configFile."nixi-companion/shared.json"`, as
  `peers.json` already is (`:382`). Its contents:
  - the shared settings;
  - `plugins_on`: plugin ids that start on;
  - `private_plugins`: names only;
  - `voices`: piper voice name → `{onnx, json}` sha256 pairs.
- `services.nixi.settings` (attrs of `trust`, `permissionMode`, `agent`,
  `model`, `reasoningEffort`), written as
  `xdg.configFile."omarchy/nixi-shared.json"`.

nixos_config's `hosts/common/nixos/omarchy-nixi-companion.nix` sets these,
plus `companion.plugins` for `news`, `nix-status` and `rss-headlines`. The
values are today's p620 values. Empty options write nothing, so other users
of the module see no change.

The store is world-readable, so the module documents: no secrets, no private
plugins, no personal free text.

### 2. Which companion keys may be shared (`SHARED_OK` in `app/server.py`)

Every value in `shared.json` is checked by the same validator the settings
panel uses (part 4). A key outside the allowlist, or a value that fails its
check, is ignored, and `doctor` gets one line for it.

**Shared**, all of them enums, numbers, booleans, colours or lists of known
ids:

| Group | Keys |
|---|---|
| Agent | `trust` `model` `effort` `lean` `max_cost_usd` `compact_tokens` `auto_model` `partial_messages` `auto_compact` `compact_at` `agent_approvals` `agent_voice_mute` |
| Speech in | `whisper_model` `whisper_beam` `stt_hint` (text, at most 1000 chars) `mic_auto` `stt_prewarm` `ptt_hotkey` `wake_word` `listen_on_show` `barge_in` `follow_up` `live_minutes` `language` |
| Speech out | `tts` `tts_fallback` `eleven_on` `eleven_voice` (an ElevenLabs voice id) `eleven_daily_chars` `espeak_voice` `speak_max_chars` `voice` `voice_by_lang` `voice_by_character` `sfx` `full_text` |
| Look | `look` (one key, replaced whole) `size` `eye_color` `eye_white` `pupil_style` `presence` `bar_edge` `idle_mode` `step_aside` `follow_focus` `hover` `click_through` `code_panel` `code_face` |
| Features | `answer_stages` `peers_on` `ambient_system` `ambient_calendar` `ambient_weather` `proactive` `reactions` `news_watch` `notifications_takeover` `notify_details` `notify_speak` `notify_speak_subject` `notify_sound` `notify_done` `popup_done` `phone_on` `mail_on` `mail_model` `water_every` `update_check` `autostart` |
| Reactions | `look_meeting` `look_music` `look_beat` `look_fullscreen` `look_coding` `look_night` `look_weather` `look_party` `react_load` `react_break` `react_welcome` `react_quips` |

**Local-only**, never taken from `shared.json`:

| Why | Keys |
|---|---|
| Machine and devices | `port` `cpu_split` `whisper_device` `mic_device` `mic_cmd` |
| Paths and executables | `cwd` `claude_bin` `extra_args` `piper_voice` (a model path) `projects` |
| Personal free text | `voice_prompt` `quick_actions` `workout` `mail_accounts` |
| State and consent | `lang_good` `peers_asked` `root_mode` `permission_mode` (legacy) |

A key that appears in `DEFAULTS` later is local until it is added to
`SHARED_OK`. A test checks that every `DEFAULTS` key is in exactly one of the
two lists.

### 3. Companion: loading (`app/server.py`)

- **`load_config`** (`:279`) builds `cfg = DEFAULTS`, then `SHARED` (from
  `shared.json`, checked as in part 2), then `config.json`. The existing
  in-memory migrations still run on the user layer.
  - A missing `shared.json` means an empty shared layer.
  - A broken one means an empty layer plus a `doctor` line.
- **First run** stops writing all of `DEFAULTS` (`:296-302`). It writes only
  `lang_good`, plus `language` when `SHARED` has none (detected, as today).
  A shared `language` is never shadowed by detection.
- **`nixi_conf()`** (`:133`) also reads `nixi-shared.json` under `nixi.json`,
  so `trust_nixi()` (`:8353`) and `stage_trust()` (`:6703`) see the same
  bridge trust as the bridge. A test covers a trust that is shared only.
- **`save_config`** doesn't change: it writes only the keys it's given, and
  the panel saves one setting at a time (`setSetting`, `index.html:4466`).

### 4. Companion: overrides and reset

- **Overrides** are the keys that are in both `SHARED` and `config.json`,
  even when the values are equal. `state_info` (`:8500`) adds `shared`
  (key → value) and `overrides` (a list of keys).
- **A validator per key.** The per-key checks in `POST /api/settings`
  (`:8828` onwards) move into `check_setting(key, value) -> value | None`.
  The POST and the shared loader both use it, so a shared value passes the
  same rules as a typed one.
- **Reset:** `POST /api/settings/reset {"key": k}`, window token only, for
  config keys and never API aliases.
  1. Refuse if `k` is not in `SHARED`.
  2. Take `_switch_lock`, then `_config_lock`, in the existing order
     (`:8936-8937`).
  3. Delete `k` from `config.json`, and replace `CFG[k]` with `SHARED[k]`
     whole. `look` is replaced whole, not merged as the POST does
     (`:8855-8858`).
  4. Drop the related state that would recreate the override. Resetting
     `voice` also removes `voice_by_lang[current language]`, because
     `restore_voice` (`:4995-4999`) would otherwise save `voice` back on the
     next language switch. The plan lists these pairs from the code.
  5. Run the key's runtime effect through `apply_effects(k)`, which is the
     side-effect half of the POST, split out: voice reload, eleven reset,
     and so on.
  
  The reply says when a key only applies on the next start or conversation.
- **The panel** (`index.html`, `renderSettings`): an overridden setting gets
  a line "differs from your NixOS config" and a "Use shared" button. With
  `shared` empty, nothing changes.

### 5. Bridge and bar card (nixi-nixarchy)

- **`bridge/bridge.js`:**
  - `loadSettings` and `followSettings` read `nixi-shared.json` (`trust`,
    `permissionMode`), then `nixi.json` over it.
  - The folder watcher (`:118-123`) also reacts to `nixi-shared.json`.
  - `mergeSettings` doesn't change.
  - A shared change reaches a running bridge as an edit to `nixi.json` does
    today (#146). For Codex, a trust change ends the conversation
    (`:165-167`), as it does now.
- **`Ask.qml`** (the bar card): it reads `nixi-shared.json` for `agent`,
  `model` and `reasoningEffort` defaults. `cardOwnedSettings` (`:197`) stops
  writing `agent`/`model`/`reasoningEffort` when they equal the shared value.
  So only a real local choice is saved, and the intent's "agent and model"
  scope is kept.
- **The `/shared` command** in the card resets the bridge-side overrides.
  It deletes `trust`, `permissionMode`, `agent`, `model` and
  `reasoningEffort` from `nixi.json` through `mergeSettings` (a delete
  patch), and then the bridge follows. `doctor` lists these overrides too.

### 6. Plugins

- **Shipping.** Nix ships `news`, `nix-status` and `rss-headlines` through
  `companion.plugins`. A Nix plugin beats a folder copy with the same id
  (`app/plugins.py:361-363`). Nix plugins count as allowed once enabled
  (`plugins_act`, `:2595`).
- **Turning them on.** Plugins start off (the module doc, and
  `plugins.py:436-438`). `shared.json` `plugins_on` adds a layer under
  `plugins-state.json`: an id with no entry there counts as `enabled: True`.
  An entry there, including one where you turned it off, always wins.
  `plugins-state.json` is never written by a deploy.
- **Private plugins.** `private_plugins` are never shipped. `doctor` says
  "private plugin 'you' is not on this machine" when one is missing.

### 7. Voices

- **Pinned source.** `fetch_voice` (`:5094`) and `fetch_voice_sync` (`:5128`)
  both download from a pinned Hugging Face revision (`PIPER_REV`, a commit
  hash), not `main`.
- **Checked bytes.** For a voice listed in `shared.json` `voices`, both
  paths, and the existing-file shortcut (`:5087`, `:5114-5119`), accept the
  `.onnx` and `.onnx.json` only when both sha256 match. A mismatching file is
  moved to `voices/.stale/` and fetched again.
- **At start**, the listed voices are checked once, cached by file
  size and mtime, and missing or stale ones are fetched in the background.
  Unlisted voices behave as today. The folder stays writable.

### 8. The one-time migration: `nixi-companion settings migrate`

It runs by hand, as one transaction:

1. Stop the companion, and so its bridge (`nixi-companion stop`).
2. Copy `config.json`, `nixi.json` and `plugins-state.json` to
   `~/.local/state/nixi-companion/migrate-<time>/`.
3. For each file:
   - read it, and keep its mtime;
   - compute the new content: drop keys equal to the shared value, else the
     default;
   - for keys that differ from a shared value, ask keep or drop (`--keep`,
     `--drop-all`);
   - write it to a temp file;
   - just before replacing the original, check its mtime hasn't changed;
   - `rename` the temp file into place.
   
   If the bar card saved in between, the mtime check fails, so that file
   isn't replaced. The command says so and can be run again.
4. Move superseded folder plugin copies into the backup. Private plugins
   stay.
5. Print what changed, start the companion again, and tell you how to undo
   it.

On an error, nothing is renamed, and the backup is there.

### 9. `doctor`

A "shared settings" section:
- the files are there and parse;
- ignored keys and values;
- overrides on both sides, with local and shared values (`look` as
  "differs");
- missing private plugins;
- voices that are missing or stale.

## Alternatives rejected

- **A deploy that merges shared values into the runtime files.** It races
  their writers and overwrites local changes.
- **`home.file` in nixos_config instead of module options.** The module
  already owns `peers.json` and `plugins`, so the shared settings belong next
  to them.
- **Voices in the Nix store.** That's 180 MB of closure, and a read-only
  folder. A pinned revision with sha256 checks gives the same bytes.
- **Sync by command, or a peer push.** Rejected at intent approval (1a).

## Risks

- **A stale override hides a later shared change.** That's intended, and
  shown in `doctor` and in the panel. `migrate` starts both hosts with none.
- **The shared bridge trust applies at the next follow.** Only nixos_config
  writes it, and a local `nixi.json` value still wins.
- **First-run change.** Reads of a default straight from the file would
  break. In the named files, nothing reads `config.json` except
  `load_config` and `save_config`. The plan greps all of `app/` and `bin/`
  for `CONF_PATH` again.
- **The pinned revision can disappear upstream.** Then the fallback is
  espeak, as today, and `doctor` says so.
- **Cross-repo order.**
  - With a new module but an old companion, `shared.json` is ignored.
  - With a new companion but an old module, there's no `shared.json`, so
    it behaves as today.
  - With a new card but an old bridge, the card's agent default only
    changes what the card writes.
  
  All of these are safe.
- **Hosts:** p620 and razer.

## Verification

- **Companion unit tests** (`_ServerEnv`/`nixi_env`, never the real HOME,
  #176):
  - layer order;
  - every `DEFAULTS` key is classified;
  - a local-only key and a bad value in `shared.json` are ignored;
  - a missing or broken `shared.json`;
  - first run, with and without a shared `language`;
  - `nixi_conf` with a shared-only trust;
  - `overrides`/`shared` in `state_info`;
  - reset:
    - it replaces `look` whole;
    - a `voice` reset followed by a language switch doesn't bring the
      override back;
    - the effects run;
    - it refuses a key that isn't shared;
  - `migrate`:
    - backup;
    - drops equal values;
    - `--keep`/`--drop-all`;
    - a concurrent save makes it refuse that file;
    - an error leaves the originals;
    - superseded plugins move;
  - plugins:
    - `plugins_on` with no entry → on;
    - a local off stays off;
  - voices:
    - pinned URLs on both paths;
    - stale existing files are replaced;
    - a sidecar mismatch;
    - a synchronous fetch;
  - the `doctor` section.
- **Bridge and card tests** (`node --test`, plus the card's QML tests if
  there are any):
  - shared → local precedence;
  - following a real symlink swap, including a moment with the target
    missing, and a trust change in flight;
  - a broken shared file is ignored;
  - `/shared` deletes the keys;
  - the card doesn't save values equal to the shared ones.
- **Module:** `nix flake check` in nixi-nixarchy, with an evaluation test
  that the two options write the two files and that empty options write
  nothing.
- **Builds:** `nix flake check` here, and in nixos_config
  `nix build .#nixosConfigurations.{p620,razer}.config.system.build.toplevel`.
- **Live on both hosts:**
  - deploy, then `migrate`, then `doctor` shows no overrides on either
    side;
  - a voice change on razer shows "differs", and "Use shared" puts it back;
  - a shared voice change in nixos_config reaches both machines on deploy;
  - `news` comes from Nix and is on;
  - `you` is still there;
  - the voices match their sha256.
