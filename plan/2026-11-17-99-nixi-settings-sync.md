---
status: approved
issue: 99
spec: spec/2026-11-17-99-nixi-settings-sync.md
coders:
  1: codex    # small, tricky: the shared layer, overrides and reset, with start-up order and related state
  2: coder    # voices: pinned revision and sha256 on every download path
  3: coder    # plugins_on default in the plugin state store
  4: coder    # migrate transaction, reset-bridge and the doctor section
  5: coder    # the settings panel line and button
  6: coder    # nixi-nixarchy: the two module options and their eval checks
  7: codex    # nixi-nixarchy: bridge shared layer and symlink-swap follow; card saves only keys you changed
reviewers:
  - codex     # read-only review of each repo's diff against this plan
---

# Plan: keep Nixi's settings and plugins the same on every machine

This plan has everything needed to build it; the intent and spec don't need
opening. It covers three repos:
- **companion:** this repo, branch `feat/99-nixi-settings-sync`;
- **nixi-nixarchy:** `/mnt/code/Source-home/GitHub/nixi-nixarchy`, default
  branch `master`, a new worktree `feat/99-shared-settings` in the
  scratchpad;
- **nixos_config:** a clean worktree off `origin/main`. Never edit
  `~/.config/nixos` itself.

Each step writes its own tests, in `tests/test_shared_settings.py` for the
companion, so its check runs when the step ends.

## Decisions

From the approved intent and spec:

- **Order:** built-in defaults, then shared files from Nix, then local
  overrides. This holds for the companion, the bridge, the bar card and
  `doctor`.
- **A deploy never writes `config.json`, `nixi.json` or
  `plugins-state.json`.**
- **The shared files are read-only Home Manager links, written by Nixi's
  module.**
  - `~/.config/nixi-companion/shared.json`: the companion keys, plus
    `plugins_on`, `private_plugins` and `voices`.
  - `~/.config/omarchy/nixi-shared.json`: `trust`, `permissionMode`,
    `agent`, `model` and `reasoningEffort`.
- **Allowlist:**
  - The **local-only** keys are `port`, `cpu_split`, `whisper_device`,
    `mic_device`, `mic_cmd`, `cwd`, `claude_bin`, `extra_args`,
    `piper_voice`, `projects`, `voice_prompt`, `quick_actions`, `workout`,
    `mail_accounts`, `lang_good`, `peers_asked`, `root_mode` and
    `permission_mode`.
  - Every other `DEFAULTS` key is **shared**.
  - A test checks that every `DEFAULTS` key is in exactly one of the two.
- **An override is a key in both the shared and the local file**, even with
  equal values. It's shown in the panel and in `doctor`.
- **First run** writes only `lang_good`, plus `language` when nothing shared
  sets it.
- **Plugins:** `news`, `nix-status` and `rss-headlines` ship through
  `services.nixi.companion.plugins`. `plugins_on` makes an id with no state
  entry count as enabled, and a local entry always wins. The private `you`
  plugin stays hand-copied.
- **Voices** come from the pinned revision
  `PIPER_REV = "0ca208afc2a2ee102b1e961e72e0a7e4907be3d0"` and must match
  these sha256s:

  | File | sha256 |
  |---|---|
  | `en_GB-alan-medium.onnx` | `0a309668932205e762801f1efc2736cd4b0120329622adf62be09e56339d3330` |
  | `en_GB-alan-medium.onnx.json` | `c0f0d124e5895c00e7c03b35dcc8287f319a6998a365b182deb5c8e752ee8c1e` |
  | `en_US-amy-medium.onnx` | `cf9ccdec59f05adee47173f6fb4d89e8b0c5f30c178748d2572fe4efd1d2724c` |
  | `en_US-amy-medium.onnx.json` | `27490c2197e3e7b566b051fc0b1dae21200e72b44c209731419effdbbe0789e5` |
  | `en_US-ryan-medium.onnx` | `33b53106e049f68a51f014e4fa10bf5a04e0f7d6668692dc05228cc4554c1d71` |
  | `en_US-ryan-medium.onnx.json` | `d29061675e660113d51f81650e922134d94cab750271f9ce2bcb05121f925a60` |

  The amy and ryan files on both machines today don't match, since they were
  downloaded from `main` earlier, so each machine fetches them again once.

Changed from the spec, to be approved with this plan (Codex plan review):

- **A. "Use shared" restarts Nixi** (about 5 s), instead of applying the
  value live. Applying it live needs the settings POST split into a
  validator and an effects runner. That split can't stay behaviour-identical
  without a large refactor, because the effects depend on values from before
  the save (`mail_changed`, `peers_changed`, `cut_cloud`, `was_phone`) and on
  checks across the whole request (`voice_settings` needs a cloud
  `confirm`). A restart applies everything through the normal start-up.
- **B. Shared values are checked against a rule table** (`SHARED_RULES`),
  defined before `CFG = load_config()` (`:306`). The rules are type, range
  and allowed values. The spec's "the same validator the panel uses" can't
  run at load time, because `look()`, `voice_settings` and the plugin checks
  are defined later, and some of them read `CFG`.
- **C. The bridge-side reset is a command**,
  `nixi-companion settings reset-bridge`, not a `/shared` command in the bar
  card. The card has no settings-patch path to the bridge today (the
  bridge's input `:940-1033`). The bridge already follows edits to
  `nixi.json` (#146), so the command just removes the five keys, and the
  bridge picks that up.

## Steps

### Companion repo

1. **`app/server.py`: the shared layer, overrides and reset.** By Codex.
   - **Before `CFG = load_config()` (`:306`), next to `DEFAULTS`:**
     - `LOCAL_ONLY` (the list above), and
       `SHARED_OK = frozenset(DEFAULTS) - LOCAL_ONLY`.
     - `SHARED_RULES`, one rule per `SHARED_OK` key, using only literals:
       - `bool`;
       - `int`/`float` with a range (for example `size` 0.4–1.6 and
         `compact_at` 0.3–0.95; take the ranges from the panel's current
         checks, `:8828-8976`);
       - `enum` with a literal tuple (`tts`, `tts_fallback`, `idle_mode`,
         `pupil_style`, `code_face`, `presence`, `bar_edge`, `trust`,
         `effort`, `voice`);
       - `color` (`#rrggbb` or `random`);
       - `str` with a maximum length (`stt_hint` 1000, `eleven_voice` 64,
         `model` 64, `auto_model` 64, `espeak_voice` 32, `mail_model` 64,
         `ptt_hotkey` 64);
       - `list_str` (`agent_voice_mute`, `notify_speak`);
       - `dict_str` (`voice_by_lang`, `voice_by_character`);
       - `look_dict`, a dict of `#rrggbb` values for `look`.
     - A test asserts that the `voice` enum equals `set(VOICES)` and the
       `effort` enum equals `EFFORTS`, so the literals can't drift.
   - **`load_shared(path)`** returns `(settings, extras, notes)`.
     - It ignores and notes keys outside `SHARED_OK` and values that fail
       their rule.
     - `extras` holds `plugins_on` and `private_plugins` (lists of plugin
       ids matching `[a-z0-9][a-z0-9_.-]{0,63}`) and `voices`
       (`{name: {"onnx": sha, "json": sha}}`, where the name matches
       `^[a-z]{2}_[A-Z]{2}-[a-z0-9_]+-(x_low|low|medium|high)$` and each sha
       is 64 hex characters).
     - A missing file gives empties. A broken file gives empties plus a
       note.
   - **`load_config`** (`:279`):
     - `cfg = dict(DEFAULTS)`, then `cfg.update(SHARED)`, then the user
       file. The existing migrations stay on the user dict.
     - Module globals: `SHARED`, `SHARED_EXTRAS` and `SHARED_NOTES`.
     - First run (`:296-302`) writes
       `{"lang_good": "en", **({"language": detected} if "language" not in SHARED else {})}`.
   - **`nixi_conf()`** (`:133`) returns `{**bridge_shared(), **local}`.
     `bridge_shared()` reads `nixi-shared.json`, keeps the five keys, and
     type-checks them: `trust` is guide or mechanic, `permissionMode` is
     permission or yolo, and the rest are strings of at most 64 characters.
   - **`state_info`** (`:8448`) adds `"shared": SHARED` and
     `"overrides": sorted(k for k in user_file_keys() if k in SHARED)`.
     `user_file_keys()` reads `CONF_PATH` under `_config_lock`.
   - **`POST /api/settings/reset`** (window token, as `/api/settings`).
     Body `{"key": k}`:
     1. 400 unless `k in SHARED`.
     2. Under `_config_lock`, read the file, delete `k`, and drop the
        related state:
        - `voice`: also delete `voice_by_lang[lang.active]`, with
          `lang.active` read at request time. The language switch
          (`:4193-4195`) and `restore_voice` (`:4995-4999`) would otherwise
          save the old voice back.
        - `notify_details`: when `SHARED["notify_details"]` is false,
          call `NImage.clear()` (`save_config` does that today at
          `:5901-5902`).
        
        Those are the only two: a grep of `save_config(` shows no other
        shared key being saved back on its own. Re-run the grep while
        building, and add a case only if the code shows one.
     3. Write the file with an atomic replace (temp file, then
        `os.replace`).
     4. Reply `{"ok": true, "restart": true}`.
     5. Start a detached `nixi-companion restart`, with `setsid` and the
        server's environment. The page shows "Restarting Nixi…".
   - Tests (`tests/test_shared_settings.py`, under `_ServerEnv`/`nixi_env`,
     never the real HOME, #176):
     - every `DEFAULTS` key is classified once;
     - the rule literals match `VOICES` and `EFFORTS`;
     - the layer order;
     - a bad or unknown key, and a broken or missing file;
     - first run, with and without a shared `language`;
     - `nixi_conf` with a shared-only trust;
     - `state_info` `shared`/`overrides`, including an equal value;
     - reset:
       - it deletes the key and, for `voice`, the active `voice_by_lang`
         entry;
       - a language switch away and back afterwards doesn't bring the
         override back;
       - `notify_details` to shared false clears `NImage`;
       - it refuses a key that isn't shared;
       - the restart is started (patch `subprocess.Popen`).
   - Verify with:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py test_shared_settings.py test_whisper_switch.py test_sessions.py
     ```
     Then run the full suite with `--exclude test_character_fit.py --exclude test_accessories_fit.py`.
   - Traps:
     - `save_config` stays sparse.
     - Grep `app/` and `bin/` for `CONF_PATH` and `NIXI_CONF`: every reader
       must go through `CFG`/`nixi_conf()`, `load_config` or `save_config`.
     - Nothing in `SHARED_RULES` may call a function defined after `:306`.
   - *Deviations (Opus review, before rollout):*
     - `look`'s rule takes the real shape: hex colours, `skinColor` hex or
       empty, `link`/`random`/`follow_theme` bools, `skin`/`character`
       strings. Hex-only dropped every real `look`.
     - `request_language` and `restore_voice` never save `voice`,
       `voice_by_lang` or `language` while those come only from the shared
       layer, so a language switch (or a failed one at start) can't create
       an override.
     - The legacy `permission_mode` → `trust` migration is skipped when
       `trust` is shared.
     - `window.py` `saved_size()` and the CLI's `size up|down` read
       `shared.json` under `config.json` (they read the file directly).
     - The restart uses `shutil.which("nixi-companion")` or
       `~/.local/bin/nixi-companion`. If it can't start, reset still
       replies ok with `restart: false`, and the panel says to restart Nixi.
     - `migrate` waits only for the server process. The bridge is its
       child; matching `bridge.js` also hit editors and the card's bridge.
   - *Deviations (Codex review):*
     - `migrate` keeps an explicit `trust` while the legacy
       `permission_mode` stays and `trust` isn't shared. Otherwise
       `load_config` re-derives trust from it.
     - A language switch also leaves a shared `voice_by_lang` unsaved when
       `voice` isn't shared.
     - At start, listed voices are checked and fetched before `warm_tts`,
       which caches a loaded model by path.

2. **`app/server.py`: voices.** By the coder.
   - **Pinned downloads.** Add the `PIPER_REV` constant. `fetch_voice` and
     `fetch_voice_sync` build their URLs with it instead of `main`
     (`:5095`, and the base inside `fetch_voice_sync`).
   - **`voice_ok(name)`:** when `SHARED_EXTRAS["voices"]` lists `name`, both
     `voice_file(name)` and its `.onnx.json` must exist and match their
     sha256. Otherwise it is true when the `.onnx` exists, as today. The
     check is cached by `(path, size, mtime)`.
   - **Every existence shortcut uses `voice_ok`:**
     - `fetch_voice` `:5087`;
     - `fetch_voice_sync` `:5114` (ready) and `:5126` (after waiting on a
       pending download).
     
     When a listed voice fails, move both of its files to
     `voices/.stale/<time>/` and download them again. A download writes to
     `<file>.part`, then `os.replace`. The voice is kept only when
     `voice_ok` passes; otherwise both files are removed and an error is
     returned.
   - **At start**, a daemon thread calls `fetch_voice` for each listed voice
     that is missing or stale.
   - Tests:
     - pinned URLs on both paths;
     - a matching voice is used as is;
     - a stale `.onnx` or a stale sidecar is moved aside and fetched again;
     - a mismatching download isn't kept;
     - the pending-download path checks too;
     - unlisted voices behave as today.
   - *Deviation (coder):* both download paths share one helper,
     `_voice_download`, so the pinned URL, `.part` files and the hash check
     live in one place. `fetch_voice` now uses `urlopen`, not `urlretrieve`.
     
     Patch `urllib.request.urlopen`: no network.
   - Verify with:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py test_shared_settings.py
     ```

3. **`app/plugins.py` + `app/server.py`: `plugins_on`.** By the coder.
   - **`plugins.State`** takes `plugins_on=()`. `get(pid)` (`:436-438`)
     returns `{"enabled": True, "sha256": None}` for an id in `plugins_on`
     that has no entry. A real entry, on or off, always wins.
   - **The three constructors** (`server.py:2411`, `:2547`, `:2585`) pass
     `plugins_on=SHARED_EXTRAS["plugins_on"]`.
   - **Note:** `Plug.review` already writes an entry with the hash for an
     enabled Nix plugin (`plugins.py:1009-1013`). That's expected: it
     records "on", and an explicit off is never turned on.
   - Tests:
     - a `plugins_on` id with no entry loads;
     - an entry with `enabled: false` stays off;
     - a folder plugin in `plugins_on` still needs its hash consent.
   - Verify with:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py test_shared_settings.py
     ```
     Then run the existing plugin test files (`ls tests | grep -i plugin`).

4. **`bin/nixi-companion` + `app/server.py`: `settings migrate`,
   `settings reset-bridge`, `doctor`.** By the coder.
   - **The CLI** gets a case `settings)`, next to `doctor)` (`:224`). It runs
     `"$PY" "$APP/server.py" --settings "${@:2}"`. The Python side is a
     function in `server.py` handling `--settings`, as `--diagnostics` is
     handled.
   - **`migrate`** is one transaction:
     1. Run the CLI's `stop` and `quitwin` (as `stop)` does, `:220`). Then
        wait until no process matches `SRV_RE` or `bridge/bridge.js`
        (10 s), else abort with nothing changed.
     2. Read `config.json`, `nixi.json` and `plugins-state.json`, noting
        each file's mtime.
     3. Copy all three into `~/.local/state/nixi-companion/migrate-<UTC>/`.
     4. Compute all three new contents in memory:
        - `config.json`: drop keys equal to `SHARED.get(k, DEFAULTS.get(k))`.
          Local-only keys stay.
        - `nixi.json`: for the five bridge keys only, drop those equal to
          `nixi-shared.json`'s value, else to the bridge default (`trust`
          guide, `permissionMode` permission). Every other key stays.
        - `plugins-state.json`: drop entries `{"enabled": true}` for ids in
          `plugins_on` whose plugin ships from Nix, because `plugins_on`
          gives them anyway. Keep every off entry and every folder plugin's
          `sha256`.
        - For keys that differ from a shared value, ask "keep as local
          override? [y/N]". `--keep a,b` and `--drop-all` answer without
          asking.
     5. Write every new file as `<file>.migrate.tmp`. Check all three
        mtimes are unchanged. Then `os.replace` all three. If any check
        fails, nothing is replaced: remove the temp files and exit 1. If a
        replace fails part-way, copy the backup over all three and exit 1.
     6. Move folder copies whose id ships from Nix into
        `<backup>/plugins/`. Leave `private_plugins` alone.
     7. In a `finally`, start Nixi again (`nixi-companion show`) and print
        what changed plus the undo command.
   - **`reset-bridge`**: under the same stop and wait, remove the five
     bridge keys from `nixi.json` (atomic replace), then start Nixi again.
   - **`doctor()`** (`:4664`) gets a "── shared settings ──" section:
     - the files and whether they parse;
     - `SHARED_NOTES`;
     - companion overrides as `key: local → shared`, with `look` as
       "differs";
     - bridge overrides;
     - missing `private_plugins`;
     - listed voices that are missing or stale.
   - Tests:
     - backup;
     - the equal-value drop in each file;
     - `--keep`/`--drop-all`;
     - a changed mtime on the **second** file replaces nothing;
     - a failed replace part-way restores all three;
     - superseded plugins move and private ones stay;
     - `reset-bridge`;
     - the doctor section.
     
     Patch the stop/start and process checks.
   - *Deviation (coder):* the shell case runs `stop; quitwin` before
     calling Python, because the Python helper's own command line matches
     `SRV_RE`. Python then waits (excluding its own pid) and restarts Nixi
     in a `finally`.
   - Verify with:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py test_shared_settings.py
     ```

5. **`app/static/index.html`: the panel.** By the coder.
   - In `renderSettings`, a setting whose key is in `info.overrides` gets a
     small note in the panel's existing note style: "differs from your NixOS
     config". Next to it goes a **Use shared** button. The button posts
     `/api/settings/reset {key}`, shows "Restarting Nixi…", and leaves the
     rest to the restart.
   - With `info.shared` empty, nothing changes.
   - *Deviation (coder):* the overrides are listed in one block at the top
     of the settings panel (`#sharedList`), one note and **Use shared**
     button per key, rather than next to each setting: several settings
     have no single row to attach to.
   - Verify with:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py --deadline 1800 test_character_fit.py test_accessories_fit.py
     ```
     Also run any `test_settings*` file.

### nixi-nixarchy (a worktree off `origin/master`)

6. **`nix/hm-module.nix`: two options.** By the coder.
   - **`services.nixi.companion.settings`:** type
     `(pkgs.formats.json { }).type`, default `{ }`. When non-empty, write
     `xdg.configFile."nixi-companion/shared.json".text = builtins.toJSON cfg.companion.settings`,
     next to `peers.json` (`:382`).
   - **`services.nixi.settings`:** a submodule of `nullOr` fields:
     - `trust`: `enum [ "guide" "mechanic" ]`;
     - `permissionMode`: `enum [ "permission" "yolo" ]`;
     - `agent`, `model`, `reasoningEffort`: `str`.
     
     When any field is set, write `xdg.configFile."omarchy/nixi-shared.json"`
     with the fields that aren't null.
   - **Option descriptions** say:
     - the store is world-readable, so no secrets, private plugins or
       personal text;
     - a local change wins until reset.
   - **`flake.nix`** gets `checks.hm-companion-shared`, in the style of
     `hm-companion-peers` (`:108-154`). It checks that:
     - both files are written with the given values;
     - empty options write neither;
     - a bad enum fails evaluation.
   - Verify with:
     ```bash
     nix flake check
     ```
     Run it in the worktree.

7. **`bridge/bridge.js` + `Ask.qml`: the shared layer.** By Codex.
   - **`bridge.js`:**
     - `sharedPath = join(settingsDir, "nixi-shared.json")`.
     - `loadSettings` (`:98`) and the follow path use
       `{...shared(trust, permissionMode), ...local}`. A missing or broken
       shared file is ignored.
     - The watcher filter (`:118-123`) also accepts `nixi-shared.json`.
     - Nothing else changes: `mergeSettings`, Guide and Codex.
   - **`Ask.qml`:**
     - A second `FileView` reads and watches `nixi-shared.json`. The
       `agent`, `model` and `reasoningEffort` defaults come from it when
       `nixi.json` lacks them.
     - *Deviation (Codex review, Quickshell 0.3.2):* the `FileView` watch
       misses a deploy's symlink swap, so `open()` also calls
       `sharedSettingsFile.reload()`. A deployed change reaches the card on
       its next open, not live.
     - The card keeps a set of keys you changed in this run, filled where
       each card setting is changed by the user.
     - `writeSettings` (`:225-230`) merges only those keys over the disk
       data, never all of `cardOwnedSettings()`. A key you never touched is
       never written, so it never becomes an override.
     - Other keys on disk, including the bridge's, survive as today.
   - Tests:
     - `bridge/settings.test.js` and `settings-follow.test.js`:
       - shared → local precedence;
       - a real symlink swap, including a missing target in between and a
         trust change in flight;
       - a broken shared file is ignored.
     - `tools/test_nixi.py` (its Ask.qml checks, `:604`):
       - the second `FileView`;
       - `writeSettings` writes only changed keys;
       - unrelated keys survive.
   - Verify, from the worktree root:
     ```bash
     (cd bridge && node --test)
     python3 tools/test_nixi.py
     ```
     Symlink `bridge/node_modules` from the main checkout for the run, and
     remove it after.
   - Traps:
     - For Codex, a trust change ends the conversation (`:165-167`), as now.
     - Never weaken the click-only sends or Guide.

### Lead

8. **Review, PRs, declare, deploy, migrate, check.**
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
   - **Run in nixi-nixarchy:**
     ```bash
     nix flake check
     (cd bridge && node --test)
     python3 tools/test_nixi.py
     ```
   - **PRs** in both repos, each commented "@codex review".
   - **nixos_config** (new issue, worktree off `origin/main`), in
     `hosts/common/nixos/omarchy-nixi-companion.nix`:
     - `services.nixi.companion.settings`: p620's current `SHARED_OK` values
       from `config.json` at that time, plus
       `plugins_on = [ "news" "nix-status" "rss-headlines" ]`,
       `private_plugins = [ "you" ]` and `voices` (the table above);
     - `services.nixi.companion.plugins` with the three plugins from the
       companion input;
     - `services.nixi.settings` from p620's `~/.config/omarchy/nixi.json`.
     
     Bump both inputs, build p620 and razer, and check with
     `diff-closures`. Open the PR, wait for CI, and merge.
   - **Deploy:**
     - Read the agent bus, then post.
     - Copy the uncommitted `nixarchy-theme.nix` into the deploy worktree if
       it differs.
     - p620: `nh os switch .`.
     - razer: `just deploy-via-p620 razer`.
   - **On each host:** run `nixi-companion settings migrate`, then
     `nixi-companion doctor`, which must show no overrides on either side.
   - **Live checks:**
     - a voice change on razer shows "differs", and **Use shared** puts it
       back after the restart;
     - a shared value change in nixos_config reaches both machines on the
       next deploy;
     - `news` comes from Nix and is on;
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
  (cd bridge && node --test)
  python3 tools/test_nixi.py
  ```
- **nixos_config:** both hosts build, and `diff-closures` shows only Nixi and
  the new files.
- **Live:** the checks in step 8.

## Rollback

Each part can be undone on its own:
- **The settings layer:** revert the nixos_config PR, which removes the
  shared files. Nixi then works from `config.json`, which `migrate` left
  holding only real differences. Restore the `migrate` backup to get the old
  files back exactly.
- **The code:** revert the companion or nixi-nixarchy PR. An old companion
  ignores `shared.json`, and an old bridge ignores `nixi-shared.json`.
