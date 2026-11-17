---
status: draft
issue: 96
intent: intent/2026-11-17-96-show-herdr-agent.md
---

# Spec: show the herdr agent when Nixi prompts it

## What I found first

Today Nixi sees **no** herdr agents on p620. Nixi's process has no `HERDR_*`
variables, so its `herdr agent list` (`herdr_agents()`, `app/server.py:6347`)
asks herdr's default session, and that session is empty. Your agents live in
named sessions:

| herdr session | Agents | Window |
|---|---|---|
| default | 0 | none |
| Devlopment-Local | 17 | kitty `org.omarchy.herdr`, child `herdr --session Devlopment-Local` |
| Synechron-development | 2 | kitty `org.omarchy.herdr`, child `herdr --session Synechron-development` |

So voice sends and status questions answer "no herdr" today, and #95's name
hint gets no herdr names live. #96 can't show an agent that Nixi can't find,
so this spec makes Nixi look in every running session first (part 1).

## Design

### Part 1: agents from every running herdr session (`app/server.py`)

- `herdr_sessions()`: `herdr session list --json`. It keeps the sessions with
  `running: true` whose `name` matches `SESSION_RE =
  [A-Za-z0-9][A-Za-z0-9_.-]{0,63}`. There is no leading dash: a session
  literally named `--help` exists on p620 and must never become an option.
- `herdr_agents()` runs `herdr --session <s> agent list` for each session.
  Each agent dict gets `"session": s`. A session that fails or times out is
  skipped; the others still count.
- `_herdr()`'s allowlist gains exactly these shapes:
  - `herdr session list --json`
  - `herdr --session <s> agent list`
  - `herdr --session <s> agent read …`
  
  `<s>` must match `SESSION_RE`. Everything else is still refused.
- `herdr_read(pane, session)` and `session_status` read with the agent's
  session.
- `session_send` tells nixi's agent to run
  `herdr --session <s> agent prompt <pane> <text>`. The bridge already treats
  any command that mentions herdr as a click-only send (`isHerdrWrite`, and
  `HERDR_WRITE` accepts `--session` for the audit line, nixi-nixarchy
  `bridge/herdr-policy.js:9-17`).
- `resolve_session` doesn't change. The same folder name in two sessions is
  two hits, so Nixi asks "which" as it does today.
- #95's `_collect_names()` gets the herdr names from all sessions with no
  change of its own.

### Part 2: the bridge says which tool finished (nixi-nixarchy `bridge/bridge.js`)

Today's events can't prove that a send worked. The bridge's `tool` event
carries a title and a status but no id (`bridge.js:486-490`), and a turn's
`done` reports success whatever the tools did. The Claude adapter marks a
tool `failed` exactly when its result is an error, so a Bash call that exits
non-zero is `failed` (claude-agent-acp `tool-calls/renderer.js:81`). Two
fields are added, and nothing else changes:

- the `tool` event gets `toolCallId: update.toolCallId`;
- the `permission` event gets `toolCallId: params.toolCall?.toolCallId`.

The companion ignores fields it doesn't know, so an old companion is fine
with the new bridge. A new companion with an old bridge sees no id and never
focuses. It fails closed.

### Part 3: focus after a confirmed send (`app/server.py`)

- `session_send` records the send it is about to ask for:
  `SEND_PENDING = {"command": <the exact command string>, "session", "pane",
  "at": monotonic}`. One at a time; a newer send replaces it, and it expires
  after 15 minutes. The 600 s approval wait fits inside that.
- In `run_bridge`, the `approve` worker checks three things: the permission
  has `confirm == "click"`, its `command` equals `SEND_PENDING["command"]`
  byte for byte, and the chosen option's kind starts with `allow`. If all
  three hold, it stores that permission's `toolCallId` in this
  `run_bridge` call's own state. Any other answer, or no id, clears it.
- On a `tool` event whose `toolCallId` equals the stored id:
  - `completed`: start one daemon thread `show_agent(session, pane, turn)`
    and clear the id.
  - `failed`: clear the id and do nothing.
- When `run_bridge` returns (done, error, fatal or stopped), the stored id
  and `SEND_PENDING` are dropped.
- `turn` is a module counter that `run_bridge` increments when it starts.
  `show_agent` gives up if `ST.stopped` is set or a newer turn has started.
  It checks both before every step that changes the desktop.
- `show_agent`:
  1. Lists that session's agents again. If the pane is gone, it stops.
  2. Finds the window. It looks at Hyprland clients with class
     `org.omarchy.herdr`, and for each one reads its child processes from
     `/proc`. A window matches when a child's argv is exactly
     `herdr --session <s>`, or `herdr` alone for the default session.
     Exactly one match gives that window's pid. Zero or several give no pid.
  3. Calls the existing `_attention_focus({"herdr": {"pane", "session"},
     "pids": [pid] or []})`. That runs `herdr --session <s> agent focus
     <pane>`, then `hyprctl dispatch focuswindow pid:<pid>`. With no pid,
     herdr's tab switches but no window is raised.
  
  Every error is caught and ignored. Nothing is spoken and nothing types.
- Spoken and typed sends both reach `session_send` through `/api/quick`
  from the page's one submit path (`app/static/index.html:3634`), so both get
  this, as decided at intent approval.

## Alternatives rejected

- **Match the tool by title or by the "next completed tool".** The title
  format belongs to the adapter and changes between versions. A
  read-only tool that runs in parallel could be mistaken for the send. Both
  break "an unknown outcome leaves focus alone".
- **Poll herdr for the agent changing state after the send.** An agent that
  is already working changes state anyway, so this proves nothing.
- **Have the companion run `herdr agent prompt` itself after the click.**
  That would add a second way to send. The card plus nixi's agent is the only
  path (#95).
- **Raise any `org.omarchy.herdr` window, or match by window title.** The
  title is herdr's current tab title, not its session, so it could raise the
  wrong one. The constraint is the right window or none.
- **Give Nixi's service a fixed `HERDR_SESSION`.** That only covers one
  session, and it breaks again when you rename or add one.
- **A setting to turn the raise off.** Not wanted for now, decided at intent
  approval.

## Risks

- **Two repos, so deploy order matters.** The companion change alone finds
  agents in every session and sends with `--session`, but never focuses
  until the bridge with ids (nixi-nixarchy) is deployed too. That is safe in
  either order.
- **Slower lookups.** `herdr_agents()` makes one call per running session
  (three on p620, each with a 3 s timeout). This is on the path of a spoken
  send or status question, though herdr normally answers in milliseconds.
  #95's background name refresh absorbs it.
- **Pane ids could repeat across sessions.** Every lookup, send and focus
  carries the session, so a pane is never looked up without one.
- **Focus moves you to herdr's workspace.** That is intended, as approved.
  It never happens for a declined, failed or stopped send.
- **Window shapes the matcher doesn't know**, such as `herdr session attach
  <s>` or a herdr desktop app. Those windows don't match, so only herdr's tab
  switches. That is safe, and a shape can be added when one shows up.
- **Hosts.** p620 only. Razer has no herdr sessions running Nixi sends today.

## Verification

- **Unit tests** (`tests/`), using `_ServerEnv` and `nixi_env`, never the
  real HOME (#176). Fake `herdr` and `hyprctl` are injected as functions, and
  the real ones never run.
  - Sessions: running vs stopped; a session named `--help` is never used;
    one failing session doesn't hide the others; each agent carries its
    session.
  - The `_herdr` allowlist refuses anything outside the listed shapes.
  - `session_send` asks for `herdr --session <s> agent prompt …` and records
    `SEND_PENDING`.
  - Focus:
    - Confirmed, then `completed`, focuses exactly once.
    - Declined, `failed`, no id, a different command, a different id, a
      stopped turn, a newer turn, or the pane gone: no focus.
    - The `run_bridge` return path clears the pending send.
  - The window matcher with fake `/proc` trees:
    - one match gives its pid;
    - two matches, or a `session attach` window, give no pid;
    - the default session matches a bare `herdr`.
- **Bridge test** (nixi-nixarchy `bridge/herdr-bridge.test.js`): `tool` and
  `permission` events carry `toolCallId`.
- **Full suite** with `.github/ci/run_tests.py`, `nix flake check`, and the
  bridge's `node --test` in nixi-nixarchy.
- **Live on p620**, after posting on the agent bus, on a test build of both
  repos:
  - Ask by voice "what is factory-gitops doing" and check it now finds the
    agent.
  - Send a prompt by voice to an agent in Devlopment-Local and click. herdr's
    tab switches and its window comes up.
  - Decline a card: nothing moves.
  - Send to an agent whose pane has just closed: nothing moves.
  - Stop the turn before clicking: nothing moves.
