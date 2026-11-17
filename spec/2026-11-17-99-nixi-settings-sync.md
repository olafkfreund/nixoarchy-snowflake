---
status: draft
issue: 99
intent: intent/2026-11-17-99-nixi-settings-sync.md
---

# Spec: keep Nixi's settings and plugins the same on every machine

## Design

The order is **built-in defaults → a shared file from nixos_config → local
overrides**. The shared values come from a read-only file of their own,
which Home Manager links into place. Nothing else writes that file, so a
deploy never touches Nixi's own files. Three readers learn to use it: the
companion, the bridge, and `doctor`.

### 1. The shared files (nixos_config)

`hosts/common/nixos/omarchy-nixi-companion.nix` gains two files, written
with `builtins.toJSON`:

- `home.file.".config/nixi-companion/shared.json"` holds the companion's
  shared settings, plus `private_plugins` (names only, such as
  `["you"]`) and `voices` (piper voice name → sha256).
- `home.file.".config/omarchy/nixi-shared.json"` holds the bridge's shared
  `trust` and `permissionMode`.

Both are symlinks into the store, read-only and world-readable, so the
constraint applies: no secrets, no private plugins.

The values are today's p620 settings, minus the local-only keys below. No
new Home Manager module: a plain `home.file` in the shared host module is
enough for one owner and two hosts.

### 2. Companion: the shared layer (`app/server.py`)

- **`SHARED_OK`** is an allowlist of keys that may be shared. It holds the
  voice, look, features, notification and behaviour keys. Every key not on
  it is local-only and ignored in `shared.json`:
  - `mic_device`, `mic_cmd` and recorder commands;
  - `whisper_device` and CPU choices;
  - `cwd`, `projects` and other paths;
  - executables;
  - window, position and size state;
  - `peers_asked` and other remembered consent;
  - `port`.

  An ignored key gets one `doctor` line. The exact list is a plan step,
  checked against `DEFAULTS` key by key.
- **`load_config`** (`:279`): `cfg = DEFAULTS`, then `SHARED` (from
  `shared.json`, filtered to `SHARED_OK`), then the user's `config.json`. The
  existing in-memory migrations (whisper `base.en`→auto, the old `stt_hint`)
  still run on the user layer.
  - A missing or broken `shared.json` means an empty shared layer. Broken
    gets a `doctor` line, and Nixi works as today.
  - On first run, Nixi stops writing all of `DEFAULTS` into `config.json`
    (`:296-302`). It writes only `language` and `lang_good`, which first-run
    detection needs.
- **`save_config`** (`:5892`) doesn't change: it already writes only the
  keys it's given, and the panel saves one setting at a time
  (`setSetting`, `index.html:4466`).
- **Overrides** are the keys that are in both `SHARED` and `config.json`.
  `state_info` (`:8500`) adds:
  - `shared`: the key → value pairs of the shared layer;
  - `overrides`: the list of overridden keys.
- **Reset:** `POST /api/settings/reset {"key": k}` (window token only).
  1. Under `_config_lock`, delete `k` from `config.json`.
  2. Apply `{k: SHARED[k]}` through the same code path as
     `POST /api/settings`. That path is refactored into
     `settings_apply(b) -> upd`, so the runtime effects (voice reload,
     `AskPass.forget`, and so on) run.
  3. Never write `k` back.
  
  Keys that only take effect on the next start or turn say so in the reply.
- **`look` is one key.** A reset replaces the whole look (decided at intent
  approval).
- **The panel** (`app/static/index.html`, `renderSettings`): an overridden
  setting shows a small "differs from your NixOS config" line, with a "Use
  shared" button that calls the reset. Nothing changes when `shared` is
  empty.

### 3. Bridge: the shared layer (nixi-nixarchy `bridge/bridge.js`)

- `loadSettings` and `followSettings` read `nixi-shared.json` (only `trust`
  and `permissionMode`), then `nixi.json` over it.
- The watcher (`:160-165`) already watches the folder. It also reacts to
  the name `nixi-shared.json`, because a Home Manager switch replaces the
  symlink.
- `mergeSettings` doesn't change. A `/mechanic` or YOLO switch still writes
  `nixi.json`, which makes it an override, as today.
- The card (`Ask.qml`) never writes `trust` or `permissionMode`
  (`:195-222`), so it needs no change.
- Agent, model and effort stay local. The card writes all of its own keys on
  every save (`cardOwnedSettings`), and they are per-machine choices anyway.
  The intent's "agent and model" is narrowed here, with that reason.

### 4. Plugins (nixos_config)

- The shared, non-private folder plugins (`news`, `nix-status`,
  `rss-headlines`) ship through the existing `plugins` argument
  (`nix/package.nix:32`). nixos_config calls
  `nixi-companion.override { plugins = map (id: mkCompanionPlugin "${inputs.nixi-companion}/plugins/examples/${id}") [ … ]; }`.
- A Nix plugin beats a folder copy with the same id (`app/plugins.py:361-363`).
  Nix-source plugins count as allowed once enabled (`plugins_act`, `:2595`).
  The bump step no longer goes stale.
- **Consent stays local.** `plugins-state.json` is never written by a
  deploy, so a plugin you turned off stays off.
- **Private plugins** (`private_plugins`) stay hand-copied. `doctor` says
  "private plugin 'you' is not on this machine" when one is missing.

### 5. Voices

- `shared.json` `voices` maps each piper voice name to its sha256.
- `fetch_voice` (`:5094`) downloads from a pinned Hugging Face revision
  (`PIPER_REV`, a commit hash) instead of `main`.
- When a listed voice is missing, Nixi fetches it in the background at start,
  checks its sha256, and keeps it only on a match. A mismatch is deleted and
  reported in `doctor`.
- The voices folder stays writable: downloads you start yourself still work.

### 6. The one-time migration: `nixi-companion settings migrate`

A new subcommand of the existing CLI. It runs by hand, never on its own:

1. Back up `config.json` and `nixi.json` to
   `~/.local/state/nixi-companion/migrate-<time>/`.
2. In `config.json`, drop every key whose value equals what it would be
   without it (the shared value, else the default). Those were written by
   the old first run, or match anyway.
3. List the remaining keys that differ from a shared value (there are none
   on p620 and razer today). For each one, ask: keep it as a local override,
   or drop it. `--keep a,b` and `--drop-all` do the same without asking.
4. Do the same in `nixi.json` for `trust` and `permissionMode` only.
5. Move folder copies that a Nix plugin now supersedes into the backup.
   Private plugins stay where they are.
6. Print what changed, then restart Nixi.

### 7. `doctor`

A "shared settings" section:
- the shared files are there and parse;
- ignored local-only keys;
- every override, with its local and shared values (`look` as "differs");
- missing private plugins;
- voices that are missing or don't match their sha256.

## Alternatives rejected

- **A deploy that merges shared values into `config.json` / `nixi.json`.**
  It races Nixi's own writes, and it overwrites your local changes on every
  deploy. The intent forbids both.
- **A Home Manager module in this repo.** One owner and two hosts don't
  need a module's options and docs. A `home.file` in the shared host module
  says the same thing. Revisit when someone else uses the companion.
- **Voices as Nix store files.** That's 180 MB per bump in the closure, and
  it would make the voices folder read-only. A pinned revision plus sha256
  gives the same bytes.
- **Sharing agent, model and effort.** The bar card writes them on every
  save, so they would always look like overrides. They are per-machine
  choices.
- **`nixi-companion sync <host>` or a peer push.** Rejected at intent
  approval (1a).

## Risks

- **A stale override hides a later shared change.** That's intended, and
  both `doctor` and the panel show it. Running `migrate` first keeps
  p620's and razer's lists empty.
- **YOLO from `nixi-shared.json` applies at the next follow.** A deploy that
  changes the shared `trust`/`permissionMode` moves a running bridge, as an
  edit to `nixi.json` does today (#146). Only nixos_config can write it, and
  a `nixi.json` override still wins.
- **First-run change.** A brand-new machine's `config.json` holds only
  `language` and `lang_good`. Anything that read a default from the file
  instead of from `CFG` would break. The plan greps for direct reads of
  `CONF_PATH`.
- **The pinned voice revision can disappear upstream.** Then a missing voice
  can't be fetched, and the fallback is espeak, as today. `doctor` says so.
- **Hosts.** p620 and razer. Another agent's deploy carries the shared files
  once they are in nixos_config main.

## Verification

- **Unit tests** (`tests/`), using `_ServerEnv`/`nixi_env`, never the real
  HOME (#176):
  - layer order;
  - `SHARED_OK` filtering;
  - a broken or missing `shared.json`;
  - first run writes only `language`/`lang_good`;
  - `overrides`/`shared` in `state_info`;
  - reset removes the key, applies the shared value and runs the
    side-effects;
  - `look` resets as a whole;
  - `migrate`'s backup, the equal-value drop, `--keep` and `--drop-all`,
    the `nixi.json` part, and the superseded-plugin move;
  - `doctor`'s new section;
  - voice sha256 match, mismatch and the pinned URL.
- **Bridge tests** (`node --test`):
  - `nixi-shared.json` sets `trust`/`permissionMode`, and `nixi.json` beats
    it;
  - a change to the shared file is followed;
  - a broken shared file is ignored.
- **Builds:** `nix flake check` here and in nixi-nixarchy, and
  `nix build .#nixosConfigurations.{p620,razer}…toplevel` with the shared
  files and the plugin override.
- **Live on both hosts:**
  - after deploy and `migrate`, `doctor` shows no overrides;
  - changing the voice in the panel on razer shows "differs" and lists it
    in `doctor`;
  - "Use shared" puts it back at once;
  - a change to the shared voice in nixos_config reaches both machines on
    the next deploy;
  - the `news` plugin is from Nix on both, and allowed.
