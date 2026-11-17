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
  - `herdr --session <s> agent focus <pane>`, for `show_agent`

  `<s>` must match `SESSION_RE`. Everything else is still refused.
- `herdr_read(pane, session)` and `session_status` read with the agent's
  session. `session_show`'s `attach_argv(pane, session)` becomes
  `herdr --session <s> agent attach <pane>`, so "show me" opens the right
  session's pane. Today it would attach through the default session.
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

The send's record is tied to its turn, used once, and checked before every
step.

- **Record the send.** `session_send` builds the ask prompt it returns
  (unchanged wording, with the `--session` command). It also stores
  `SENDS[ask_prompt] = {"command", "session", "pane", "at"}`.
  - At most 8 records; each expires after 15 minutes, which covers the 600 s
    approval wait.
  - The key is the exact prompt, so two quick sends in a row get two records.
    A second `/api/quick` while a turn is busy no longer replaces the first
    one's state (the page calls `/api/quick` before its `busy` check,
    `index.html:3634-3636`).
- **Bind it to the turn.** In `ask()` (`:9175`), when the turn's `said`
  equals a key in `SENDS`, that record is popped. It becomes this turn's
  `ST.send_watch`, set next to `ST.stage_run` (`:9363`) and cleared with it
  when the turn ends. Nothing else ever reads `SENDS`. `run_bridge`'s
  retries (`:9368`) share the one `ST.send_watch`.
- **Arm it on the click.** In `run_bridge`'s `approve` worker, only a
  permission that matches all three of these is looked at:
  - `confirm == "click"`;
  - its `command` equals `ST.send_watch["command"]` byte for byte;
  - it carries a `toolCallId`.
  
  If the chosen option's kind starts with `allow`, the watch takes that id
  and becomes armed. A declined matching permission ends the watch. Other
  permissions never touch it, so an unrelated tool that is denied can't
  clear an approved send. The watch arms once: a second identical command in
  the same turn, under a new id, can't arm it again.
- **Fire on success.** On a `tool` event whose `toolCallId` equals the armed
  id:
  - `completed`: the watch ends, and one daemon thread
    `show_agent(session, pane, turn)` starts.
  - `failed`: the watch ends, and nothing happens.
  
  Other events change nothing.
- **Same id on both sides.** The adapter uses one id for both events. The
  Claude adapter builds the permission request's tool call from the same
  `toolUseID` as its `tool_call` updates
  (claude-agent-acp 0.100.0 `permissions/presentation.js:39`,
  `tool-calls/renderer.js:115`). It marks a tool `failed` exactly when its
  result is an error (`renderer.js:81`), which a non-zero Bash exit is.
- **Turn identity.** `turn` is a module counter that `ask()` increments when
  a turn starts. `alive()` means `not ST.stopped and TURN == turn`.
- **`show_agent`.** Its own sequence, so that it can check `alive()` before
  every step. It doesn't call `_attention_focus`, whose three commands run
  without a check in between.
  1. `alive()`? List that session's agents again. If the pane is gone, stop.
  2. `alive()`? Run `herdr --session <s> agent focus <pane>`. This switches
     herdr's tab.
  3. `alive()`? Find the window. It looks at Hyprland clients with class
     `org.omarchy.herdr`, and reads each one's child processes from `/proc`.
     A window matches only when a child's argv is exactly
     `["herdr", "--session", s]`. A bare `herdr` never matches, because
     `HERDR_SESSION` in its environment can name any session (Codex checked
     this live). Exactly one match gives a pid. Zero or several give none.
  4. `alive()`, with a pid? Run `hyprctl dispatch focuswindow pid:<pid>`.
  
  Every error is caught and ignored. Nothing is spoken and nothing types.
  Every argv is built from `SESSION_RE`/`PANE_RE`-checked values.
- **Spoken and typed both count.** Both reach `session_send` through
  `/api/quick` from the page's one submit path (`app/static/index.html:3634`),
  as decided at intent approval.

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
- **Window shapes the matcher doesn't know**, such as a bare `herdr`,
  `herdr session attach <s>` or a herdr desktop app. Those windows don't
  match, so only herdr's tab switches. That is safe, and a shape can be added
  when one shows up.
- **The adapter's ids could change in a later version** (verified in
  claude-agent-acp 0.100.0). If they stop matching, the effect is that
  focus never happens. Nothing is ever sent wrongly.
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
    - None of these focus: declined, `failed`, no id, a different command,
      a different id, a stopped turn, a newer turn, or the pane gone.
    - A second identical command with a new id doesn't focus again.
    - Two `/api/quick` sends in a row keep two records.
    - Turn end clears `ST.send_watch`.
    - An unrelated permission that is denied, landing between the click and
      the `completed`, doesn't stop the focus.
    - A stop between herdr's focus and the raise means no raise.
  - The window matcher with fake `/proc` trees:
    - one `herdr --session s` match gives its pid;
    - two matches, a bare `herdr`, or a `session attach` window give no pid.
  - `session_show` attaches with the agent's session. Duplicate pane ids in
    two sessions stay apart everywhere.
- **Bridge test** (nixi-nixarchy `bridge/herdr-bridge.test.js`): `tool` and
  `permission` events carry the adapter's `toolCallId` unchanged. A herdr
  send's permission and its `completed` update carry the same id.
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
