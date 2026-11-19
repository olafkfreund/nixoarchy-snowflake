---
status: approved
issue: 107
intent: intent/2026-11-19-107-otp-pause-asleep.md
---

# Spec: pause clipboard sharing for codes while Nixi is hidden

## Design

One new class, `NotifyWatch`, in `app/server.py` next to `CodePause` (`:3184`).

- It watches the session bus for `Notify` calls to the notification server, which is omarchy-shell on p620 and razer.
- It checks each call with #105's checks and feeds `CodePause`.
- `CodePause` gains a fallback flag on `seen` and a toast rule. `Inbox.rows` passes that flag.

### The connection (`NotifyWatch.connect`)

- **Address:** `Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION)`. PyGObject is already packaged (`nix/package.nix:45`).
- **Two private connections** from `Gio.DBusConnection.new_for_address_sync(addr, AUTHENTICATION_CLIENT | MESSAGE_BUS_CONNECTION)`. It never uses `Gio.bus_get_sync`: its shared connection would turn into a monitor.
  1. **`plain`**, kept for the life of the watch. It asks:
     - `GetId()`: the bus instance, so ids from a restarted bus never collide;
     - `GetNameOwner("org.freedesktop.Notifications")`: the owner `O`. `NameHasNoOwner` fails the attempt.
  2. **`mon`** adds the filter, then calls `org.freedesktop.DBus.Monitoring.BecomeMonitor(rules, 0)` with four rules:
     - `type='method_call',destination='org.freedesktop.Notifications',path='/org/freedesktop/Notifications',interface='org.freedesktop.Notifications',member='Notify'`;
     - the same with `destination='<O>'`, for a client that addresses the owner directly;
     - `type='method_return',sender='<O>'`: only the notification server's replies, not every reply on the bus;
     - `type='signal',sender='org.freedesktop.DBus',member='NameOwnerChanged',arg0='org.freedesktop.Notifications'`.
- **Owner check after the monitor starts:**
  - `plain` asks `GetNameOwner` again. If the answer isn't `O`, the owner changed between the two calls, and the monitor holds stale rules: close `mon` and fail the attempt.
  - The same check runs after `connect` returns, once Phone has been confirmed still on (see Lifecycle). A connection that finishes after Phone was switched off is closed, not kept.
- **Probed on p620 and razer (2026-11-19):** `BecomeMonitor` succeeds as the user on both.
  - A new notification's call has `replaces_id` 0, and its reply carries the new id.
  - An update carries that id and gets the same id back: p620 1970 → 1970, razer 5 → 5.
- **Two Gio traps the probe found,** both handled in the filter:
  - Filters see **outgoing** messages too. The filter returns them unchanged, or `BecomeMonitor` itself is dropped and times out.
  - Messages addressed to `mon`'s own unique name, such as the `BecomeMonitor` reply, are returned unchanged. Every monitored message is consumed (`None`).

### The filter (`NotifyWatch.filter`, on GDBus's worker thread)

- **Phone first:** if `CFG.get("phone_on") is not True`, the filter returns `None` before touching the body. A message that arrives after Phone is switched off is never read.
- **On a `Notify` call:**
  1. Check that `get_signature()` is `susssasa{sv}i`. Otherwise drop the call.
  2. Take only children 3 (summary), 4 (body) and 5 (actions) with `get_child_value`. The hints (child 6) are never unpacked.
  3. Bound each field **before** any normalising:
     - summary and body: the first 16 KiB of each;
     - actions: the first 64 entries, and the first 1 KiB of each label (the odd entries).
     - The shell hands Nixi at most 200 characters of summary, 200 of body, 40 per label and 600 of rich text (omarchy `Service.qml:731-736`). These bounds see strictly more than #105's check, so they never hide a code that #105 would catch.
  4. Turn the body into visible text exactly as `Inbox.rows` does for `rich` (`:3428`): `Inbox.STRIP` (a `<br>` becomes a newline), then `Inbox.ENT`.
  5. Join summary, body and labels with `\n`.
  6. `hit = Inbox.OTP.match(text) or SECRET_LINE.search(text)`, the same expression as `:3433`.
  7. On a hit, store `pending[(sender, serial)] = monotonic now`. Nothing else is kept.
  8. `pending` holds at most 64 entries, and entries older than 10 s are dropped on each insert.
- **On a reply from `O`:** if `(destination, reply_serial)` is in `pending`, pop it, read the `u` id, and call `CodePause.seen(f"{bus_id}:{O}:{id}")`.
  - The id from the reply is the identity, so a new notification and its later updates share one key.
  - A clean notification updated to a code counts once, when the code appears, because only hits reach `pending`.
  - `bus_id` keeps a restarted bus's repeated unique names and ids apart.
- **On `NameOwnerChanged`:** set `stale = True`. The loop closes `mon` and reconnects to the new owner.
- **Any exception** in the filter is caught, logged once through `_log`, and the message is consumed.
- **`pending` and `stale`** are guarded by `NotifyWatch.lock`. The filter never blocks beyond that lock and the bounded match.

### Lifecycle (`NotifyWatch.loop`, one daemon thread)

- `start()` is called from `Inbox.start()` next to `CodePause.start()` (`:3557`). It starts one thread, under a lock.
- **Every 2 s:**
  - **Phone off** with `mon` open: close `mon` and `plain`. The filter's Phone check already stops reading in between.
  - **Phone on:**
    - If `mon` is open and `mon.is_closed()`, `stale`, or the owner check fails, close everything. Polling `is_closed()` is used because the `closed` signal needs a GLib main context that Nixi doesn't run.
    - If nothing is open and the back-off has passed: `connect()`. Then re-check Phone and the owner; if either fails, close.
    - On a failure (refused, no server, any `GLib.Error`): one stderr line per process, with no content: `[nixi] notification watch: <domain>:<code>`. The next try waits `min(300, 2·2^n)` s. A success resets `n`.

### Sharing the pause with #105 (decision 2, refined; see the intent)

#105's `Inbox.rows` hook stays as the fallback. Instead of switching on an "is the watch up" flag, which can be wrong during a reconnect, the watch's own history decides:

- **`CodePause.seen(key, fallback=False)`** records `last_watch = monotonic now` when `fallback` is false.
- **`Inbox.rows` (`:3434`) calls `CodePause.seen(x["key"], fallback=True)`.**
  - The key is always recorded, so later updates of the same shell row are deduped as in #105.
  - `pending` is increased only if no watch-sourced code was counted in the last 10 s.
- **The cases this covers:**
  - **Watch up:** the reply arrives within milliseconds, before the shell hands the row over on its 1 s lease. The fallback is skipped, and the notification counts once.
  - **Watch down, starting, or missed it:** no watch count in the last 10 s, so the fallback counts. This is never worse than #105.
- **What's left, accepted and tested:**
  - **A late row:** a row the shell hands over more than 10 s after the watch counted it counts once more. That's at most one extra request in the hold.
  - **A second code within 10 s seen only by `Inbox`:** it doesn't renew the pause. The hold was renewed under 10 s earlier, so the pause still has at least 110 s to run.
- **The display gate is unchanged:** `hit` still blanks text and hands cards back.

### What you see (decision 3)

- **`CodePause.turn`** publishes the toast only when `not Wake.asleep`. A pause confirmed while Nixi is hidden is silent.
- Nothing else changes: no popup, no voice, no window.

### Docs

`docs/GUIDE.md`, the "Codes and the clipboard" paragraph (#105):

- It now works while Nixi is hidden, on every notification sent to the desktop, not only those Nixi takes over.
- It is silent while hidden.
- The shell's **Copy code** button is never shared anyway, because Flux skips sensitive copies.
- **The cost:** more false positives, each one a 2-minute pause.

### nixos_config

After merge, one PR bumps `nixi-companion`. Deploy to p620 and razer, then restart Nixi.

## Alternatives rejected

- **`busctl monitor` as a subprocess.** It isn't on Nixi's PATH (`nix/package.nix:102`), and its output is text meant for people.
- **Legacy eavesdropping (`AddMatch` with `eavesdrop=true`).** dbus-broker refuses it outside `BecomeMonitor`.
- **A `method_return` or `Notify` rule without `sender` or `destination`.** It would read messages meant for other services.
- **Keying on `replaces_id` alone.** It is 0 for every new notification.
- **Keying on the call serial.** Every update would count as new.
- **An "is the watch up" flag to choose the source** (the first spec draft). A disconnect that hasn't been noticed yet, or a code that arrives before the watch starts, would be lost or counted twice.
- **The `closed` signal.** It is only delivered by a running GLib main context.
- **A main loop for Gio.** Filters run on GDBus's worker thread, and polling `is_closed()` replaces the signal.
- **Truncating the joined text.** It bounds work after the expensive steps, and a long body could push a later label past the cut.
- **A content hash as a shared key across both sources.** Updates with new text would count again, and it keeps a fingerprint of the text.

## Risks

- **False positives grow:** every app's notifications are checked, not only the shell's categories. Each match costs a 2-minute pause, and `MAX` caps a stretch at 5 requests. Accepted and documented.
- **Privacy:** Nixi reads every notification's text while Phone is on. This is bounded by:
  - the four rules;
  - the Phone check before any body is read;
  - the per-field bounds;
  - the in-memory-only filter.
  - `pending` holds only keys and times.
  - The tests check that nothing but the key leaves the filter.
- **GDBus's worker may be shared across connections:** a slow filter could delay other GDBus users in the process. The work is bounded (≤ ~50 KiB of linear matching), and Nixi has no other GDBus users today.
- **A notification server that answers late or never:** its entry ages out after 10 s, and no pause happens from the watch. The fallback still counts if the row reaches `Inbox`.
- **Not covered:** a sender that calls a server outside the well-known name or its owner. Accepted.
- **p620 and razer:** a Nixi restart only. No Flux or shell change.

## Verification

### New `tests/test_notify_watch.py`: unit tests with fake messages, under `nixi_env`

- **Identity:**
  - a code call (`replaces_id` 0) followed by its reply calls `seen("<bus>:<owner>:<id>")` once;
  - an update with the same id doesn't count again;
  - a clean call followed by a code update counts once;
  - a reply with no matching call does nothing;
  - the same owner and id under a different bus id count again.
- **Detection:**
  - a code only after markup (`<b>482</b>910` with "sign-in code") is found;
  - a long link id inside `<a href=…>` is not;
  - a code only in an action label is found;
  - `SECRET_LINE` alone is enough;
  - a code at character 300 of the body (past the shell's 200) is found.
- **Bounds:**
  - a 1 MB body, and 10,000 action entries, finish in under 0.2 s, and the hints are never unpacked (a fake whose child 6 raises);
  - `pending` holds at most 64 entries, and an 11 s-old entry is dropped.
- **Messages passed through:** outgoing messages, and messages to `mon`'s own name, come back unchanged. Monitored ones return `None`. A wrong signature is dropped without being read.
- **Phone gate:** with Phone off, the filter never calls `get_body` or `get_child_value`.
- **Privacy:** a malformed body gives one `_log` line with no notification text. The `seen` argument never contains summary or body text.
- **Lifecycle,** with `connect` and the connections faked:
  - Phone off: no connect;
  - Phone on: connect;
  - a refusal: one log line, then the next try after the back-off;
  - Phone switched off while `connect` is running: the new connection is closed;
  - `is_closed()` true, `stale`, or a changed owner: close, then reconnect.

### New `tests/test_notify_watch_bus.py`: integration tests on a real private bus

- It runs under `dbus-run-session`, with `dbus` added to the `.#ci` dev shell (`flake.nix:69`). It is skipped with a reason when `dbus-run-session` is missing.
- A fake notification server (Gio, owning `org.freedesktop.Notifications`) returns ids. The tests check:
  - real `BecomeMonitor`;
  - a code notification counts once;
  - its update doesn't count again;
  - a `Notify` sent to another name isn't read;
  - **owner change:** the fake server releases the name, a second one takes it, and a new code still counts under the new owner;
  - **closing the watch's connection from outside:** detected within one 2 s poll, then reconnected;
  - oversized fields as real variants stay within the time bound.

### `tests/test_inbox.py` and `tests/test_code_pause.py`

- **The fallback:**
  - with a watch count 1 s earlier, an `Inbox` code row records its key but doesn't send;
  - 11 s later, a new `Inbox` code row sends;
  - with no watch count, it sends, as in #105;
  - an update of a recorded shell row never sends.
- **The display gate:** `hit` still blanks rows whatever the watch did.
- **The toast:** with `Wake.asleep` true, a confirmed pause sets `until` and publishes no toast. While shown, it publishes the toast.

### Full suite

```bash
nix develop .#ci -c python3 -B .github/ci/run_tests.py --exclude test_character_fit.py --exclude test_accessories_fit.py
```

This must pass, then the fit tests.

### Runtime on p620 and razer after deploy, with Nixi hidden

1. `notify-send -p "Your sign-in code" "551872 is your verification code"`. Within 3 s, `flux-cli status --json` lists a `nixi-otp` pause about 120 s out. No toast and no window appear.
2. `notify-send -r <id> …` with the printed id doesn't move the expiry.
3. With Phone off in Nixi, a new code makes no pause.
4. `omarchy-shell` restarted (the notification server changes owner), then a new code, still pauses within one reconnect.
