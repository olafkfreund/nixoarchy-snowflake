---
status: draft
issue: 105
intent: intent/2026-11-18-105-otp-clipboard-pause.md
---

# Spec: pause Flux clipboard sharing while a one-time code is around

## Design

One small class, `CodePause`, in `app/server.py` next to `Inbox`. `Inbox.rows` tells it when a row carries a code.
A single worker thread asks Flux for an owned pause, so the notification path never waits.

### Detection (`Inbox.rows`, `app/server.py:3305`)

- **One verdict per row, from the full text:** for each row that passes the key and category checks, Nixi computes
  `hit` once from the raw text, before any cut. The raw text is:
  - the untruncated `summary` and `body`;
  - for cards, the raw `rich` string and the button labels in full.
- **The test:** `hit = bool(Inbox.OTP.search(text) or SECRET_LINE.search(text))`, whatever `notify_details` says.
- **The display gate uses `hit` too.** Today it tests the text after the 120-character cut (`:3318`–`:3320`), so a code
  past character 120 with its code word inside the cut is shown. Checked: `"123456 " + "hello " * 22 + "sign-in code"`
  matches in full but not cut. With this change:
  - `:3320` blanks when `not notify_details or hit`;
  - the card gate at `:3331` blanks or hands back when `not notify_details or hit` or its own existing test matches.
    That keeps today's check over the parsed runs and adds the full-text one.
  - This closes an existing leak. It never shows more than today.
- **On a hit,** `rows` calls `CodePause.seen(row_key)` before any `continue`, including the card the shell keeps
  (`:3333`).
  - `seen` stores the key and a time, nothing else, and wakes the worker.
  - It is non-blocking: one short lock, no I/O. No text is stored, logged or passed on.
- **Notifications only.** `mail_otp` (`:7246`) is untouched.

### `CodePause` state

- `OWNER = "nixi-otp"`: fixed, ASCII, 8 bytes, so it meets Flux's label rules.
- `SECS = 120`. `MAX = 5` requests per hold.
- All fields below are guarded by one `threading.Lock` (`lock`):
  - `keys`: row key → when it was first seen;
  - `pending`: the count of new keys not yet sent;
  - `sent`: requests counted in the current hold;
  - `until`: the latest moment Nixi's pause may still be in force, in `time.time()` seconds;
  - `gen`: the Phone connection number of the current hold.
- An `Event` wakes the worker.

### Dedupe

- A key already in `keys` does nothing: an update or repeat of one notification is not a new code.
- **Retention limit:** `keys` holds at most 64 keys and forgets each after 10 min. A key presented again after that
  counts as new and can pause again.
  - This narrows the intent's repeat rule to "within 10 min and 64 notifications". The cost is one more bounded pause.
  - The docs say so.

### Worker

- It starts with `Inbox.start()`, as one daemon thread. It never runs on Phone's reader thread, so `phone.py:193`
  holds.
- **Each turn:**
  1. Wait on the `Event`, then clear it.
  2. **Under `lock`:** if `pending == 0`, loop. If `until <= now`, the hold is over: set `sent = 0`.
     - If `sent >= MAX`, drop `pending` (set it to 0) and loop: the codes arrived while the hold was used up.
     - Otherwise take the work: `pending = 0`, `sent += 1`, and note `g = Phone.session`.
     - Then release the lock. Keys that arrive during the call set `pending` again and are not lost; the next turn
       sends them.
  3. **Eligibility,** outside the lock: Phone on (`CFG.get("phone_on") is True`), `Phone.connected`, and
     `"clipboardPauses"` present in the snapshot.
     - If any fails, the taken work is dropped and `sent -= 1`: nothing was sent.
     - The intent accepts that a code seen while Flux is unusable is not paused later.
  4. `r = Phone.call("clipboard.pauseOwned", owner=OWNER, expires=SECS)`.
  5. **Account under `lock`,** per outcome:

     | Outcome | `until` | `sent` | Shown |
     |---|---|---|---|
     | `NotSent` | unchanged | `-= 1` (nothing reached Flux) | nothing |
     | `TimeoutError`, `ConnectionError` raised after the write | `max(until, call start + SECS)` (it may have taken effect) | kept | nothing |
     | `RuntimeError` from a Flux error (`too_many`, `bad_params`, …), `ValueError` | unchanged | kept | nothing |
     | Reply whose `expires` is not an `int` greater than `time.time() + 1` | `max(until, call start + SECS)` | kept | nothing |
     | Good reply, but `Phone.session != g` (Flux restarted or Phone was reset meanwhile) | unchanged | kept | nothing |
     | Good reply, same session | `max(until, expires)` | kept | toast |

     - The conservative `until` means an unconfirmed request still counts toward the hold. A late reply can't reset
       the budget early.
     - `sent` resets only at step 2, once `until` has passed. So at most `MAX` requests reach Flux per stretch of
       time in which Nixi's pause may be in force: about 10 min.
     - Flux's own 1 h cap per continuous hold stays the outer limit.
  6. **Failures** print at most one stderr line per process, with the exception type only: `[nixi] code pause: <Type>`.
     There is no retry.
- **`Phone.session`:** a new read-only property in `app/phone.py`. It is a counter that rises by 1 each time the
  reader marks a connection live (`:261`).
  - It is needed because `_version` also rises on every snapshot, so it can't tell a reconnect from a snapshot.
- **`Phone.METHODS`** gains `"clipboard.pauseOwned"` only. `resumeOwned`, `pause` and `resume` stay out, so Nixi can
  never end or shorten a pause, its own included.
- **Phone off, Flux down, `fluxd` restart:** Nixi does nothing extra. A pause it already set runs out by itself.
  - After a `fluxd` restart the pause is gone and Nixi does not restore it. A later new code starts a new one once
    `until` has passed.

### What you see

- **Each confirmed request** publishes `BUS.pub(t="toast", text=lang.t("phone.clip_paused"))`.
  - The page shows toasts in one chip, and `tick()` (`app/static/index.html:3494`) overwrites its text and restarts
    its timer. A renewal therefore updates the one line in place and never adds a second one, which is decision 3.
- **New string `phone.clip_paused`** in `app/lang/en.json`, `nb.json` and `pl.json`:
  - en: "Clipboard sharing paused for the code"
  - nb: "Deling av utklippstavlen er satt på pause for koden"
  - pl: "Udostępnianie schowka wstrzymane na czas kodu"

### Agent boundary

- No HTTP route or tool endpoint is added. `CodePause` is reachable only from `Inbox.rows`.
- The `flux-cli` policy at `app/server.py:962` is unchanged.

### Docs

`docs/GUIDE.md:163`: replace "pausing the clipboard from Nixi" with a short paragraph. It covers:

- **What triggers it:** a notification with a code or secret, while Nixi takes notifications over.
- **How long:** 2 min, renewed by a new code, for about 10 min at most, then not again until it has run out.
- **The limits:** only while notifications are taken over; a copy made before the notification can still go out; a
  send already past Flux's check still goes out; a notification seen again after 10 min counts as new.
- **What it costs:** copies made during it are not shared and stay out of Flux history; copying the same value
  again after it ends may not sync; manual sends still work.
- **Restarts:** a `fluxd` restart drops it.

### nixos_config

- After the Nixi PR merges, one PR moves two inputs:
  - `nixarchy-flux` from `6eb6347` to `8267293`, the #77 merge;
  - `nixi-companion` to the #105 merge.
- Deploy to p620 and razer. Both restart `fluxd`. p510 doesn't run Flux.

## Alternatives rejected

- **Reuse the display gate for detection.** It stops early when `notify_details` is off, the default (`:262`), and
  tests cut text.
- **Silent renewals.** They contradict decision 3, and the single toast chip already gives an in-place update.
- **`resumeOwned` on dismiss.** Rejected by decision 2.
- **A per-hold random owner label.** It would fill Flux's 8-owner table on repeated holds and buys nothing: labels are
  not identity.
- **Calling inline from `Inbox.tick`.** `Phone.call` waits up to 10 s and would stall the 1 s lease loop.
- **Probing by calling `pauseOwned` on any Flux.** The `clipboardPauses` snapshot key says the same without an error
  on old builds.
- **Unbounded dedupe.** It would grow without limit on a long-running Nixi.
- **A setting.** Not needed. The feature follows the Phone switch.
- **Mail codes.** Rejected by decision 4.

## Risks

- **False positives.** `OTP` also matches ordinary text such as "your PIN 1234 reminder", and `SECRET_LINE` matches some
  technical notifications.
  - Either one pauses sharing for 2 min, and now also blanks that row's text, as the cut-text gate already does for
    shorter rows.
  - The `MAX` bound limits the cost. Accepted.
- **False negatives.** Codes the regexes miss are not paused. It is a mitigation.
- **A toast published by someone else in the same 3.4 s** replaces this one, and the other way round. Accepted; that
  is how every toast behaves today.
- **On both p620 and razer:** the flux bump `6eb6347` → `8267293` carries only #77 and a CI-only commit (`70d109c`).
  Restarting `fluxd` drops any pause and reconnects the phone.

## Verification

### New `tests/test_code_pause.py`

It runs under `nixi_env`, with `Phone.call` and `Phone.session` patched, and covers:

- **The request:** a code row sends exactly `("clipboard.pauseOwned", {owner: "nixi-otp", expires: 120})`.
- **Dedupe:**
  - the same key again does nothing;
  - a key evicted from the 64, or older than 10 min, counts as new.
- **Coalescing:** three `seen()` calls before the worker turns send one request.
  - A key that arrives **while** `Phone.call` is blocked, held on a `threading.Event`, is sent on the next turn.
  - `seen()` returns at once while the call is blocked.
- **The bound:**
  - the 6th request in a hold is dropped;
  - after `until` passes, requests are allowed again.
- **Unconfirmed requests:** after a `TimeoutError` at t=119 on a hold confirmed to t=120, a new code at t=130 is still
  counted in the same hold. This is Codex's case, with the clock patched.
- **Accounting per outcome:**
  - `NotSent` gives `sent` back and leaves `until` alone;
  - a Flux `RuntimeError` keeps `sent` and leaves `until` alone;
  - each failure kind shows no toast;
  - across all of them, stderr gets exactly one line, and it has no row text.
- **Bad replies:** these claim nothing:
  - `{}`;
  - `{"expires": "x"}`;
  - `{"expires": now - 5}`;
  - a non-dict reply.
- **Session change:** a good reply after `Phone.session` changed shows no toast.
- **When nothing is sent:**
  - Phone off;
  - not connected;
  - a snapshot without `clipboardPauses`.
  - `clipboardPauses: []` is enough to send.
- **The toast:** each confirmed renewal publishes the same toast text again.
- **Detection:**
  - it works with `notify_details` off;
  - it works through `SECRET_LINE` alone;
  - it works on a card with buttons that the shell keeps;
  - it works on a code only in `rich` past 600 characters, or only in a button label.

### `tests/test_inbox.py`

- **Regression for the cut-text leak:** the 120+ character summary with `notify_details` on returns blank
  `summary`/`body`.
- **No change for clean rows:** a row without a code is returned unchanged, with no new fields.

### `tests/test_phone.py`

- **Through the real client:** with the existing `FakeFlux`, `Phone.call("clipboard.pauseOwned", owner=…, expires=120)`
  sends that exact JSON and returns `{"expires": …}`.
- **Still refused:** `clipboard.resumeOwned`, `clipboard.pause` and `clipboard.resume` raise.
- **`Phone.session`:** it rises on each reconnect, not on each snapshot.

### Full suite

```bash
nix develop .#ci -c python3 -B .github/ci/run_tests.py --exclude test_character_fit.py --exclude test_accessories_fit.py
```

This must pass, then the fit tests.

### Runtime on p620 after deploy

1. `flux-cli status --json` shows `clipboardPauses: []`.
2. With takeover on, `notify-send "Your sign-in code" "123456"` shows the toast.
3. `clipboardPauses` then lists `nixi-otp` with an expiry about 120 s out.
4. A second, different code notification within 2 min moves the expiry and updates the toast.
5. After the pause runs out, the list is empty.
