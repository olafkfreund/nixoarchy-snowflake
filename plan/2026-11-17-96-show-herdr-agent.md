---
status: approved
issue: 96
spec: spec/2026-11-17-96-show-herdr-agent.md
coders:
  1: coder    # session plumbing through existing helpers: careful but mechanical
  2: codex    # small, tricky logic: turn-bound one-shot watch, races, /proc window match
  3: coder    # tests across one new file and four existing ones
  4: coder    # two fields and one test in the bridge (nixi-nixarchy)
  5: coder    # one docs paragraph
reviewers:
  - codex     # read-only review of the whole diff in both repos, against this plan
---

# Plan: show the herdr agent when Nixi prompts it

This plan has everything needed to build it; the intent and spec don't need
opening.

## Decisions (from the approved intent and spec)

- **Find agents in every running herdr session.** Nixi's process has no
  `HERDR_*` variables, so today it only sees herdr's default session, which
  is empty on p620. The agents live in `Devlopment-Local` (17) and
  `Synechron-development` (2). Every lookup, read, send, attach and focus
  carries the agent's session.
- **Session names are checked** with `SESSION_RE =
  re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")`. There is no leading dash:
  a session literally named `--help` exists. Panes keep `PANE_RE`
  (`app/server.py:6325`).
- **The bridge (nixi-nixarchy) adds `toolCallId`** to its `tool` and
  `permission` events, and nothing else changes.
  - The Claude adapter uses the same id for both. A non-zero Bash exit is
    reported as `failed` (claude-agent-acp 0.100.0
    `permissions/presentation.js:39`, `tool-calls/renderer.js:81,115`).
  - With an old bridge there is no id, so Nixi never focuses. It fails
    closed.
- **Focus happens only after a confirmed send**, and the watch is tied to
  its turn and used once:
  1. `session_send` stores `SENDS[ask_prompt]`.
  2. `ask()` pops it into `ST.send_watch` when `said` equals the key.
  3. The click arms it: the `confirm == "click"` permission whose `command`
     matches byte for byte, answered `allow*`, with a `toolCallId`.
  4. That id's `completed` starts `show_agent`. Its `failed`, or a decline of
     that permission, ends the watch.
  5. Other permissions never touch it. The turn's end clears it.
- **`show_agent` uses its own steps** and checks
  `alive() = not ST.stopped and TURN == turn` before each one:
  1. Look up the agent again.
  2. `herdr --session s agent focus pane`.
  3. Match the window.
  4. `hyprctl dispatch focuswindow pid:N`.
  
  Errors are ignored. It never speaks or types.
- **The window matcher** looks at Hyprland clients with class
  `org.omarchy.herdr`. A window counts only if one of its child processes
  has argv exactly `["herdr", "--session", s]`. A bare `herdr` never counts:
  `HERDR_SESSION` can redirect it. Exactly one match gives a pid. None or
  several give no raise, but herdr's tab still switches.
- **Raising the window is always on**, with no setting. Typed and spoken
  sends both get it (decided at intent approval).

## Steps

Steps 1 and 2 both edit `session_send`, so they run in order. Step 2
starts only after step 1 is in the worktree.

1. **`app/server.py`: agents from every session (spec part 1).** By the
   coder.
   - At `:6325`, next to `PANE_RE`, add `SESSION_RE`.
   - `_herdr` (`:6336`): replace the two-shape allowlist with exactly these
     shapes, where `s` matches `SESSION_RE` and `pane` matches `PANE_RE`:
     - `["herdr","session","list","--json"]`
     - `["herdr","--session",s,"agent","list"]`
     - `["herdr","--session",s,"agent","read",pane,…]`
     - `["herdr","--session",s,"agent","focus",pane]`
     
     Keep the 3 s timeout.
   - New `herdr_sessions()`: the names whose `running` is true and that
     match `SESSION_RE`. `[]` on any failure.
   - `herdr_agents()` (`:6347`): loop over `herdr_sessions()`, list each
     one, and give each agent dict `"session": s`. A session that fails is
     skipped.
   - `herdr_read(pane, session)` (`:6370`) and `session_status`: pass the
     agent's session.
   - `attach_argv(pane, session)` (`:6416`):
     `[…, "herdr", "--session", session, "agent", "attach", pane]`, with
     the session checked. Update both callers:
     - `session_show` (`:6425`);
     - the desk's "open session" action in `stage_act` (`:7869`,
       `attach_argv(got[1]["pane"])`).
     
     The desk's status rows (`:6597`) must carry `"session": a["session"]`
     next to `"pane"`, so the stored action has it. Check `app/stages.py`
     `status_stage` for where the token's payload is built, and pass
     `session` through unchanged.
   - `session_send` (`:6441`): validate the session, and make the command
     `herdr --session {session} agent prompt {pane} {shlex.quote(text)}`.
     Keep the wording otherwise.
   - Verify with:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py tests/test_sessions.py tests/test_no_herdr_writes.py tests/test_desk_stages.py tests/test_whisper_switch.py
     ```
     Fix the expectations that change (the `--session` argv and the
     allowlist).
   - Traps:
     - `_collect_names` (#95) calls `herdr_agents()` and needs no change.
     - `tests/test_no_herdr_writes.py` exempts only the last `return` in
       `session_send` that contains an f-string (`_prompt_span`, `:25-31`).
       Keep the prompt, with the `agent prompt` command, built inside that
       one `return` statement. Step 2 records it by wrapping that same
       return, not by moving the f-string out. If the shape has to change,
       narrow `_prompt_span` to the new single statement and keep every
       negative check. `focus` is in neither `WRITE` nor `VERBS` (`:10-11`),
       so it needs no exemption.
     - Tests must not import server.py under the real HOME (#176): use
       `_ServerEnv` and `nixi_env`.

2. **`app/server.py`: the turn-bound watch and `show_agent` (spec part 3).**
   By Codex.
   - Module state:
     - `SENDS = {}`: at most 8 entries, 15-minute expiry, guarded by a
       lock.
     - `TURN = 0`.
     - In `State.__init__` (`:383-400`): `self.send_watch = None`.
   - `session_send`: record the ask prompt without moving the f-string out
     of its `return` (see step 1's trap). For example:
     `return (None, _record_send(<the f-string>, command, session, pane))`,
     where `_record_send` stores
     `SENDS[prompt] = {"command", "session", "pane", "at": time.monotonic()}`
     and returns `prompt`. It drops expired entries and the oldest beyond 8.
   - `ask()` (`:9175`), where the turn starts (`:9363-9365`, next to
     `ST.stage_run, ST.stage_run_tok = run_cmd, tok`):
     - Order matters: under one `WATCH_LOCK`, first `TURN += 1`, keeping
       `turn = TURN`, and only then run the existing
       `ST.stopped = False` (`:9363`). An old focus thread must never see its
       own turn number with `stopped` cleared.
     - Under the same lock, `rec = SENDS.pop(said, None)`. It is used only
       if `time.monotonic() - rec["at"] <= 900`, because expiry is checked
       when the record is used too, not only on insert. Then
       `ST.send_watch = {**rec, "turn": turn, "id": None, "armed": False}`,
       or `None`.
     - Where `ST.stage_run = ST.stage_run_tok = None` (`:9395`), also clear
       `ST.send_watch = None`.
   - `run_bridge` (`:6464`):
     - The `tool` branch (`:6525`) reads `o.get("toolCallId")`.
     - `run_bridge` captures `my_turn = TURN` when it starts. Its `approve`
       worker (`:6470`) captures `w = ST.send_watch` when the permission
       event arrives. It does that in the reader loop before starting the
       thread (`:6528`), and passes `w` in, so a worker that starts late
       can't grab a newer turn's watch.
     - The worker looks at a permission only when it sees all of these:
       - `w` is set, and `w["turn"] == my_turn`;
       - `o.get("confirm") == "click"`;
       - `o.get("command") == w["command"]`;
       - `o.get("toolCallId")` is a non-empty string.
     - After `pick` comes back, and before
       `BRIDGE.send({"type":"permission",…})`, one atomic step runs under
       `WATCH_LOCK`. It proceeds only when all of these hold:
       - `ST.send_watch is w`;
       - `not w["armed"]`;
       - `TURN == my_turn`;
       - `not ST.stopped`;
       - `BRIDGE.proc is p`.
       
       If they do, it looks up the picked option's kind in `opts` by id:
       - a kind starting with `allow`: set `w["id"]` and
         `w["armed"] = True`;
       - anything else: `ST.send_watch = None`.
       
       A second worker for the same command finds the watch armed, or gone,
       and changes nothing.
     - In the `tool` branch, under `WATCH_LOCK`, when
       `w = ST.send_watch` is armed, `w["turn"] == my_turn`, and
       `o.get("toolCallId") == w["id"]`:
       - `completed`: `ST.send_watch = None`, then start one daemon
         `threading.Thread(target=show_agent, args=(w["session"], w["pane"], w["turn"]))`;
       - `failed`: `ST.send_watch = None`.
   - New `show_agent(session, pane, turn)`:
     - `alive = lambda: not ST.stopped and TURN == turn`.
     - Steps, with an `alive()` check before each one that runs a command:
       1. `alive()`. Re-list with `herdr --session s agent list`. Return if
          the pane is absent.
       2. `alive()`. `_run(["herdr","--session",s,"agent","focus",pane], timeout=3)`.
       3. `alive()`. `pid = herdr_window_pid(session)`.
       4. If `alive()` and `pid`:
          `_run(["hyprctl","dispatch","focuswindow",f"pid:{pid}"], timeout=3)`.
     - Wrap it all in `try/except Exception: pass`.
     - Check `session` with `SESSION_RE` and `pane` with `PANE_RE` before
       anything runs.
   - New `herdr_window_pid(session)`:
     - `hyprctl clients -j`, keeping clients with
       `class == "org.omarchy.herdr"` and an int `pid`.
     - For each window, find its children: scan `/proc/*/stat` for that
       ppid, and read `/proc/<child>/cmdline` split on `\0`.
     - A window matches when a child's argv is exactly
       `["herdr","--session",session]`. The argv may start with a full path
       ending in `/herdr`; compare `os.path.basename(argv[0]) == "herdr"`.
     - Return the pid only when exactly one window matches; else `None`.
     - `/proc` reads are wrapped. Take the `/proc` root as a parameter
       defaulting to `"/proc"`, so tests can pass a fake tree.
   - Verify with:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py tests/test_sessions.py tests/test_whisper_switch.py
     ```
     Then run the new test file from step 3 once it exists.
   - Traps:
     - The `approve` worker runs on its own thread, and `ST.send_watch` can
       change under it. Every read-and-change happens under `WATCH_LOCK`,
       with `ST.send_watch is w` and the turn checked again.
     - Never focus on a `result`/`done` event: only on the armed id's
       `completed`.
     - `run_bridge` can be retried up to 3 times per turn (`:9368`). The
       watch is per turn, and arming happens once.

3. **Tests.** By the coder.
   - New `tests/test_show_agent.py`, using `_ServerEnv` and `nixi_env`.
     herdr, hyprctl and `/proc` are faked by patching `_run`/`_herdr`/
     `subprocess.run` and passing a temp `/proc` tree. Nothing real runs.
   - Sessions:
     - running vs stopped;
     - `--help` is never used;
     - one failing session doesn't hide the others;
     - each agent carries its `session`;
     - duplicate pane ids in two sessions stay apart in send, read and
       attach.
   - The allowlist refuses other shapes, including an unchecked session.
   - `session_send` gives the `--session` command and records `SENDS`.
     Two quick sends in a row give two records. Records expire and are
     capped at 8.
   - The watch:
     - Confirmed, then `completed`, gives exactly one `show_agent`.
     - None of these give one: declined, `failed`, a missing `toolCallId`,
       a different command, a different id, a stopped turn, or a newer
       turn.
     - A second identical command with a new id after arming doesn't give
       a second one.
     - An unrelated denied permission between the click and `completed`
       still focuses.
     - The turn's end clears `ST.send_watch`.
     - Two workers for the same command, one allowed and one declined, in
       either order: one arms it, and the other changes nothing. Drive this
       deterministically with Events.
     - A worker from an old turn, answered after a new turn installed an
       identical-command watch: the new watch is untouched.
     - A record older than 15 minutes, used without any send in between,
       gives no watch.
     - An old `show_agent` paused exactly at the turn boundary (counter
       bumped, `stopped` reset) doesn't focus.
   - The desk's "open session" action attaches with the row's session.
     Duplicate pane ids in two sessions open the right one.
   - `show_agent`:
     - The pane gone: no focus.
     - `ST.stopped` set after the herdr focus: no `hyprctl dispatch`.
     - Exceptions are swallowed.
   - `herdr_window_pid` on fake trees:
     - one match gives its pid;
     - two matches give `None`;
     - a bare `herdr`, `herdr session attach s` or another class gives
       `None`;
     - a full-path argv[0] matches.
   - Use Events or Barriers with bounded joins for the threads, and no
     sleeps over 0.2 s (#95's pattern in `tests/test_whisper_switch.py`).
   - Verify with:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py tests/test_show_agent.py
     ```
     It must pass with 0 skips. Then run the full suite.
   - Traps: CI fails on skips that aren't on the allow-list. Never run the
     real `herdr`, because the owner's agents are live.

4. **nixi-nixarchy `bridge/bridge.js`: `toolCallId` on two events.** By the
   coder, in `/mnt/code/Source-home/GitHub/nixi-nixarchy` on a new branch
   `feat/96-tool-call-ids` off `origin/main`.
   - `:486-490`, the `tool` emit: add `toolCallId: update.toolCallId`.
   - `:578`, the `permission` emit (its `command` field is at `:582`): add
     `toolCallId: params.toolCall?.toolCallId`. Add it only when it is a
     non-empty string, as the `command` field is.
   - `bridge/herdr-bridge.test.js`: one test that a herdr send's card and
     its tool updates carry the same `toolCallId` as the fake agent's.
     The fake agent already gives the herdr tool call id `"t5"`
     (`bridge/testing/fake-agent.js:146`), but sends no tool updates after
     the permission. Extend it minimally so an allowed herdr send emits a
     `tool_call_update` with `toolCallId: "t5"` and `status: "completed"`.
   - Verify with:
     ```bash
     cd bridge && node --test
     ```
     Everything must pass.
   - Traps:
     - That repo has its own `intent/spec/plan` folders. This change is
       tracked by this plan; its PR links here.
     - The ids are opaque strings. Never log them in `sends.log`.

5. **`docs/GUIDE.md:182`: one short paragraph.** By the coder.
   - Voice and typed sends now reach agents in every running herdr session.
   - After you click allow and the send succeeds, herdr switches to that
     agent's tab.
   - Its window comes to the front when exactly one herdr window shows that
     session.
   - Verify with:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py tests/test_docs*.py
     ```
     Run it if such tests exist; otherwise skip this check.
   - Traps: none.

6. **Lead: review, build, live test, PRs.**
   - A fresh Opus review gets only this plan and both diffs. Codex reviews
     with `review --base main` in each repo.
   - Builds and tests:
     - Here:
       ```bash
       nix develop .#ci -c python3 -B .github/ci/run_tests.py --exclude test_character_fit.py --exclude test_accessories_fit.py
       nix develop .#ci -c python3 -B .github/ci/run_tests.py --deadline 1800 test_character_fit.py test_accessories_fit.py
       nix flake check
       nix build
       ```
       The last one builds the companion package.
     - In nixi-nixarchy:
       ```bash
       cd bridge && node --test
       ```
       Also run `nix build` at its root, which builds the nixi package with
       the bridge.
   - Live on p620:
     - Post on the agent bus first. Start a test build with `systemd-run`
       and `RemainAfterExit`, using the live Hypr signature from
       `/run/user/1000/hypr`.
     - Live checks:
       - By voice, "what is factory-gitops doing": Nixi finds the agent in
         `Devlopment-Local` and answers about it, instead of "no herdr".
       - By voice, send a prompt to an agent in `Devlopment-Local` and
         click allow. herdr's tab switches to that agent, and its kitty
         window (class `org.omarchy.herdr`, child
         `herdr --session Devlopment-Local`) comes to the front.
       - Decline a send card: nothing moves.
       - Send to an agent whose pane has just closed: nothing moves.
       - Stop the turn before clicking: nothing moves.
       - "Show me factory-gitops" opens that agent's pane in
         `Devlopment-Local`.
     - The focus checks need the bridge with ids. If the installed nixi has
       the old bridge, run them once the new nixi is deployed too, and say so
       in the PR.
   - PRs in both repos, each commented "@codex review". Deploy is the
     usual nixos_config input bump, and only on the owner's OK.

## Tests

- This repo:
  ```bash
  nix develop .#ci -c python3 -B .github/ci/run_tests.py
  ```
  The whole suite must pass, with only the allowed skips. Also run the fit
  tests and `nix flake check`.
- nixi-nixarchy:
  ```bash
  cd bridge && node --test
  ```
  It must all pass.
- Live: the six checks in step 6.

## Rollback

Revert the PR in each repo; they are independent. Reverting only the bridge
leaves cross-session sends working, with no focus. Reverting only the
companion ignores the new bridge fields. Then bump the nixos_config inputs
back and redeploy.
