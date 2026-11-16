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

- Whisper reads at most ~224 tokens of prompt; the hint must stay short and
  the user's own words must never be cut.
- Must not slow down a transcription: no herdr call on the hot path that can
  block it (herdr calls already have a 3 s timeout; that is too long here).
- Window titles and pane text never go into the prompt, only folder, host
  and project names.
- Tests must use `nixi_env` (no real HOME, no live herdr).

## Open questions

1. Hosts: take them from `~/.config/nixi-companion/peers.json` (the fleet
   board's list), or skip hosts if no peers are configured? (Proposed: peers.json.)
2. Also do #2 from the Auren review (switch herdr to the agent when Nixi
   prompts it) in this task, or keep it a separate issue? (Proposed: separate.)
