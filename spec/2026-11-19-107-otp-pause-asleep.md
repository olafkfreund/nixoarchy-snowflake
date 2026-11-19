---
status: draft
issue: 107
intent: intent/2026-11-19-107-otp-pause-asleep.md
---

# Spec: pause clipboard sharing for codes while Nixi is hidden

## Design

One new class, `NotifyWatch`, in `app/server.py` next to `CodePause` (`:3184`). It watches the session bus for `Notify` calls, checks each one with #105's checks, and feeds `CodePause.seen()`. `CodePause` itself is unchanged except for the toast rule.

### The connection (`NotifyWatch.connect`)

- **Address:** `Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION)`. PyGObject is already packaged (`nix/package.nix:45`).
- **Two private connections,** each from `Gio.DBusConnection.new_for_address_sync(addr, AUTHENTICATION_CLIENT | MESSAGE_BUS_CONNECTION)`, never `Gio.bus_get_sync`, whose shared connection would turn into a monitor:
  1. **`plain`** asks `GetNameOwner("org.freedesktop.Notifications")` and is then closed. No owner (`NameHasNoOwner`) means no notification server: connect fails, and the loop tries again later.
  2. **`mon`** adds the filter, then calls `org.freedesktop.DBus.Monitoring.BecomeMonitor(rules, 0)` with three rules:
     - `type='method_call',interface='org.freedesktop.Notifications',member='Notify'`
     - `type='method_return',sender='<owner>'`: only the notification server's replies, not every reply on the bus.
     - `type='signal',sender='org.freedesktop.DBus',member='NameOwnerChanged',arg0='org.freedesktop.Notifications'`: a server restart.
- **Probed on p620 and razer (2026-11-19):** `BecomeMonitor` succeeds as the user on both. A new notification's call has `replaces_id` 0 and its reply carries the new id. An update carries that id and gets the same id back (p620 1970 → 1970, razer 5 → 5).
- **Two Gio traps found by the probe,** both handled in the filter:
  - Filters also see **outgoing** messages. The filter returns those unchanged, or `BecomeMonitor` itself is dropped and times out.
  - Messages addressed to `mon` itself (the `BecomeMonitor` reply) are returned unchanged. Every monitored message is consumed (`None`).

### The filter (`NotifyWatch.filter`, on Gio's worker thread; it must not block)

- **On a `Notify` call:**
  1. Read `summary` (arg 3), `body` (arg 4) and the action labels (arg 5, the odd entries).
  2. Turn the body into visible text exactly as `Inbox.rows` turns `rich` into text (`:3428`): `Inbox.STRIP` (a `<br>` becomes a newline), then `Inbox.ENT`.
  3. Cap the joined text at 64 KiB. `OTP.match` and `SECRET_LINE` are linear, so this only bounds the worst case.
  4. Compute `hit` with `Inbox.OTP.match(text) or SECRET_LINE.search(text)`, the same expression as `:3433`.
  5. On a hit, store `pending[(sender, serial)] = monotonic now`. Nothing else is kept: no text and no app name.
  6. `pending` holds at most 64 entries, and entries older than 10 s are dropped on each insert.
- **On a reply from the owner:**
  - If `(destination, reply_serial)` is in `pending`, pop it, read the `u` id, and call `CodePause.seen(f"{owner}:{id}")`.
  - The id from the reply is the identity. A new notification and its later updates share one key. A clean notification updated to a code counts once, when the code appears, because only hits reach `pending`.
- **On `NameOwnerChanged`:** the notification server restarted, and ids restart with it. The watch marks itself down (`up = False`) and closes `mon`. The loop reconnects to the new owner, whose ids are namespaced by its new bus name.
- **Any exception** in the filter is caught. It logs a single line through `_log`, the first time only, and the message is consumed.

### Lifecycle (`NotifyWatch.loop`, one daemon thread)

- `start()` is called from `Inbox.start()` next to `CodePause.start()` (`:3557`). It starts one thread, under a lock.
- **Every 5 s:**
  - If `CFG.get("phone_on") is True` and the watch is not up, it tries `connect()`.
    - On success: `up = True`.
    - On failure (refused, no server, any `GLib.Error`): one stderr line per process, content-free: `[nixi] notification watch: <domain/code or type>`. The next try waits `min(300, 5·2^n)` s.
  - If Phone is off and the watch is up, it closes `mon`, and `up = False`.
- `mon`'s `closed` signal sets `up = False`. Covered cases: the bus went away, or the connection was closed above.
- `up` is read and written under `NotifyWatch.lock`.

### Sharing the pause with #105 (decision 2)

- `Inbox.rows` (`:3434`) calls `CodePause.seen(x["key"])` only when `not NotifyWatch.up`.
- The display gate (`hit` blanking text and handing cards back) is unchanged and still uses `hit` whatever the watch says.

### What you see (decision 3)

- **`CodePause.turn`** publishes the toast only when `not Wake.asleep`. A pause confirmed while Nixi is hidden is silent.
- Nothing else changes: no popup, no voice, no window.

### Docs

`docs/GUIDE.md`, the "Codes and the clipboard" paragraph (#105):

- It now works while Nixi is hidden, on every notification sent to the desktop, not only those Nixi takes over.
- It is silent while hidden.
- The shell's **Copy code** button is already never shared, because Flux skips sensitive copies.
- **What it costs:** more false positives, each one a 2-minute pause.

### nixos_config

After merge, one PR bumps `nixi-companion`. Deploy to p620 and razer, then restart Nixi.

## Alternatives rejected

- **`busctl monitor` as a subprocess.** It isn't on Nixi's PATH (`nix/package.nix:102`), and its output is text meant for people.
- **Legacy eavesdropping (`AddMatch` with `eavesdrop=true`).** dbus-broker refuses it outside `BecomeMonitor`.
- **A `method_return` match without `sender`.** It would show Nixi every reply on the session bus.
- **Keying on `replaces_id` alone.** It is 0 for every new notification.
- **Keying on the call serial.** Every update would count as new.
- **Running the monitor only while Nixi is asleep.** The hand-off at each sleep change opens gaps, and decision 2 asks for one source while the watch is up.
- **Both sources always on.** One notification would count twice under different keys, using 2 of the 5 requests in a hold.
- **A main loop for Gio.** Filters run on GDBus's own worker thread, so none is needed.

## Risks

- **False positives grow:** every app's notifications are checked, not only the shell's categories. Each match costs a 2-minute pause, and `MAX` caps a stretch at 5 requests. This is accepted and documented.
- **Privacy:** Nixi reads every notification's text while Phone is on.
  - It is bounded by the three match rules and the in-memory-only filter.
  - `pending` holds only keys and times.
  - Tests check that nothing reaches stderr, the page or `CodePause` except the key.
- **The filter thread:** a slow filter would delay GDBus's worker for `mon` only. `mon` is private, so Nixi's other D-Bus users (none share it) are unaffected.
- **A notification server that answers `Notify` late or never:** its `pending` entry ages out after 10 s, and no pause happens. This is accepted.
- **A sandboxed sender (portal) or a server that doesn't own the well-known name** is not covered. This is accepted.
- **p620 and razer:** a Nixi restart only. No Flux or shell change.

## Verification

### New `tests/test_notify_watch.py`

It runs under `nixi_env`, with fake Gio message objects fed straight into `NotifyWatch.filter` and no real bus. It covers:

- **Identity:**
  - a code `Notify` call (`replaces_id` 0) followed by its reply calls `seen("<owner>:<id>")` once;
  - an update with the same id doesn't call it again (via `CodePause` dedupe);
  - a clean call followed by an update with a code calls it once;
  - a reply with no matching call does nothing.
- **Detection:**
  - a code only in the body after markup (`<b>482</b>910` with "sign-in code") is found;
  - a long link id inside `<a href=…>` is not;
  - a code only in an action label is found;
  - `SECRET_LINE` alone is enough;
  - a 1 MB body finishes in under 1 s.
- **Messages passed through:** outgoing messages, and messages addressed to the watch's own unique name, are returned unchanged. Monitored ones return `None`.
- **Pending bounds:** at most 64 entries; an entry 11 s old is dropped.
- **Server restart:** `NameOwnerChanged` sets `up = False` and closes the connection.
- **Privacy:** a malformed body does one `_log` and no stderr text from the notification. The `seen()` argument never contains summary or body text.
- **Lifecycle,** with `connect` patched:
  - Phone off: no connect;
  - Phone on: connect, then `up`;
  - a refusal: one log line, then the next try after the back-off;
  - Phone turned off: close, then `up = False`.

### `tests/test_inbox.py` and `tests/test_code_pause.py`

- With `NotifyWatch.up` true, a code row doesn't call `seen` but is still blanked. With it false, `seen` is called, as #105 does.
- With `Wake.asleep` true, a confirmed pause sets `until` and publishes no toast. Shown, it still publishes the toast.

### Full suite

```bash
nix develop .#ci -c python3 -B .github/ci/run_tests.py --exclude test_character_fit.py --exclude test_accessories_fit.py
```

This must pass, then the fit tests.

### Runtime on p620 and razer after deploy, with Nixi hidden

1. `notify-send "Your sign-in code" "551872 is your verification code"`. Within 3 s, `flux-cli status --json` lists a `nixi-otp` pause about 120 s out. No toast and no Nixi window appear.
2. `notify-send -r <id> …` with the same id doesn't send a new request: the expiry stays put.
3. With Phone off in Nixi, a new code makes no pause.
4. `systemctl --user restart` of the notification server (or an omarchy-shell restart), then a new code, still pauses.
