---
status: draft
issue: 107
spec: spec/2026-11-19-107-otp-pause-asleep.md
coders:
  1: codex   # small tricky logic: the fallback rule inside CodePause's lock and the toast gate
  2: codex   # tricky: Gio monitor, filter threading traps, owner checks, lifecycle
  3: coder   # unit tests for steps 1-2: plentiful, follows test_code_pause.py patterns
  4: coder   # dev-shell change plus a private-bus integration test
  5: coder   # one docs paragraph
reviewers:
  - codex    # branch review against origin/main before the PR; agy is out of use (#2748)
---

# Plan: pause clipboard sharing for codes while Nixi is hidden

## Approved decisions (from the intent and spec)

- **The watch:** a `NotifyWatch` monitor on the session bus feeds `CodePause` whenever Phone is on, whether Nixi is shown or hidden. It uses `BecomeMonitor` on a private Gio connection, with no root and no policy change.
- **#105's rules are unchanged:**
  - 120 s;
  - at most 5 requests per hold;
  - never ended early;
  - the same `Inbox.OTP.match` / `SECRET_LINE.search` on visible text (`Inbox.STRIP`, then `Inbox.ENT`) plus action labels.
- **The rules the watch asks the bus for:**
  - the `Notify` call, matched by `destination` (the well-known name, and the owner `O`) plus `path`, `interface` and `member`;
  - `method_return` from `O` only;
  - `NameOwnerChanged` for `org.freedesktop.Notifications`.
- **The key is `f"{bus_id}:{O}:{id}"`,** with `id` taken from the `Notify` reply.
  - The filter keeps only `pending[(sender, serial)] = time` for hits: at most 64 entries, each kept 10 s.
  - It never stores text.
- **The filter:**
  - It checks Phone first, before reading any body.
  - It checks the signature `susssasa{sv}i`.
  - It reads children 3, 4 and 5 only; the hints are never unpacked.
  - Bounds come before any normalising: summary and body 16 KiB each, at most 64 action entries, each label 1 KiB.
  - It returns outgoing messages, and messages addressed to its own unique name, unchanged. It consumes the monitored ones.
- **The lifecycle:**
  - One daemon thread polls every 2 s.
  - It closes the watch when Phone is off.
  - It reconnects on `is_closed()`, on `stale` (owner changed), or when an owner check fails.
  - It checks the owner again after `BecomeMonitor`, and Phone and the owner again after `connect` returns.
  - On failure it logs one content-free line per process and backs off `min(300, 2·2^n)` s.
- **Decision 2, as amended:** `Inbox.rows` calls `CodePause.seen(key, fallback=True)`.
  - The key is always recorded.
  - `pending` rises only if the watch counted nothing in the last 10 s.
- **Decision 3:** the toast is published only when `not Wake.asleep`.

## Steps

1. **`app/server.py`, `CodePause` (`:3184`–`:3290`) and `Inbox.rows` (`:3434`)**
   - **Changes:**
     - Add `last_watch = -1e9` and `WATCH_GRACE = 10`.
     - `seen(cls, key, fallback=False)`:
       - The dedupe works as today: forget after 600 s, keep at most 64, return if the key is known.
       - It always records the key.
       - When `fallback` is false, it sets `last_watch = monotonic now`, increments `pending` and sets `wake`.
       - When `fallback` is true, it increments `pending` and sets `wake` only if `now - last_watch >= WATCH_GRACE`.
       - Everything happens under `lock`.
     - In `turn()`, publish the toast only if `not Wake.asleep`. `Wake` is defined later in the module, so read it at call time.
     - In `Inbox.rows`, the call becomes `CodePause.seen(x["key"], fallback=True)`.
   - **Verify:** `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_code_pause.py test_inbox.py` passes unchanged.
   - **Traps:**
     - `seen` must not do I/O, because it runs on the `Inbox` thread and, after step 2, on GDBus's worker.
     - Don't touch the display gate.

2. **`app/server.py`, the new `class NotifyWatch` right after `CodePause`, and `Inbox.start()` (`:3553`)**
   - **Class state:** `lock`, `thread`, `mon`, `plain`, `owner`, `bus_id`, `pending = {}`, `stale = False`, `fails = 0`, `retry_at = 0.0`, `logged = False`.
   - **`connect()`:**
     - Import `gi` lazily: `gi.require_version("Gio", "2.0")`, then `from gi.repository import Gio, GLib`. An `ImportError` is a failure. `server.py` doesn't import `gi` today, and the test shell may lack it.
     - Get the address with `Gio.dbus_address_get_for_bus_sync(SESSION)`.
     - Build `plain` with `new_for_address_sync(addr, AUTHENTICATION_CLIENT | MESSAGE_BUS_CONNECTION)`. Never use `bus_get_sync`.
     - `GetId` gives `bus_id`; `GetNameOwner` gives `O`.
     - Build `mon` the same way. Then `add_filter(cls.filter)`, then `BecomeMonitor(rules, 0)` with the four rules from the decisions above.
     - Call `GetNameOwner` again on `plain`. If it isn't `O`, close both connections and fail.
     - Set `owner`, `pending = {}` and `stale = False` under `lock`.
   - **`filter(conn, msg, incoming)`:**
     - Order: not `incoming` returns `msg`; `msg.get_destination() == conn.get_unique_name()` and not a pending reply returns `msg`; Phone not `True` returns `None`. Then dispatch on the type.
     - **A `Notify` call:** check the signature; take the bounded fields via `get_child_value`; normalise; join; match. On a hit, set `pending[(sender, serial)]` with the 64-entry and 10 s bounds.
     - **A return:** pop the pending entry, read `get_body().get_child_value(0).get_uint32()`, and call `CodePause.seen(f"{bus_id}:{owner}:{id}")` outside `NotifyWatch.lock`.
     - **`NameOwnerChanged`:** set `stale = True`.
     - Wrap everything in `try`/`except Exception` that calls `_log(type(e))` and returns `None`.
   - **`_log(what)`:** prints `[nixi] notification watch: <what>` once per process. For a `GLib.Error`, `what` is its domain and code.
   - **`close()`:** closes `mon` and `plain` (`close_sync`), ignoring errors, and clears the references.
   - **`tick()`:**
     - If Phone is not `True`, `close()` if open.
     - Otherwise:
       - if open and (`mon.is_closed()`, `stale`, or the owner check on `plain` fails), `close()`;
       - if not open and `monotonic() >= retry_at`, try `connect()`.
         - On success, re-check Phone and the owner. If either fails, `close()`. Otherwise `fails = 0`.
         - On failure, `_log`, `fails += 1`, and `retry_at = now + min(300, 2 * 2**fails)`.
   - **`loop()`:** `while True: tick(); time.sleep(2)`, with `tick` exceptions logged.
   - **`start()`:** starts one daemon thread, under `lock`. `Inbox.start()` calls `NotifyWatch.start()` after `CodePause.start()`.
   - **Verify:**
     - `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_code_pause.py test_inbox.py` still passes.
     - The scratch probe `/tmp/claude-1000/-mnt-code-Source-home-GitHub-nixoarchy-snowflake/ad40f9f2-1c79-4b6c-a4db-157a6d378049/scratchpad/probe/monprobe.py` shows the working Gio call pattern. Read it; don't copy its prints.
   - **Traps:**
     - Filters see outgoing messages. A filter that drops them makes `BecomeMonitor` time out (GIO error 24), which the probe hit twice.
     - The `closed` signal needs a running main context, which Nixi doesn't have, so don't rely on it.
     - Never log, publish or store any message argument.
     - Tests must never connect to the real session bus: under test, `connect` is patched, or the bus test sets its own `DBUS_SESSION_BUS_ADDRESS`.

3. **Tests for steps 1 and 2:** a new `tests/test_notify_watch.py`, plus additions to `tests/test_code_pause.py` and `tests/test_inbox.py`
   - Use `_ServerEnv` from `test_speakable` as `test_code_pause.py` does. Build fake messages with `mock.Mock`, with `get_message_type`, `get_signature`, `get_child_value` and so on.
   - Patch `gi`-dependent names via the class's own references. Unit tests must not need `gi`: give the filter fakes whose child values return Python objects through `get_string`, `get_strv`, `get_uint32`, `n_children` and `get_child_value`.
   - **Cases:** every unit case in the spec's Verification section:
     - identity;
     - detection;
     - bounds, including a fake whose child 6 raises;
     - messages passed through;
     - the Phone gate (`get_body` and `get_child_value` never called);
     - privacy (one log line, no text, `seen` argument checks);
     - lifecycle (Phone off/on, refusal plus back-off, Phone off during `connect`, `is_closed`, `stale`, owner change);
     - the fallback (watch 1 s ago, 11 s ago, none, update);
     - the display gate unchanged;
     - the toast while asleep and while shown.
   - **Verify:** `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_notify_watch.py test_code_pause.py test_inbox.py`. Every new test must fail when its step 1 or 2 line is reverted. Mutation-check at least the Phone gate, the outgoing pass-through, the fallback grace and the toast gate.
   - **Traps:**
     - Reset `NotifyWatch` and `CodePause` class state in `setUp`.
     - Never import `server` outside `_ServerEnv`: it would write the real HOME's config (#176).

4. **`flake.nix` dev shells (`:52`–`:75`) and a new `tests/test_notify_watch_bus.py`**
   - **The shells:** in `base`, replace `pkgs.python3` with `(pkgs.python3.withPackages (p: [ p.pygobject3 ]))`, and add `pkgs.dbus`.
   - **The test:**
     - It starts its own `dbus-daemon --session --nofork --print-address=1` in a temp dir and kills it in `tearDown`.
     - It points `NotifyWatch` at that daemon through `DBUS_SESSION_BUS_ADDRESS`, patched only inside the test.
     - A fake notification server (Gio, owning `org.freedesktop.Notifications`, returning increasing ids) runs on its own connection.
     - **Cases, from the spec:**
       - real `BecomeMonitor`;
       - a code counts once;
       - an update doesn't count again;
       - a `Notify` sent to another name isn't read;
       - an owner change still counts under the new owner;
       - closing `mon` from outside is detected within one `tick` and reconnected;
       - oversized real variants stay within the time bound.
     - Skip with a reason if `dbus-daemon` or `gi` is missing.
   - **Verify:**
     - `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_notify_watch_bus.py` runs; it is not skipped.
     - `nix flake check --no-build` evaluates.
   - **Traps:**
     - Never touch the host's session bus.
     - The fake server needs a GLib main loop on its own thread to answer calls. `NotifyWatch` itself needs none.

5. **`docs/GUIDE.md`, the "Codes and the clipboard" paragraph (#105)**
   - Rewrite it to say:
     - the pause works while Nixi is hidden, on every desktop notification, whenever Phone is on;
     - it is silent while hidden;
     - the shell's **Copy code** button is never shared anyway, because Flux skips sensitive copies;
     - **the cost:** more false positives, each a 2-minute pause;
     - #105's limits still apply: a copy made earlier, a send already past Flux's check, and a `fluxd` restart.
   - **Verify:** `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_docs.py`, if present; otherwise the full suite.
   - **Traps:** match the guide's short-sentence style.

6. **Lead only:** checks, reviews, PR and rollout
   - **Checks:** the full suite, then the fit tests (commands under Tests).
   - **Opus review:** a fresh Opus agent, given only this plan's path and `git diff origin/main`.
   - **Codex branch review:** `codex review --base origin/main`, with `git status --porcelain` checked before and after.
   - **PR:** it links the intent, spec and plan, says which steps codex or the coder did, and gets an "@codex review" comment.
   - **After merge:**
     - a nixos_config PR bumping `nixi-companion`, from a clean worktree with `nixarchy-theme.nix` copied in;
     - CI;
     - an agent-bus announcement;
     - `nh os switch` on p620 and `just deploy-via-p620 razer`;
     - Nixi restarted on both with the live Hypr signature;
     - the spec's runtime checks 1–4 on both hosts, with Nixi hidden.

## Tests

```bash
nix develop .#ci -c python3 -B .github/ci/run_tests.py --exclude test_character_fit.py --exclude test_accessories_fit.py
nix develop .#ci -c python3 -B .github/ci/run_tests.py --deadline 1800 test_character_fit.py test_accessories_fit.py
```

Both must pass. The bus test must run, not be skipped, in `.#ci`.

## Rollback

- **Code:** revert the PR's squash commit, then bump `nixi-companion` back in nixos_config and redeploy.
- **Without a deploy:** turning Phone off in Nixi stops the watch at once, because the filter checks Phone first.
- **Pauses already set:** they expire by themselves within 120 s.

## Deviations

None yet.
