---
status: approved
issue: 107
spec: spec/2026-11-19-107-otp-pause-asleep.md
coders:
  1: codex   # small tricky logic: the fallback rule inside CodePause's lock and the toast gate
  2: codex   # tricky: Gio monitor, filter threading traps, generation and owner checks, lifecycle
  3: coder   # unit tests for steps 1-2: plentiful, follows test_code_pause.py patterns
  4: coder   # dev-shell change plus a private-bus integration test
  5: coder   # one docs paragraph
reviewers:
  - codex    # branch review against origin/main before the PR; agy is out of use (#2748)
---

# Plan: pause clipboard sharing for codes while Nixi is hidden

## Approved decisions (from the intent and spec)

- **The watch:** `NotifyWatch` monitors the session bus with `org.freedesktop.DBus.Monitoring.BecomeMonitor`, on private Gio connections, as the user. There is no root and no policy change.
  - It feeds `CodePause` whenever Phone is on, whether Nixi is shown or hidden, fullscreen or not, with takeover on or off.
  - It uses no `busctl` (not on Nixi's PATH) and no legacy eavesdropping.
- **#105's rules are unchanged:**
  - 120 s per pause;
  - at most 5 requests per hold;
  - never ended early;
  - the same check: `Inbox.OTP.match(text) or SECRET_LINE.search(text)`.
  - `text` joins summary, body and action labels with `\n`. The body is first turned into visible text exactly as `Inbox.rows` turns `rich` into text: `Inbox.STRIP.sub(lambda m: "\n" if Inbox.BR.match(m[0]) else "", body)`, then `Inbox.ENT.sub(lambda m: Inbox.ENTS[m[1]], …)`.
- **The four match rules,** where `O` is the unique name that owns `org.freedesktop.Notifications`:
  1. `type='method_call',destination='org.freedesktop.Notifications',path='/org/freedesktop/Notifications',interface='org.freedesktop.Notifications',member='Notify'`
  2. the same as 1, with `destination='<O>'`
  3. `type='method_return',sender='<O>'`
  4. `type='signal',sender='org.freedesktop.DBus',member='NameOwnerChanged',arg0='org.freedesktop.Notifications'`
- **Identity:** the key is `f"{bus_id}:{O}:{id}"`.
  - `bus_id` comes from `org.freedesktop.DBus.GetId`; `id` is the `u` in the `Notify` reply.
  - **What the probe showed on p620 and razer:** a new notification's call has `replaces_id` 0, and its reply carries the new id. An update carries that id and gets the same id back (p620 1970 → 1970, razer 5 → 5).
- **The filter:**
  - It checks Phone first, before reading any body.
  - It reads a call only if its destination is the well-known name or `O`, and its signature is `susssasa{sv}i`.
  - It reads children 3, 4 and 5 only, never 6 (the hints).
  - Bounds come before any normalising: summary and body each cut to their first 16 KiB; at most 64 action entries read, one at a time; each label cut to 1 KiB. (The shell hands `Inbox` at most 200, 200, 40 and 600 characters, so these bounds see more than #105.)
  - Hits are kept as `pending[(sender, serial)] = monotonic time`: at most 64 entries, each valid for 10 s. It never stores text.
- **The lifecycle:**
  - One daemon thread polls every 2 s.
  - It closes everything when Phone is off.
  - It reconnects on `mon.is_closed()`, on `stale` (`NameOwnerChanged`), or when the owner check fails.
  - It doesn't use the `closed` signal, which needs a GLib main context that Nixi doesn't run.
  - On failure it prints one content-free line per process and backs off `min(300, 2·2^n)` s.
- **Decision 2, as amended:** `Inbox.rows` calls `CodePause.seen(key, fallback=True)`.
  - The key is always recorded.
  - `pending` rises only if the watch counted nothing in the last 10 s.
- **Decision 3:** the toast is published only when `not Wake.asleep`.

## Steps

1. **`app/server.py`, `CodePause` (`:3182`–`:3290`) and the `Inbox.rows` call (`:3435`)**
   - **Changes:**
     - Add the class attributes `last_watch = -1e9` and `WATCH_GRACE = 10`.
     - `seen(cls, key, fallback=False)`, under `lock`:
       1. Do today's dedupe: forget keys after 600 s; return if the key is known; record it; evict the oldest above 64.
       2. If `fallback` is false: `last_watch = now`, `pending += 1`, and set `wake` after the lock.
       3. If `fallback` is true: only when `now - last_watch >= WATCH_GRACE`, `pending += 1` and set `wake`.
       - A duplicate returns at step 1, so it never refreshes `last_watch`.
     - In `turn()`, replace the `else: BUS.pub(...)` with "publish only if `not Wake.asleep`". `Wake` is defined at `:4697`, later in the module; read it at call time.
     - In `Inbox.rows`, `CodePause.seen(x["key"])` becomes `CodePause.seen(x["key"], fallback=True)`.
   - **Verify:** `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_code_pause.py test_inbox.py` passes.
   - **Traps:**
     - `seen` does no I/O. It runs on the `Inbox` thread and, after step 2, on GDBus's worker thread.
     - Don't touch the display gate.

2. **`app/server.py`, the new `class NotifyWatch` right after `CodePause`; `Inbox.start()` (`:3553`); and `tests/test_code_pause.py:187-192`**
   - **State,** all guarded by `lock` (a `threading.Lock`):
     - `gen = 0`, `mon = plain = None`, `owner = bus_id = ""`, `pending = {}`, `stale = False`;
     - `fails = 0`, `retry_at = 0.0`, `logged = False`, `thread = None`;
     - `Gio = GLib = None`, filled by `_load()`.
   - **`_load()`:**
     - It imports lazily: `import gi`, `gi.require_version("Gio", "2.0")`, then `from gi.repository import Gio, GLib`.
     - It stores them as `cls.Gio` and `cls.GLib`. `server.py` must still import without `gi`.
     - The filter compares message types through `cls.Gio.DBusMessageType`, so tests can install a stub namespace.
   - **`connect()`:**
     - It returns `True` or `False`. On every path that returns `False`, it closes every connection it created, including after a refused `BecomeMonitor`. Use `try`/`except Exception`, closing whatever was made.
     - **Order:**
       1. `_load()`.
       2. Get the address with `Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None)`.
       3. Build `plain` with `Gio.DBusConnection.new_for_address_sync(addr, AUTHENTICATION_CLIENT | MESSAGE_BUS_CONNECTION, None, None)`. Never use `Gio.bus_get_sync`.
       4. On `plain`, call `GetId()` for `bus_id` and `GetNameOwner("org.freedesktop.Notifications")` for `O`.
       5. **Under `lock`, before any monitoring starts:** `gen += 1`, `g = gen`, `owner = O`, `bus_id = …`, `pending = {}`, `stale = False`, `plain = plain`. Identity is ready before the first message can arrive.
       6. Build `mon` the same way, then `mon.add_filter(lambda c, m, i: cls.filter(c, m, i, g))`, then call `BecomeMonitor(rules, 0)` with the four rules.
       7. Call `GetNameOwner` again on `plain`. If it isn't `O`, fail.
       8. Under `lock`, store `mon`.
   - **`filter(conn, msg, incoming, g)`,** in this order:
     1. Not `incoming`: return `msg`. Filters see outgoing messages too; dropping them makes `BecomeMonitor` time out (GIO error 24), which the probe hit twice.
     2. `msg.get_destination() == conn.get_unique_name()`: return `msg`. This is the connection's own reply, such as the `BecomeMonitor` result.
     3. `g != cls.gen`: return `None`. The message came from a connection that was closed or replaced.
     4. `CFG.get("phone_on") is not True`: return `None` before reading anything else.
     5. **A `Notify` method call:**
        - Destination is not `org.freedesktop.Notifications` or `owner`, or the signature isn't `susssasa{sv}i`: return `None`.
        - Read `get_child_value(3).get_string()[:16384]` and the same for child 4.
        - Let `a = get_child_value(5)`. For `i in range(1, min(a.n_children(), 64), 2)`, read `a.get_child_value(i).get_string()[:1024]`. Never `unpack()` or `get_strv()` the array.
        - Normalise, join, match.
        - On a hit, under `lock`: drop entries older than 10 s; add `pending[(sender, serial)] = now`; drop the oldest above 64.
     6. **A method return:**
        - Under `lock`, pop `(destination, reply_serial)`.
        - If it exists and `now - t < 10`, read `get_body().get_child_value(0).get_uint32()` and build the key.
        - Call `CodePause.seen(key)` **outside** `NotifyWatch.lock`.
     7. **`NameOwnerChanged`:** `stale = True` under `lock`.
     - Everything after step 2 is wrapped in `try`/`except Exception as e: cls._log(e)`. The filter returns `None` for every monitored message.
   - **`_log(e)`:** prints `[nixi] notification watch: <domain>:<code>` for a `GLib.Error`, else `<TypeName>`. It prints once per process and never includes message content.
   - **`close()`:**
     - Under `lock`: `gen += 1`, take `mon` and `plain`, set them to `None`, `pending = {}`.
     - Then `close_sync(None)` each one, ignoring errors.
   - **`tick()`:**
     - **Phone off:** if open, `close()`, and return.
     - **Open:** if `mon.is_closed()`, or `stale`, or `plain`'s `GetNameOwner` isn't `owner`, call `close()`.
     - **Not open, and `monotonic() >= retry_at`:** call `connect()`.
       - On success, re-check Phone and the owner. If either fails, `close()`. Otherwise `fails = 0`.
       - On failure: `fails += 1`, and `retry_at = now + min(300, 2 * 2**fails)`.
   - **`loop()`:** `while True: try tick() except log; time.sleep(2)`.
   - **`start()`:** starts one daemon thread, under `lock`.
     - `Inbox.start()` calls `NotifyWatch.start()` after `CodePause.start()`.
     - Update `test_inbox_start_starts_code_worker_once` (`tests/test_code_pause.py:187`): patch `NotifyWatch.thread` to `None` too. Assert three `Thread` calls over two `Inbox.start()` calls (Inbox, CodePause and NotifyWatch, each once), and check the three `target=` values.
   - **Verify:** `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_code_pause.py test_inbox.py` passes.
   - **Traps:**
     - Never log, publish or store a message argument.
     - Tests must never reach the real session bus: unit tests patch `connect` and `_load`, and the bus test sets its own address.

3. **Unit tests:** a new `tests/test_notify_watch.py`, plus additions to `tests/test_code_pause.py` and `tests/test_inbox.py`
   - **Harness:**
     - Use `_ServerEnv` (`tests/test_speakable.py:14`) as `test_code_pause.py` does.
     - In `setUp`, block `gi` with `mock.patch.dict(sys.modules, {"gi": None, "gi.repository": None})`. Any accidental import then fails the test.
     - Install a stub `NotifyWatch.Gio` with a `DBusMessageType` namespace (`METHOD_CALL`, `METHOD_RETURN`, `SIGNAL`).
     - Reset the `NotifyWatch` and `CodePause` state.
     - **Fake messages:** `mock.Mock` objects with `get_message_type`, `get_member`, `get_destination`, `get_sender`, `get_serial`, `get_reply_serial`, `get_signature` and `get_child_value`.
     - **Fake variants:** objects with `get_string`, `n_children`, `get_child_value` and `get_uint32`. Their `unpack()` and `get_strv()` raise.
   - **Identity:**
     - A code call (`replaces_id` 0), then its reply with id 7, calls `CodePause.seen("B:O:7")` exactly once.
     - A later code update with the same id doesn't raise `pending` again.
     - A clean call, then a code update with id 7, counts once.
     - A reply with no matching call does nothing.
     - The same `O` and `7` under bus id `B2` count again.
     - A reply 11 s after its call, with no insert in between, doesn't count (patch `time.monotonic`).
   - **Detection:**
     - `"Your sign-in code"` with body `"<b>482</b>910"` is found.
     - Body `"<a href=\"https://x/" + "A1b2C3d4"*20 + "\">open</a>"` with summary "New mail" is not.
     - A code only in the label at index 1 is found.
     - A `SECRET_LINE` match alone is enough.
     - A code at character 300 of the body is found.
   - **Bounds:**
     - A 1 MB body finishes in under 0.2 s.
     - An action array fake with 10,000 entries raises on any `get_child_value(i)` with `i >= 64`, and on `unpack` and `get_strv`.
     - Child 6 raises on any access.
     - `pending` holds at most 64 entries, and an entry 11 s old is dropped on the next insert.
   - **Messages passed through:**
     - Outgoing messages (`incoming=False`) and messages to `conn.get_unique_name()` come back as the same object.
     - A monitored `Notify` returns `None`.
     - A call with the wrong signature, or to another destination, returns `None`, and `get_child_value` is never called.
     - A message with an old `g` returns `None` unread.
   - **The Phone gate:** with `phone_on` false, a `Notify` returns `None`, and `get_child_value` and `get_body` are never called.
   - **Privacy:**
     - A body whose `get_string` raises gives exactly one stderr line, with no summary text in it.
     - No `seen` argument ever contains summary or body text.
   - **Lifecycle,** with `_load` stubbed and `new_for_address_sync` returning fakes:
     - Phone off: no connect.
     - Phone on: connect.
     - A failure at `GetId`, `GetNameOwner` or `BecomeMonitor` closes every fake made, logs one line, and sets `retry_at` to `now + 4`, then `now + 8`.
     - Phone switched off while `connect` runs (the fake's `BecomeMonitor` flips it): the result is closed.
     - An owner change between the two `GetNameOwner` calls: closed, and it fails.
     - A message delivered from inside the fake's `BecomeMonitor` (during setup) counts under the new owner.
     - `is_closed()` true, `stale`, or a changed owner on `tick`: `close()`, then a reconnect after the back-off.
   - **The fallback** (in `test_code_pause.py`):
     - `seen("w")`, then 1 s later `seen("s", fallback=True)`: `pending` is 1, and `"s"` is recorded.
     - 11 s after a watch count, `seen("s2", fallback=True)` raises `pending`.
     - With no watch count, a fallback raises `pending`, as in #105.
     - `seen("s", fallback=True)` again never raises `pending`.
     - A duplicate watch key doesn't refresh `last_watch`.
   - **The display gate** (in `test_inbox.py`): a code row is still blanked, and `seen` is called with `fallback=True`.
   - **The toast:**
     - With `Wake.asleep` true, a confirmed pause sets `until` and doesn't publish.
     - With it false, it publishes `phone.clip_paused`.
   - **Verify:**
     - `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_notify_watch.py test_code_pause.py test_inbox.py`.
     - Mutation-check by reverting, one at a time: the Phone gate, the outgoing pass-through, the generation check, the reply-age check, the fallback grace, and the toast gate. Each must fail at least one test.
   - **Trap:** never import `server` outside `_ServerEnv`, because that writes the real HOME's config (#176).

4. **`flake.nix` dev shells (`:52`–`:75`) and a new `tests/test_notify_watch_bus.py`**
   - **The shells:** in `base`, replace `pkgs.python3` with `(pkgs.python3.withPackages (p: [ p.pygobject3 ]))`, and add `pkgs.dbus`.
   - **The bus:**
     - In `setUp`, start a private bus: `dbus-daemon --session --nofork --print-address=1 --address=unix:dir=<tmp>`.
     - Read the address and kill it in `tearDown`.
     - Patch `os.environ["DBUS_SESSION_BUS_ADDRESS"]` only inside the test.
     - Skip with a reason when `dbus-daemon` or `gi` is missing. In `.#ci` it must run.
     - This replaces the spec's `dbus-run-session` wording; see Deviations.
   - **The fake server:**
     - A Gio connection that owns `org.freedesktop.Notifications` and exports `Notify` at `/org/freedesktop/Notifications`, returning ids 1, 2, 3 and so on.
     - Its GLib main loop runs on its own thread.
     - A second fake can take the name over.
   - **Cases:**
     - A real `NotifyWatch.connect()` succeeds.
     - A code notification sent with `Gio` from a client connection counts once.
     - Its update (with `replaces_id`) doesn't count again.
     - A `Notify` sent to another owned name (`org.example.Other`) never reaches the filter's body read. Wrap `NotifyWatch.filter` with a spy that records which destinations reached step 5.
     - **Owner change:** the first fake releases the name, and the second takes it. After `tick()`, a new code counts under the new owner.
     - **Dropped connection:** `NotifyWatch.mon.close_sync(None)` from the test is noticed by the next `tick()`, which reconnects.
     - A real variant with a 1 MB body and 10,000 actions finishes under 0.2 s.
   - **Verify:**
     - `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_notify_watch_bus.py` runs; it is not skipped.
     - `nix flake check --no-build` evaluates.
     - The full suite still passes with PyGObject now in the shell.
   - **Trap:** never touch the host's session bus.

5. **`docs/GUIDE.md:165`, the "Codes and the clipboard" paragraph**
   - Rewrite it in the guide's short-sentence style:
     - the pause now works while Nixi is hidden, on every desktop notification, whenever Phone is on;
     - it is silent while hidden;
     - the shell's **Copy code** button is never shared anyway, because Flux skips sensitive copies;
     - **the cost:** more false positives, each one a 2-minute pause;
     - #105's limits still apply: a copy made earlier, a send already past Flux's check, a notification seen again after 10 min, and a `fluxd` restart.
   - **Verify:** `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_docs_names.py`.

6. **Lead only: checks, reviews, PR and rollout**
   - **Checks:** the full suite and the fit tests (see Tests).
   - **Opus review:** a fresh Opus agent, given only this plan's path and `git diff origin/main`.
   - **Codex branch review:** `codex review --base origin/main`, with `git status --porcelain` checked before and after.
   - **PR:** it links the intent, spec and plan, says which steps codex and the coder did, and gets an "@codex review" comment.
   - **After merge:**
     - A nixos_config PR bumping `nixi-companion`, from a clean worktree of `origin/main` with `nixarchy-theme.nix` copied in.
     - CI, then an agent-bus announcement.
     - `AGENT_BUS_ANNOUNCED=1 nh os switch .` on p620, and `AGENT_BUS_ANNOUNCED=1 just deploy-via-p620 razer`. Use `NIX_SSHOPTS="-o HostName=razer.tail833f7.ts.net"` when razer is off the LAN.
     - Restart Nixi on both with the live Hypr signature: `systemd-run --user -p RemainAfterExit=yes -E HYPRLAND_INSTANCE_SIGNATURE=$(ls -t /run/user/1000/hypr/|head -1) $(readlink -f $(which nixi-companion)) restart`.
   - **Runtime checks on each host, with Nixi hidden:**
     1. `notify-send -p "Your sign-in code" "551872 is your verification code"`. Within 3 s, `flux-cli status --json` lists a `nixi-otp` pause about 120 s out. No toast and no window appear.
     2. `notify-send -r <printed id> "Your sign-in code" "551872 is your verification code (still valid)"` doesn't move the expiry.
     3. With Phone off in Nixi, a new code makes no pause.
     4. Restart `omarchy-shell`, which makes the notification server change owner. A new code then still pauses, after at most one reconnect (≤ 4 s).

## Tests

```bash
nix develop .#ci -c python3 -B .github/ci/run_tests.py --exclude test_character_fit.py --exclude test_accessories_fit.py
nix develop .#ci -c python3 -B .github/ci/run_tests.py --deadline 1800 test_character_fit.py test_accessories_fit.py
```

Both must pass. `test_notify_watch_bus.py` must run, not be skipped, in `.#ci`.

## Rollback

- **Code:** revert the PR's squash commit, then bump `nixi-companion` back in nixos_config and redeploy.
- **Without a deploy:** turn Phone off in Nixi. The filter stops reading at once, and the watch closes within 2 s.
- **Pauses already set:** they expire by themselves within 120 s.

## Deviations

1. **The bus test starts its own `dbus-daemon`** instead of running under `dbus-run-session`, as the spec's Verification says.
   - **Why:** the test needs the bus address in-process, and needs to change the name owner and close connections during the test.
   - The result is the same: a private bus, never the host's.
2. **The back-off no longer grows while the notification server is gone,** and Phone off resets it. This comes from the Opus review.
   - A `connect()` that fails with `org.freedesktop.DBus.Error.NameHasNoOwner` retries on the next tick (2 s) without raising `fails`. Under the plan's rule, an omarchy-shell restart longer than about 30 s left the watch off for up to 5 min afterwards.
   - Phone off resets `fails` and `retry_at`, so turning Phone on connects at once.
   - Other failures keep `min(300, 2·2^n)`.
3. **Other changes from the Opus review:**
   - A test covers the second generation check in the filter (a `close()` while it reads).
   - `.github/ci/run_tests.py` drops `DBUS_SESSION_BUS_ADDRESS`, so no test can reach the runner's real session bus.
   - The bus test asserts that the private daemon printed an address, and it restores `NotifyWatch.logged`.
4. **Step 3's additions to `test_code_pause.py` and `test_inbox.py`** already landed with steps 1 and 2, written by the implementer. Step 3 added `tests/test_notify_watch.py` only.
5. **Step 4's update case** asserts that the update produces the same key. The real dedupe of that key is covered in `test_notify_watch.py` and `test_code_pause.py`.
