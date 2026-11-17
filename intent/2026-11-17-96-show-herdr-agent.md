---
status: approved
issue: 96
author: olafkfreund
---

# Intent: show the herdr agent when Nixi prompts it

## Problem

When you ask Nixi by voice to send a prompt to a herdr agent ("ask
nixarchy-microvm to run the tests"), Nixi shows a click-only card. After you
click, Nixi's own agent runs `herdr agent prompt <pane> <text>`
(`session_send()`, `app/server.py:6441`). The text lands in the agent's pane,
but nothing on screen moves. That agent is usually in a herdr tab you aren't
looking at, often in a herdr window on another workspace. So you can't see
whether it started, what it's doing, or that the prompt even arrived, unless
you go and find it yourself.

Nixi can already move focus to an agent. `_attention_focus()` (`:1485`) runs
`herdr --session <s> agent focus <pane>` and `hyprctl dispatch focuswindow`
when you answer an agent's nudge. A send never uses it.

The idea comes from kvm404/Auren's `show_agent`. It was split out of #95.

## Proposed outcome

- After a voice send to a herdr agent goes through, herdr switches to that
  agent's tab. herdr's window (class `org.omarchy.herdr`) comes to the front
  on its own workspace, so you see the agent start on your prompt.
- Nothing moves if the send didn't happen: the card was declined, the command
  failed, or the turn stopped.
- Every other path stays as it is: status questions, "show me"
  (`session_show`, which opens an attach window) and the nudge focus.

## Affected users and systems

- `app/server.py`: the send path (`session_send`, the bridge's tool-result
  handling) and the focus helper it could reuse.
- herdr (the CLI's `agent focus`) and Hyprland (`hyprctl`) on the desktop.
  p620 is the only host running Nixi with herdr today.
- The owner, whenever they send by voice.

## Constraints

- Only after the send succeeded, never before the click or on a declined card.
  The click-only card is the consent (#95) and must stay the only path to a
  send. A click proves consent, not delivery. Today the bridge forwards a
  tool event with only a title and a status (`run_bridge`, `:6525`). It has
  no command, id or exit code, and `done` reports success whatever the
  tools did. So "succeeded" must be tied to the exact approved
  `herdr agent prompt <pane>` command in this turn. An unknown outcome leaves
  focus alone.
- Tied to its turn. Approval can wait up to 600 s (`ask_bridge`), and the
  bridge process outlives turns. A stopped turn, a newer turn, or an agent
  that has gone away by then means no focus. The target is looked up again
  just before focusing.
- The right herdr session. `herdr_agents()` and the send's
  `herdr agent prompt` use herdr's default session. Several sessions run
  at once on p620 (default, Devlopment-Local, Synechron-development), and
  `_attention_focus` needs a session plus window pids. It doesn't find a
  window by class. The spec must establish which session and which
  `org.omarchy.herdr` window shows the pane, before anything is raised.
- Only argv built from validated ids (`PANE_RE`, `_ATTN_ID`), never a shell
  string. The pane and session come from `herdr agent list`, not from the
  model's reply.
- Never type into or send keys to any window. Focus only, as
  `_attention_focus` does.
- A failed focus is silent and never fails or delays the send or the spoken
  reply. It runs in the background, bounded, because `_attention_focus` can
  take three commands with 3 s timeouts each. herdr or hyprctl may be missing, or herdr's window may be closed.
- When several herdr windows are open, bring up the one showing that agent's
  herdr session, or none. Never a wrong one.
- Tests must not import `server.py` under the real HOME (#176) and must not
  call the real herdr or hyprctl.

## Open questions

Decided at approval (2026-11-17): both recommendations below.


1. **Raise the window, or only switch herdr's tab?** Raising it moves you to
   another workspace in the middle of whatever you were doing. Switching the
   tab is quiet, but you only see it the next time you look at herdr.
   Recommendation: raise it (the issue asks for it), with no setting to
   turn it off. A setting can be added if raising gets in the way.
2. **When the send was typed in Nixi's window rather than spoken, show the
   agent too?** Recommendation: yes, as long as it is the same confirmed
   send. `session_send` has one caller, `/api/quick` (`:8873`), which
   doesn't tell speech from typing. The spec must check whether typed
   input reaches it.
