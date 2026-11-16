---
status: draft
issue: 95
spec: spec/2026-11-16-95-stt-hint-names.md
coders:
  1: coder    # two small, plain edits next to an existing migration
  2: codex    # small but tricky: a lock-light background refresh that must never block or wedge
  3: coder    # many test cases in one existing file, following its own setUp/tearDown style
reviewers:
  - codex     # independent read of the concurrency in step 2 and the test isolation in step 3
---

# Plan: Speech hint from this machine's names

Self-contained. Everything below was decided in the approved spec; nothing
here needs the intent or spec to implement.

## Decisions carried over

- All code in `app/server.py`. No new module, no new setting, no new dependency.
- New English default hint: drop `npm`, `pacman`, `Arch Linux`; add `nix`,
  `flake`, `NixOS`, `nixos-rebuild`, `home-manager`, `herdr`. Keep the old
  string as `_OLD_STT_HINT`.
- `load_config`: a saved `stt_hint` exactly equal to `_OLD_STT_HINT` is
  dropped in memory so the default applies. Empty and custom values stay.
  The file is not rewritten. Log one line to stderr when it happens:
  `[nixi] stt_hint: old default replaced`.
- `stt_names()` returns cached names immediately. A refresh runs on a daemon
  thread when the cache is over 60 s old and none is running. The lock covers
  only reading the cache, claiming the refresh and swapping in the result.
  Names are collected outside the lock, and a `finally` always releases the
  claim, also when `Thread.start()` fails.
- Sources, in order, each in its own `try`: `os.path.basename(cwd)` of
  `herdr_agents()`; keys of `quick.projects()`; `name` of each
  `peers.current()` row. Never `peers.load()` or `peers.snapshot()`.
- Name filter: `isinstance(n, str)` and
  `re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_ .-]{1,31}", n, re.ASCII)`.
  Deduplicate case-insensitively in first-seen order; cap 30. The first call
  returns `[]`.
- In `run_whisper`, only when `hint is None`: `base` = today's prompt;
  `names` = cached names whose casefold is not a substring of `base.casefold()`;
  `prompt = ", ".join(names) + ". " + base` (just `base` when there are no
  names). Names go first because faster-whisper 1.2.1 keeps the last 223
  tokens (`max_length = 448`, `transcribe.py:722`; `previous_tokens[-(448//2-1):]`
  at `:1550`; the initial prompt enters at `:1147`/`:1187`, checked 2026-11-16).
- Explicit `hint=` callers are not changed: wake check `app/server.py:4552`
  and mic test `:4658`. Names do not reach a request said in the same breath
  as the wake word. That is accepted and out of scope.

## Steps

1. `app/server.py:172-173` (DEFAULTS `stt_hint`) and `load_config` `:277-284`:
   - Add `_OLD_STT_HINT = "<the current string, verbatim>"` just above
     `DEFAULTS` and replace the default text as decided.
   - In `load_config`, after the `whisper_model == "base.en"` line (`:282-283`):
     `if user.get("stt_hint") == _OLD_STT_HINT: del user["stt_hint"]` plus
     the stderr line.
   → verify: `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_whisper_switch.py` still passes
   (the test at `:213-219` compares to `DEFAULTS`, so it follows the change).
   Traps: `DEFAULTS` is also used at `:3742` for nb/pl: it must stay a single
   source; do not copy the string. Importing `server` under the real HOME
   writes the user's config (#176), so run tests only through the test suite.

2. `app/server.py`: add `stt_names()` and its helpers just above
   `run_whisper` (`:3727`), and change the prompt line in `run_whisper.go`
   (`:3744`, `prompt = hint if hint is not None else (...)`):
   - module state: `_names_lock = threading.Lock()`, `_names = []`,
     `_names_at = 0.0`, `_names_busy = False`; `NAMES_TTL = 60`, `NAMES_MAX = 30`.
   - `_collect_names()` gathers the three sources (each in its own
     `try/except Exception`), filters and deduplicates, and returns the list.
     `quick.projects()` may raise when `quick.cfg` is None (not wired yet):
     the `try` covers it.
   - `_refresh_names()`: try collect → under the lock, swap the list and stamp
     `time.monotonic()`; finally, under the lock, clear `_names_busy`.
   - `stt_names()`: under the lock, read the list; if it is stale and not busy,
     set busy. Outside the lock, start
     `threading.Thread(target=_refresh_names, daemon=True)`; if `start()`
     raises, clear busy under the lock. Return the list.
   - In `go()`: keep `base = (local_hint if code == "en" else wake + " " + local_hint)`;
     when `hint is None` prepend the filtered names as decided; else
     `prompt = hint`.
   → verify: `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_whisper_switch.py` passes, and
   `python -B -c "import ast,sys; ast.parse(open('app/server.py').read())"`.
   Traps: `herdr_agents()` may block for 3 s: never call it under
   `_names_lock` or on the transcription thread. Do not touch `_whisper_lock`.
   No `print` per refresh (the log is user-facing).

3. `tests/test_whisper_switch.py`: new test class `SttNamesTest(_ServerEnv)`.
   In the existing `WhisperSwitchTest.setUp` (`:13`), patch `stt_names` to
   `return []` for **every** test (start the patcher in `setUp`, stop it in
   `tearDown`): its tests call `run_whisper()` (e.g. `:64`, `:210`) and must
   not start a refresh that reaches live herdr. `SttNamesTest` saves and
   restores the same globals `WhisperSwitchTest` does (`CFG`, `lang.active`,
   `_stt`, `_whisper`, `_whisper_err`, `lang_status`), plus the cache state;
   `_ServerEnv` only isolates HOME per class, not these globals per test. Cases:
   - names before the hint (en); for nb and pl the wake word comes after the
     names; names already in the prompt are left out, including a name with a space;
   - `hint=` callers: the prompt equals the hint exactly, even with names cached;
   - filter: non-str, a trailing `\n`, non-ASCII, a slash, 1 and 33 characters
     → dropped; duplicates differing in case → one; 40 valid → 30;
   - one source raising or giving bad rows leaves the others' names;
   - concurrency, with Events and a `threading.Barrier`, no timing thresholds:
     the collector is stubbed to set `entered` and wait on `release`. Two
     callers released by a Barrier both return, and the collector count is 1.
     While `entered` is set and `release` is not, a third call returns the
     old list (proved by it returning before `release.set()`, with a bounded
     `join(timeout=2)` on the caller thread). After a collector that raises,
     the next stale call refreshes. A patched `threading.Thread` whose
     `start()` raises leaves `_names_busy` False, and the next call starts one.
     `addCleanup(release.set)` runs first, so a failed assertion never leaves
     a worker blocked; workers are joined with `timeout=2` and asserted dead;
   - migration via `load_config()` with a temp `CONF_PATH` file: no hint, the
     exact old default, `""`, a custom hint, and a reload after
     `save_config(volume=…)`;
   - budget: with 30 names of 32 characters, the prompt **ends with** the
     whole base prompt (default hint, and a 150-word custom hint). No
     tokenizer here: the CI shell has no `faster_whisper`, and CI fails on a
     skip that is not allow-listed (`.github/ci/run_tests.py`). The real
     token count is checked in step 5.
   `setUp` resets `_names`, `_names_at`, `_names_busy`; cleanup releases any
   Event, then joins each refresh thread with a timeout (keep references) before
   the mocks are removed. Stub `herdr_agents`,
   `quick.projects` and `peers.current` with `mock.patch.object`.
   → verify: the single-file run above, then the full suite (see Tests).
   Traps: tests must use `_ServerEnv` (throwaway HOME, `nixi_env` runtime
   dir); never the real config or live herdr.

4. `docs/GUIDE.md:480`: the `stt_hint` row: the default starts "Hey Nixi,
   Claude, …"; the description adds "herdr agent folders, saved projects and
   fleet peers are added on their own". Done by me (one line).
   → verify: read it back.

5. Offline A/B on the owner's voice (no repo changes; scratchpad script).
   The owner records 12 clips with `pw-record --rate 16000 --channels 1
   --format s16`: 8 names, 2 plain sentences, 2 silent. A script imports the
   built package's `server` under a throwaway HOME (the `_ServerEnv` pattern),
   stubs `stt_names()` to the live list captured once, and runs
   `run_whisper` on each clip with names off and on.
   Token checks with the model's own tokenizer: first confirm in the
   installed `faster_whisper/transcribe.py` that `self.max_length = 448` and
   that `initial_prompt` tokens are cut to the last `448 // 2 - 1`. Then
   encode (a) the real names plus the default hint, (b) 30 names of 32
   characters plus the default hint, and (c) the same plus a custom hint
   whose own token count is 150 (under 223). For each, the last 223
   tokens decode to text that ends with the whole hint.
   Pass: names right with names on ≥ off; plain sentences no worse; silent clips give "".
   Done by me.

6. Live test (me): post on the agent bus first, then build and start this
   branch with the test-build recipe:
   `nix build .#default -o <scratch>/result`, then
   `AGENT_BUS_ANNOUNCED=1 systemd-run --user --unit=nixi-pr95 -p RemainAfterExit=yes -E HYPRLAND_INSTANCE_SIGNATURE=<live sig from /run/user/1000/hypr> <scratch>/result/bin/nixi-companion restart`.
   Warm-up: one push-to-talk with a plain sentence (this triggers the first
   refresh; the wake path does not, it passes its own hint). Then confirm the
   refresh finished: call `stt_names()` in the running server through a one-off debug
   check, or, without one, do a second warm-up press 5 s later. Only then score:
   push-to-talk three agent names and one host; a bare
   "Hey Nixi", then a name; a follow-up reply with a name; three silent
   push-to-talk presses (nothing sent); "Hey Nixi" still wakes him;
   `nixi-companion doctor` mic test passes; `nixi-companion log` shows
   `stt_hint: old default replaced`.
   Traps: the owner's own `nixi-companion restart` goes back to the installed build.

## Tests

```bash
nix develop .#ci -c python3 -B .github/ci/run_tests.py test_whisper_switch.py
nix develop .#ci -c python3 -B .github/ci/run_tests.py --exclude test_character_fit.py --exclude test_accessories_fit.py
nix develop .#ci -c python3 -B .github/ci/run_tests.py --deadline 1800 test_character_fit.py test_accessories_fit.py
nix build -L .#packages.x86_64-linux.default && nix flake check -L
```

Expected: all pass. The plugin sandbox run is not needed: nothing touches
`app/plugins.py`, its tests or `nix/package.nix`.

## Rollback

Revert the merge commit. No data or config is written: the migration is in
memory only, so the old hint comes back on the next start.
