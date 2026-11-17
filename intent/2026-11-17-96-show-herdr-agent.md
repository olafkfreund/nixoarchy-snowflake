---
status: draft
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
- Every other path stays as it is: typed sends, status questions, "show me"
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
  send.
- Only argv built from validated ids (`PANE_RE`, `_ATTN_ID`), never a shell
  string. The pane and session come from `herdr agent list`, not from the
  model's reply.
- Never type into or send keys to any window. Focus only, as
  `_attention_focus` does.
- A failed focus is silent and never fails or delays the send or the spoken
  reply. herdr or hyprctl may be missing, or herdr's window may be closed.
- When several herdr windows are open, bring up the one showing that agent's
  herdr session, or none. Never a wrong one.
- Tests must not import `server.py` under the real HOME (#176) and must not
  call the real herdr or hyprctl.

## Open questions

1. **Raise the window, or only switch herdr's tab?** Raising it moves you to
   another workspace in the middle of whatever you were doing. Switching the
   tab is quiet, but you only see it the next time you look at herdr.
   Recommendation: raise it (the issue asks for it), with a config switch to
   turn it off. The default is on.
2. **When the send was typed in Nixi's window rather than spoken, show the
   agent too?** Recommendation: yes. Both go through the same card, and the
   reason to show it is the same.
