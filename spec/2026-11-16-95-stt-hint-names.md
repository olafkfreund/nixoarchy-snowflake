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
the user's own and stays; an empty string is a choice and stays too. The file
is not rewritten, and `save_config` (`:5821`) only writes the keys it is
given, so the old string stays on disk. That is fine: the migration runs in
memory at every start.

**3. `stt_names()`: the machine's names, never blocking.** Returns the cached
list at once. A module lock `_names_lock` guards only three short sections:
reading the list, checking and claiming the single refresh (`_names_busy`),
and swapping in a finished list. When the list is older than 60 s and no
refresh is running, it claims the refresh and starts a daemon thread. The
caller still gets the old list. The thread collects **outside** the lock, then
swaps the new list in and stamps the time. A `finally` clears `_names_busy`,
also when collecting or `Thread.start()` fails, so one failure never stops
later refreshes. Each source has its own `try`, so a source that fails or
returns bad rows only loses its own names. The refresh gathers, in this order:

- running herdr agents: `os.path.basename(cwd)` from `herdr_agents()`;
- saved projects: the keys of `quick.projects()`;
- fleet hosts: the `name` of each row of `peers.current()`. This reads the
  cached list and has no side effects. `peers.load()` and `snapshot()` are
  not called.

Each name is kept only if it is a `str` and
`re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_ .-]{1,31}", name, re.ASCII)`: 2 to 32
ASCII characters, no slashes, no newline or other control characters
(`fullmatch`, because `$` would also match before a trailing newline).
Names are deduplicated case-insensitively in first-seen order and capped at 30.
The cache holds only these names. Removing names already in the prompt
happens when the prompt is built (step 4), against the prompt actually used,
so a change of hint or language takes effect at once. The first call after
start returns `[]`.

**4. Prompt order.** faster-whisper 1.2.1 keeps only the **last**
`max_length // 2 - 1` = 223 tokens of `initial_prompt`
(`faster_whisper/transcribe.py:1550`, `previous_tokens[-(...):]`).
`max_length` (448) and how `initial_prompt` becomes `previous_tokens` are
checked in the plan's first step against the same installed source. So what
may be dropped goes first. In `run_whisper`, only when `hint is None`:

```
base  = <today's prompt>
names = [n for n in stt_names() if n.casefold() not in base.casefold()]
prompt = (", ".join(names) + ". " if names else "") + base
```

The check is a substring test against the whole prompt, so a name with a
space ("my app") works like a one-word name.

Today's prompt stays as it is: the English hint, or the wake word plus the
local hint for nb and pl. The wake word and the user's words are at the end,
which is the part that survives. Explicit `hint=` callers are untouched: the
wake check (`:4552`) and the mic test (`:4658`).

**Where names help:** push-to-talk and the listen that starts after a bare
"Hey Nixi" (both `:4069`), and follow-up replies (`:4552` with `follow`).
**Where they do not:** a request said in the same breath as the wake word
("Hey Nixi, ask nixarchy-microvm…"). That clip is transcribed once with the
wake-only hint, and adding names there would change the wake check, which
the intent rules out. Left as a possible follow-up.

The user's words are never cut by the names, except when the user's hint
is itself over the budget on its own (the case the intent left as today).

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
- **Prompt language:** names are ASCII only (the regex), project names, also in the nb and pl
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
   - a source that raises or returns bad rows loses only its own names; the
     other sources still give theirs;
   - names that are not strings, end in a newline, are not ASCII or are too long are dropped;
   - two stale calls at once start exactly one refresh; a read while the
     refresh is blocked returns the old list at once; a refresh after a
     failed one works;
   - migration: no saved hint, the exact old default, an empty hint, a
     custom hint, and a reload after an unrelated `save_config`;
   - a long list of names plus the default hint and a custom hint: the hint
     is the end of the prompt, and only names are lost when it is too long
     (measured with the real tokenizer's token count, not `FakeModel`);
   - the existing exact-prompt test (`:219`) stubs `stt_names()` to `[]`.
   The cache and thread state are reset in `setUp`, and every refresh thread
   is joined in `tearDown` before the stubs are removed. `quick.cfg` is wired
   or `quick.projects` stubbed.
   Run: `python -m pytest tests/test_whisper_switch.py -q`, then the full suite.
2. **Offline A/B on your real voice.** You record about 12 short WAVs once:
   eight names ("ask nixarchy-microvm…", "factory-gitops", "p510",
   "razer"…), two plain sentences, and two near-silent clips. A script
   transcribes each one with the real model on this machine, once with the
   old prompt and once with the new one. It reports names heard correctly
   and words invented from silence. Pass: names correct with the new prompt
   ≥ with the old; plain sentences no worse; nothing from silence.
3. **Live on the running companion**, built from this branch with the
   test-build recipe (systemd-run with RemainAfterExit), after at least one
   refresh (60 s after start):
   - push-to-talk: say three agent names and one host; check the heard caption;
   - say "Hey Nixi", wait for listening, then say a name; and a follow-up
     reply with a name in it;
   - near-silence through push-to-talk (press, stay quiet, release) three
     times: nothing is sent;
   - "Hey Nixi" still wakes him; `nixi-companion doctor` mic test still passes;
   - the live config's old hint is migrated: a debug log line at startup
     says the old default was replaced.
