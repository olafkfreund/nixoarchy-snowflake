---
status: draft
issue: 95
intent: intent/2026-11-16-95-stt-hint-names.md
---

# Spec: Speech hint from this machine's names

## Design

All in `app/server.py`; no new module, no new setting.

**1. New English default.** `DEFAULTS["stt_hint"]` (`:172`) drops `npm,
pacman, Arch Linux` and gains `nix, flake, NixOS, nixos-rebuild,
home-manager, herdr`. The old string is kept as `_OLD_STT_HINT`.

**2. Migrate the saved old default.** In `load_config` (`:277`), next to the
`whisper_model: base.en` migration: if the saved `stt_hint` equals
`_OLD_STT_HINT`, drop it so the new default applies. Any other saved value is
the user's own and stays. The file is not rewritten; the next settings save
writes whatever is current, as today.

**3. `stt_names()`: the machine's names, never blocking.** Returns a cached
list at once. When the cache is older than 60 s it starts one background
refresh thread (one at a time, a lock flag) and still returns the old list.
The refresh gathers, in this order:

- running herdr agents: `os.path.basename(cwd)` from `herdr_agents()`;
- saved projects: the keys of `quick.projects()`;
- fleet hosts: the `name` of each row of `peers.current()`. This reads the
  cached list and has no side effects. `peers.load()` and `snapshot()` are
  not called.

Each name is kept only if it matches `^[\w][\w .-]{1,31}$` (2 to 32
characters, no slashes, no control characters). Names are deduplicated
case-insensitively, also against words already in the hint, and capped at 30
names. A source that raises or returns junk adds nothing. The first call
after start returns `[]`.

**4. Prompt order.** faster-whisper 1.2.1 keeps only the **last**
`max_length // 2 - 1` = 223 tokens of `initial_prompt`
(`faster_whisper/transcribe.py:1550`, `previous_tokens[-(...):]`). So what
may be dropped goes first. In `run_whisper`, only when `hint is None`:

```
prompt = (", ".join(names) + ". " if names else "") + <today's prompt>
```

Today's prompt stays as it is: the English hint, or the wake word plus the
local hint for nb and pl. The wake word and the user's words are at the end,
which is the part that survives. Explicit `hint=` callers are untouched: the
wake check (`:4552`) and the mic test (`:4658`).

## Alternatives rejected

- **faster-whisper `hotwords`:** it is only used when there is no
  `prefix`, it has its own 223-token cut, and it adds a second path to test.
  Our prompt path already works.
- **Names first-call synchronous:** a herdr call can take 3 s; that would land
  on a transcription.
- **A settings switch to turn names off:** nobody asked for one. If the live
  test shows harm, the fix is to drop the feature, not add a toggle.
- **Window titles or pane text as names:** untrusted, long, and personal.
- **Rewriting `config.json` during migration:** it would need write locking
  with the settings path. Dropping the value in memory is enough.

## Risks

- **More words can make Whisper hear words on near-silence.** The noise
  filter (`:3754`) catches only fixed phrases. Measured in verification step 3.
- **Long agent lists:** 17 agent cwd entries today (with repeats). The cap
  and the front placement mean only names are lost, never the user's words.
- **Prompt language:** names are ASCII project names, also in the nb and pl
  prompts. That is the same as a user adding them to `stt_hint` today.
- All hosts run the same code. Nothing host-specific; no p510 build needed.

## Verification

1. **Unit tests** (`tests/test_whisper_switch.py`, under the existing
   `_ServerEnv`/`nixi_env`; herdr, projects and peers stubbed):
   - names come before the hint in the prompt; nb and pl keep their wake
     word, and it comes after the names;
   - `hint=` callers get exactly their own prompt;
   - the saved old default migrates, and an edited hint is kept;
   - bad names (paths, control characters, more than 32 characters) are
     dropped; deduplication works; there are at most 30 names;
   - a source that raises gives `[]` and does not raise;
   - `stt_names()` returns at once while a refresh is running.
   Run: `python -m pytest tests/test_whisper_switch.py -q`, then the full suite.
2. **Offline A/B on your real voice.** You record about 12 short WAVs once:
   eight names ("ask nixarchy-microvm…", "factory-gitops", "p510",
   "razer"…), two plain sentences, and two near-silent clips. A script
   transcribes each one with the real model on this machine, once with the
   old prompt and once with the new one. It reports names heard correctly
   and words invented from silence. Pass: names correct with the new prompt
   ≥ with the old; plain sentences no worse; nothing from silence.
3. **Live on the running companion**, built from this branch with the
   test-build recipe (systemd-run with RemainAfterExit): say three agent
   names and one host through "Hey Nixi" and check the heard caption; check
   the wake word still triggers; run `nixi-companion doctor` (the mic test
   prompt is unchanged). The live config's old hint is migrated: the server
   log shows the new default in use.
