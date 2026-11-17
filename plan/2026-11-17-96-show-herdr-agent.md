---
status: draft
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
     the session checked. Update `session_show` (`:6425`) to pass it.
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
     - `tests/test_no_herdr_writes.py` guards that the companion never runs
       a herdr write itself. `focus` isn't a write, but check that test's
       rule and extend it to allow exactly `agent focus` if it needs that.
     - Tests must not import server.py under the real HOME (#176): use
       `_ServerEnv` and `nixi_env`.

2. **`app/server.py`: the turn-bound watch and `show_agent` (spec part 3).**
   By Codex.
   - Module state:
     - `SENDS = {}`: at most 8 entries, 15-minute expiry, guarded by a
       lock.
     - `TURN = 0`.
     - In `State.__init__` (`:383-400`): `self.send_watch = None`.
   - `session_send`: after building the ask prompt, store
     `SENDS[prompt] = {"command", "session", "pane", "at": time.monotonic()}`.
     Drop expired entries and the oldest beyond 8.
   - `ask()` (`:9175`), where the turn starts (`:9363-9365`, next to
     `ST.stage_run, ST.stage_run_tok = run_cmd, tok`):
     - `TURN += 1`, and keep `turn = TURN` for this request.
     - `ST.send_watch = SENDS.pop(said, None)` under the lock, adding
       `"turn": turn`, `"id": None` and `"armed": False`.
     - Where `ST.stage_run = ST.stage_run_tok = None` (`:9395`), also clear
       `ST.send_watch = None`.
   - `run_bridge` (`:6464`):
     - The `tool` branch (`:6525`) reads `o.get("toolCallId")`.
     - The `approve` worker (`:6470`), after the `stage_run` check:
       - It looks at a permission only when it sees all of these:
         - `w = ST.send_watch` is set and not armed;
         - `o.get("confirm") == "click"`;
         - `o.get("command") == w["command"]`;
         - `o.get("toolCallId")` is a non-empty string.
       - After `pick` comes back:
         - its option kind starts with `allow`: set `w["id"]` and
           `w["armed"] = True`;
         - otherwise: `ST.send_watch = None`.
       
       Look up the picked option's kind in `opts` by id.
     - In the `tool` branch, when `w` is armed and
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
       change under it. Read it into a local `w` once, and only clear it if
       `ST.send_watch is w`.
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
   - `:575-578`, the `permission` emit: add
     `toolCallId: params.toolCall?.toolCallId`. Add it only when it is a
     non-empty string, as the `command` field is.
   - `bridge/herdr-bridge.test.js`: one test that a herdr send's card and
     its tool updates carry the same `toolCallId` as the fake agent's.
     Check `bridge/testing/` for the fake agent's ids, and extend it
     minimally if it sends none.
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
   - Builds:
     - Run the full suite, the fit tests and `nix flake check` here.
     - Run `node --test` there.
     - `nix build` of the companion, and of nixi with the bridge change,
       where nixi-nixarchy's flake allows it.
   - Live on p620:
     - Post on the agent bus first. Start a test build with `systemd-run`
       and `RemainAfterExit`, using the live Hypr signature from
       `/run/user/1000/hypr`.
     - Run the spec's live checks. If the installed nixi is the old bridge,
       the focus check waits until the new nixi is deployed; say so in the
       PR.
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
- Live: the spec's checks:
  - status found;
  - send, then tab and window;
  - decline, then nothing;
  - pane gone, then nothing;
  - stop before click, then nothing.

## Rollback

Revert the PR in each repo; they are independent. Reverting only the bridge
leaves cross-session sends working, with no focus. Reverting only the
companion ignores the new bridge fields. Then bump the nixos_config inputs
back and redeploy.
