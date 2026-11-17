---
status: draft
issue: 99
spec: spec/2026-11-17-99-nixi-settings-sync.md
coders:
  1: codex    # small, tricky: split the settings POST into check_setting/apply_effects without changing behaviour
  2: codex    # small, tricky: layered load, nixi_conf, overrides, reset with related state and lock order
  3: coder    # voices: pinned revision and sha256 on both download paths
  4: coder    # plugins_on layer in plugins.py
  5: coder    # migrate subcommand and the doctor section
  6: coder    # the settings panel badge and button
  7: coder    # companion tests across steps 1-6
  8: coder    # nixi-nixarchy: the two module options and their eval checks
  9: codex    # nixi-nixarchy: bridge shared layer, symlink-swap follow, /shared, card not saving shared values
reviewers:
  - codex     # read-only review of each repo's diff against this plan
---

# Plan: keep Nixi's settings and plugins the same on every machine

This plan has everything needed to build it; the intent and spec don't need
opening. It covers three repos:
- **companion:** this repo, `/mnt/code/Source-home/GitHub/nixoarchy-snowflake`,
  branch `feat/99-nixi-settings-sync`;
- **nixi-nixarchy:** `/mnt/code/Source-home/GitHub/nixi-nixarchy`, default
  branch `master`, a new worktree on `feat/99-shared-settings`;
- **nixos_config:** `~/.config/nixos`, a clean worktree off `origin/main`.
  Never edit `~/.config/nixos` itself.

## Decisions (from the approved intent and spec)

- **Order:** built-in defaults, then shared files from Nix, then local
  overrides. This holds for the companion (`config.json`), the bridge and its
  bar card (`~/.config/omarchy/nixi.json`), and `doctor`.
- **A deploy never writes `config.json`, `nixi.json` or
  `plugins-state.json`.**
- **The shared files are read-only Home Manager links.**
  - `~/.config/nixi-companion/shared.json` holds the companion keys, plus
    `plugins_on`, `private_plugins` and `voices`.
  - `~/.config/omarchy/nixi-shared.json` holds `trust`, `permissionMode`,
    `agent`, `model` and `reasoningEffort`.
- **Only `SHARED_OK` keys are taken from `shared.json`.** Each value is
  checked by the same validator as the panel. Anything else is ignored and
  noted in `doctor`.
  - The local-only keys are: `port`, `cpu_split`, `whisper_device`,
    `mic_device`, `mic_cmd`, `cwd`, `claude_bin`, `extra_args`,
    `piper_voice`, `projects`, `voice_prompt`, `quick_actions`, `workout`,
    `mail_accounts`, `lang_good`, `peers_asked`, `root_mode` and
    `permission_mode`.
  - Every other `DEFAULTS` key is in `SHARED_OK`. The spec's part 2 table is
    the authority.
- **Overrides:** a key in both `SHARED` and the local file, even when the
  values are equal. They are visible in the panel ("differs from your NixOS
  config" with **Use shared**) and in `doctor`. The bar card's `/shared`
  resets the bridge side.
- **Reset:** it replaces the value whole (`look` too). It also drops related
  state, so `voice` drops `voice_by_lang[active]`. It follows the existing
  lock order (`_switch_lock`, then `_config_lock`), and runs that key's
  effects.
- **First run:** writes only `lang_good`, plus `language` when nothing shared
  sets it.
- **Plugins:** `news`, `nix-status` and `rss-headlines` ship through
  `services.nixi.companion.plugins`. `plugins_on` makes an id with no
  `plugins-state.json` entry count as enabled, and a local entry always wins.
  The private `you` plugin stays hand-copied.
- **Voices:** pinned revision `PIPER_REV = "0ca208afc2a2ee102b1e961e72e0a7e4907be3d0"`.
  The sha256 at that revision:

  | File | sha256 |
  |---|---|
  | `en_GB-alan-medium.onnx` | `0a309668932205e762801f1efc2736cd4b0120329622adf62be09e56339d3330` |
  | `en_GB-alan-medium.onnx.json` | `c0f0d124e5895c00e7c03b35dcc8287f319a6998a365b182deb5c8e752ee8c1e` |
  | `en_US-amy-medium.onnx` | `cf9ccdec59f05adee47173f6fb4d89e8b0c5f30c178748d2572fe4efd1d2724c` |
  | `en_US-amy-medium.onnx.json` | `27490c2197e3e7b566b051fc0b1dae21200e72b44c209731419effdbbe0789e5` |
  | `en_US-ryan-medium.onnx` | `33b53106e049f68a51f014e4fa10bf5a04e0f7d6668692dc05228cc4554c1d71` |
  | `en_US-ryan-medium.onnx.json` | `d29061675e660113d51f81650e922134d94cab750271f9ce2bcb05121f925a60` |

  The amy and ryan files now on both machines don't match, since they were
  downloaded from `main` earlier. So both machines refetch them once.
- **`nixi-companion settings migrate`:** you run it by hand. It stops Nixi,
  backs up, keeps only real differences, checks each file's mtime before
  replacing it, then starts Nixi again.

## Steps

### Companion repo

1. **`app/server.py`: split the settings POST** (`:8828` up to its
   `save_config` call, about `:8960`). By Codex.
   - New `check_setting(key, value) -> (ok, value)`. It holds every per-key
     validation now done inline: enums, ranges, `look()`, colours,
     `size_value`, `voice_settings`, and the rest. The POST loops over the
     body with it. The API alias `root` → `root_mode` stays in the POST only.
   - New `apply_effects(keys)`. It holds every side effect now done after
     validation:
     - `AskPass.forget`;
     - voice and engine reload;
     - eleven and language switching, under `_switch_lock` as now;
     - `NImage.clear` (that one stays in `save_config`).
   - The POST becomes: validate, then `save_config(**upd)`, then
     `apply_effects(upd)`. The response is unchanged.
   - Verify with:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py --exclude test_character_fit.py --exclude test_accessories_fit.py
     ```
     The whole suite must stay green. This is a pure refactor.
   - Traps: keep the `_switch_lock` → `_config_lock` order (`:8936-8937`),
     and keep `voice_by_lang` saving on a voice change (`:8938-8942`).

2. **`app/server.py`: the shared layer.** By Codex, after step 1.
   - Add `SHARED_PATH = CONF_PATH.parent / "shared.json"` and
     `NIXI_SHARED = NIXI_CONF.parent / "nixi-shared.json"`.
   - `SHARED_OK` and `LOCAL_ONLY` are frozensets next to `DEFAULTS`.
   - `load_shared()`:
     - reads `SHARED_PATH`;
     - keeps `SHARED_OK` keys whose `check_setting` passes;
     - returns `(settings, extras, notes)`, where `extras` holds
       `plugins_on`, `private_plugins` and `voices`, each type-checked.
   - `load_config` (`:279`):
     - `cfg = dict(DEFAULTS)`, then the shared settings, then the user file.
       The migrations stay on the user dict.
     - Keep `SHARED` and `SHARED_EXTRAS` as module globals.
     - First run (`:296-302`): write only
       `{"lang_good": "en", **({"language": detected} if "language" not in SHARED else {})}`.
   - `nixi_conf()` (`:133`): `{**shared_bridge, **local}`, where
     `shared_bridge` is `nixi-shared.json` filtered to the five bridge keys.
   - `state_info` (`:8500`) adds:
     - `"shared": SHARED`;
     - `"overrides"`: the keys in the user file that are also in `SHARED`.
       Read the file under `_config_lock`; it's small.
   - New `POST /api/settings/reset` (window token, as `/api/settings`).
     Body `{"key": k}`:
     1. Refuse unless `k in SHARED`.
     2. Take `_switch_lock`, then `_config_lock`.
     3. Remove `k` from the file and set `CFG[k] = SHARED[k]`.
     4. Drop the related state from `RESET_RELATED = {"voice": ("voice_by_lang", lang.active)}`.
        Add other pairs only where the code shows something saving the key
        back: grep `save_config(` for keys in `SHARED_OK`.
     5. Write the file with an atomic replace, under the lock.
     6. Run `apply_effects([k])`.
     
     The reply is `state_info()`, plus `"next": "start"` for keys that apply
     on restart (`port` is local, so no shared key needs it today; keep the
     hook).
   - Verify by running `test_whisper_switch.py`, `test_sessions.py` and the
     new test file from step 7 with:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py <files>
     ```
   - Traps:
     - `save_config` must stay sparse.
     - Grep `app/` and `bin/` for `CONF_PATH` and `NIXI_CONF`: every reader
       must go through `CFG` or `nixi_conf()`.
     - Tests must never use the real HOME (#176).

3. **`app/server.py`: voices.** By the coder.
   - `PIPER_REV` is a constant.
   - `fetch_voice` (`:5094`) and `fetch_voice_sync` (`:5128`) build their
     URL with `PIPER_REV` instead of `main`.
   - `voice_ok(name)`: when `SHARED_EXTRAS["voices"]` lists the name, both
     the `.onnx` and `.onnx.json` sha256 must match. The check is cached in a
     dict keyed by `(path, size, mtime)`.
   - The existing-file shortcuts (`:5087`, `:5114-5119`) use `voice_ok`. On
     a mismatch, move both files to `voices/.stale/` and fetch again.
     Downloads write to a temp file and are kept only when `voice_ok` passes.
   - At start, in a daemon thread, fetch every listed voice that is missing
     or stale.
   - Verify with the step 7 voice tests.
   - Traps:
     - No network in tests: patch `urllib.request.urlopen`.
     - Unlisted voices behave as today.

4. **`app/plugins.py`: the `plugins_on` layer.** By the coder.
   - The state store's `get(pid)` (`:436-438`) returns
     `{"enabled": True, "sha256": None}` for an id in `plugins_on` with no
     entry. Pass `plugins_on` in when the store is created, from
     `server.SHARED_EXTRAS`.
   - A real entry, on or off, always wins. Nothing writes the state file
     because of `plugins_on`.
   - Verify with the step 7 plugin tests and the existing plugin tests:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py test_plugins*.py
     ```
   - Traps: folder plugins still need their hash consent. `plugins_on` only
     changes `enabled`, never `sha256`.

5. **`bin/nixi-companion` + `app/server.py`: `settings migrate` and the
   `doctor` section.** By the coder.
   - **`settings migrate`** (CLI case next to `doctor)`, `bin:224`). It runs
     the Python side through the same interpreter the CLI uses for
     `doctor`.
     1. Stop Nixi with the existing `stop`, then back up `config.json`,
        `nixi.json` and `plugins-state.json` to
        `~/.local/state/nixi-companion/migrate-<UTC time>/`.
     2. For each file: read it and note its mtime, then build the new dict.
        - `config.json`: drop keys equal to `SHARED.get(k, DEFAULTS.get(k))`.
          Local-only keys are never dropped.
        - `nixi.json`: only the five bridge keys, compared with
          `nixi-shared.json`, else the bridge's defaults (`trust` guide,
          `permissionMode` permission). Card keys without a shared value stay.
        - For keys that differ from a shared value, ask "keep as local
          override? [y/N]". `--keep k1,k2` and `--drop-all` answer without
          asking.
     3. Write each file to `<file>.migrate.tmp`, recheck its mtime, then
        `os.replace`. A changed mtime means skip that file, say so, and exit
        1.
     4. Move folder copies in `~/.local/share/nixi-companion/plugins/<id>`
        whose id ships from Nix into the backup. Skip `private_plugins`.
     5. Print a summary and the undo command
        (`cp -a <backup>/* back`), then start Nixi with `nixi-companion show`.
   - **`doctor()`** (`:4664`) gets a "── shared settings ──" section listing:
     - the shared files and whether they parse;
     - ignored keys and values;
     - companion overrides as `key: local → shared`, with `look` as
       "differs";
     - bridge overrides from `nixi.json`;
     - missing `private_plugins`;
     - voices that are missing or stale.
   - Verify with the step 7 tests, then on this machine:
     ```bash
     nixi-companion doctor
     ```
   - Traps: never write the files while Nixi runs; `migrate` stops it first.

6. **`app/static/index.html`: the panel.** By the coder.
   - In `renderSettings`, for every rendered setting whose key is in
     `info.overrides`, add a small line "differs from your NixOS config"
     and a **Use shared** button. The button posts
     `/api/settings/reset {key}` and replaces `info` with the reply.
   - With `info.shared` empty, nothing changes.
   - Use the panel's existing small-note style. No new colours.
   - Verify with:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py test_settings*.py
     nix develop .#ci -c python3 -B .github/ci/run_tests.py --deadline 1800 test_character_fit.py test_accessories_fit.py
     ```
     Run the first if those tests exist. The fit tests must stay green.
   - Traps: the panel must stay inside its fit boxes. Check with the
     settings fit test if there is one.

7. **Tests: `tests/test_shared_settings.py` (new).** By the coder.
   - Use `_ServerEnv`/`nixi_env`, never the real HOME, never the network.
     Cover every case in the spec's Verification list:
     - layers;
     - every `DEFAULTS` key is classified, and `SHARED_OK` and `LOCAL_ONLY`
       don't overlap;
     - ignored keys and bad values;
     - a missing or broken file;
     - first run, with and without a shared `language`;
     - `nixi_conf` with a shared-only trust;
     - `state_info` `shared`/`overrides`;
     - reset:
       - it replaces `look` whole;
       - a `voice` reset followed by a language switch keeps no override;
       - effects run;
       - it refuses a key that isn't shared;
     - `migrate`:
       - backup;
       - drops equal values;
       - `--keep`/`--drop-all`;
       - a concurrent mtime change refuses;
       - an error leaves the originals;
       - superseded plugins move, and private ones stay;
     - plugins: `plugins_on` with no entry → on, and a local off stays off;
     - voices:
       - pinned URLs on both paths;
       - stale files replaced;
       - a sidecar mismatch;
       - a synchronous fetch;
     - the doctor section.
   - Verify with:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py test_shared_settings.py
     ```
     It must have 0 skips. Then run the full suite.
   - Traps: CI fails on skips that aren't on the allow-list.

### nixi-nixarchy

8. **`nix/hm-module.nix`: two options.** By the coder.
   - `services.nixi.companion.settings`: `attrsOf (json-able)`, default
     `{}`. When non-empty, write
     `xdg.configFile."nixi-companion/shared.json".text = builtins.toJSON cfg.companion.settings`,
     next to `peers.json` (`:382`).
   - `services.nixi.settings`: a `submodule`, `nullOr` per field: `trust`
     (enum guide/mechanic), `permissionMode` (enum permission/yolo),
     `agent`, `model` and `reasoningEffort` (strings). When any field is
     set, write `xdg.configFile."omarchy/nixi-shared.json"` with the
     non-null fields.
   - Option descriptions say:
     - the files are world-readable in the store, so no secrets, private
       plugins or personal text;
     - a local change wins until reset.
   - Add `checks.hm-companion-shared` in `flake.nix`, in the style of
     `hm-companion-peers` (`:108-154`). It checks that:
     - both files are written with the given values;
     - empty options write neither;
     - a bad enum fails evaluation.
   - Verify with:
     ```bash
     nix flake check
     ```
     Run it in the worktree.
   - Traps: the repo's default branch is `master`.

9. **`bridge/bridge.js` + `Ask.qml`: the shared layer.** By Codex.
   - **`bridge.js`:**
     - `sharedPath = join(settingsDir, "nixi-shared.json")`.
     - `loadSettings` (`:98`) and the follow path read
       `{...shared(trust, permissionMode), ...local}`. A missing or broken
       shared file is ignored.
     - The watcher filter (`:118-123`) also accepts `nixi-shared.json`.
     - `mergeSettings` (`:203-232`) accepts `null` values as deletes.
       `/shared` (a new card command, handled where `/mechanic` is) sends
       `{trust: null, permissionMode: null, agent: null, model: null, reasoningEffort: null}`.
   - **`Ask.qml`:**
     - Read `nixi-shared.json` with a second `FileView`, watched. The
       `agent`, `model` and `reasoningEffort` defaults come from it when
       `nixi.json` lacks them.
     - `cardOwnedSettings` (`:197`) leaves out those three keys when they
       equal the shared value.
     - `writeSettings` (`:225`) must then delete a left-out key from the
       merged data, instead of keeping the disk value. Do that only for
       keys that equal the shared value.
   - **Tests** (`bridge/settings.test.js`, `bridge/settings-follow.test.js`,
     and `tools/test_nixi.py`'s Ask.qml checks at `:604`):
     - shared → local precedence;
     - a real symlink swap, including a missing target in between and a
       trust change in flight;
     - a broken shared file is ignored;
     - `/shared` deletes the keys;
     - the card doesn't save shared-equal values.
   - Verify with:
     ```bash
     cd bridge && node --test
     python3 tools/test_nixi.py
     ```
     The second is the repo's QML/static test; check its README line for
     the exact command. Symlink `node_modules` from the main checkout for
     the run only.
   - Traps:
     - For Codex, a trust change ends the conversation (`:165-167`), as now.
     - Never weaken the click-only sends or Guide.

### Lead

10. **Review, PRs, declare, deploy, migrate, check.**
    - **Reviews:**
      - a fresh Opus agent with this plan and both diffs;
      - Codex `review --base main` here, and `--base origin/master` in
        nixi-nixarchy.
    - **Run here:**
      ```bash
      nix develop .#ci -c python3 -B .github/ci/run_tests.py --exclude test_character_fit.py --exclude test_accessories_fit.py
      nix develop .#ci -c python3 -B .github/ci/run_tests.py --deadline 1800 test_character_fit.py test_accessories_fit.py
      nix flake check
      nix build
      ```
      The two suites must pass, with only allowed skips.
    - **Run in nixi-nixarchy:**
      ```bash
      nix flake check
      cd bridge && node --test
      ```
    - **PRs** in both repos, each commented "@codex review".
    - **nixos_config**, in a worktree off `origin/main`, under a new issue.
      In `hosts/common/nixos/omarchy-nixi-companion.nix` set:
      - `services.nixi.companion.settings`: p620's current values for the
        `SHARED_OK` keys, read from `~/.config/nixi-companion/config.json`
        at that time, plus `plugins_on`, `private_plugins = [ "you" ]` and
        `voices` (the table above);
      - `services.nixi.companion.plugins`, with the three example plugins
        from the companion input;
      - `services.nixi.settings`, from p620's `~/.config/omarchy/nixi.json`.
      
      Bump both inputs, then build p620 and razer, and check with
      `diff-closures` that only Nixi changes. Open the PR and merge it after
      CI.
    - **Deploy:**
      - Post on the agent bus first.
      - Check `git -C ~/.config/nixos diff nixarchy-theme.nix` and copy it
        into the deploy worktree if it differs (memory: deploys keep the
        uncommitted theme).
      - p620: `nh os switch .`.
      - razer: `just deploy-via-p620 razer`.
    - **On each host:** `nixi-companion settings migrate`, then
      `nixi-companion doctor`, which must show no overrides on either side.
    - **Live checks:**
      - change the voice on razer, which shows "differs";
      - **Use shared** puts it back;
      - a shared value change in nixos_config reaches both machines on the
        next deploy;
      - `news` is from Nix and on;
      - `you` is still there;
      - the voices match.

## Tests

- **Companion:**
  ```bash
  nix develop .#ci -c python3 -B .github/ci/run_tests.py --exclude test_character_fit.py --exclude test_accessories_fit.py
  nix develop .#ci -c python3 -B .github/ci/run_tests.py --deadline 1800 test_character_fit.py test_accessories_fit.py
  nix flake check
  ```
- **nixi-nixarchy:**
  ```bash
  nix flake check
  cd bridge && node --test
  python3 tools/test_nixi.py
  ```
- **nixos_config:** both hosts build, and `diff-closures` shows only Nixi
  and the new files.
- **Live:** the checks in step 10.

## Rollback

Each part can be undone on its own:
- **The settings layer:** revert the nixos_config PR, which removes the
  options' files. Nixi then works from `config.json` alone, which `migrate`
  left holding only real differences. Restore the `migrate` backup to get
  the old files back exactly.
- **The code:** revert the companion and nixi-nixarchy PRs. An old
  companion ignores `shared.json`, and an old bridge ignores
  `nixi-shared.json`.
