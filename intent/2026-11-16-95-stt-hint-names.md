---
status: draft
issue: 95
author: olafkfreund
---

# Intent: Speech hint from this machine's names

## Problem

Whisper is given a fixed word list (`stt_hint`, `app/server.py:172`) as its
`initial_prompt`. Two things are wrong with it:

- The default names `pacman` and `Arch Linux`, which nobody on NixOS says,
  and leaves out the words they do say (`nix`, `flake`, `NixOS`, `rebuild`).
- The names said most often to Nixi are not in it at all: the herdr agents
  and their project folders ("ask the snowflake agent…"), the projects saved
  in the companion's config, and the fleet's host names (p620, razer, p510).
  Whisper mishears such names, and then herdr routing and project lookups miss.

Users can add names by hand to `stt_hint`, but few do, and the list goes
stale as agents and projects come and go.

Idea taken from kvm404/Auren (`ears.vocabulary()`): the user's own words
first, then a base list, then names found on the machine.

## Proposed outcome

- Saying the name of a running herdr agent's folder, a saved project, or a
  fleet host is transcribed as that name more often than today.
- The English default hint fits NixOS: no `pacman` or `Arch Linux`.
- A user who set their own `stt_hint` keeps it, first in the prompt.
- Nothing is sent anywhere new: the names stay in the local Whisper prompt.

## Affected users and systems

- `app/server.py`: the `stt_hint` default and `run_whisper`'s prompt.
- Every host running the companion; English first. Norwegian and Polish
  prompts get the same machine names appended.
- `docs/GUIDE.md` settings row for `stt_hint`; `tests/test_whisper_switch.py`.

## Constraints

- Existing configs hold the old default verbatim: the first run writes every
  default into `config.json` (`load_config`, `app/server.py:277`), and this
  machine's config has it. A saved value equal to the old default must be
  treated as the default (as `load_config` already does for `whisper_model:
  base.en`), or nobody gets the new hint. A hint the user really edited is kept.
- Whisper reads at most ~224 tokens of prompt (to verify in the spec); machine
  names fill only what is left after the user's words and the base list, and
  are dropped first. A user hint that is itself too long is passed as today.
- Explicit `hint=` callers keep their exact prompts: the wake check
  (`app/server.py:4552`) and the mic test (`:4658`). Norwegian and Polish keep
  their wake words first.
- Names are folder basenames and saved project keys only: bounded length,
  no paths, no control characters. A failing source (herdr down, bad JSON)
  just adds no names.
- Hosts are the `name` fields of configured peers, read without calling
  `peers.load()` (it resets polling state); no peers configured → no hosts.
- Must not slow down a transcription: no herdr call on the hot path that can
  block it (herdr calls already have a 3 s timeout; that is too long here).
- Window titles and pane text never go into the prompt, only folder, host
  and project names.
- Tests must use `nixi_env` (no real HOME, no live herdr).

## Open questions

1. Hosts: configured peer names from `peers.json`, nothing when none are
   configured, no hard-coded fleet list? (Proposed: yes; Codex agrees.)
2. Also do #2 from the Auren review (switch herdr to the agent when Nixi
   prompts it) in this task, or keep it a separate issue? (Proposed:
   separate; Codex agrees, since `session_send()` has its own routing.)

Whether more words in the prompt help or hurt is not proven: Whisper can
echo hint words on near-silence (`app/server.py:3754`). The spec's
verification must measure it live, not assume it.
