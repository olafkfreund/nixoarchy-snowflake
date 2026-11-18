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

- For each row that passes the key and category checks, Nixi tests the **raw** text: `summary`, `body` and, for cards,
  the `rich` text and button labels, joined as the card gate already does (`:3329`).
  - The test is `Inbox.OTP.search(text) or SECRET_LINE.search(text)`, run **before** the `notify_details` gate blanks
    anything, and whatever `notify_details` says.
  - The display gate (`:3320`, `:3331`) is unchanged.
- On a hit, `rows` calls `CodePause.seen(row_key)`. That only records the key and wakes the worker. No text is stored,
  logged or passed on.
- Rows that `continue` early, such as the shell keeping a card with buttons (`:3333`), are tested before that `continue`.
- Notifications only. `mail_otp` (`:7246`) is untouched.

### `CodePause` state and rules

- `OWNER = "nixi-otp"`: fixed, ASCII, 8 bytes, so it meets Flux's label rules. It carries no notification content.
- `SECS = 120`.
- **Dedupe:** `keys` maps a row key to when it was first seen, keeps at most 64 keys, and drops them after 10 min.
  A key already in `keys` (an update or repeat of the same notification) does nothing.
- **Coalescing:** `seen` sets a flag and an `Event`. The worker sends one request for any number of new keys that
  arrived since its last request.
- **Bound on Nixi's side:** at most 5 requests per continuous hold, so a hold lasts about 10 min at most. A hold counts as
  continuous while Flux's returned `expires` is still in the future. Once 5 are used, new codes do nothing until the
  current hold has expired, and the count resets. Flux's own 1 h cap stays the outer limit.
- **When it asks:** only when `CFG.get("phone_on") is True`, `Phone.connected`, and the snapshot has a `clipboardPauses`
  key. An older Flux has no such key, so Nixi never sends it an unknown method.
- **The call:** `Phone.call("clipboard.pauseOwned", owner=OWNER, expires=SECS)`.
  - `Phone.METHODS` gains `"clipboard.pauseOwned"` only. `resumeOwned`, `pause` and `resume` stay out, so Nixi cannot end
    or shorten any pause, its own included.
- **The reply:** `expires` must be an `int` later than `time.time() + 1`, or it counts as a failure.
  - Near Flux's cap it can be earlier than asked; Nixi keeps the returned value, not its own guess.
  - Errors from `Phone.call` (`NotSent`, `ConnectionError`, `TimeoutError`, `RuntimeError` carrying `too_many`,
    `bad_params` or anything else, `ValueError`) count as a failure too.
  - A failure claims nothing and shows nothing. The first failure in a process prints one line to stderr, with the
    exception type only. There is no retry; the next new code tries again.
- **Phone off, Flux down, `fluxd` restart:** Nixi does nothing extra. A pause it already set runs out by itself.
  - After a `fluxd` restart the pause is gone; Nixi does not restore it. A later new code starts a new one.

### What you see

- After the **first** successful request of a hold, one toast: `BUS.pub(t="toast", text=lang.t("phone.clip_paused"))`.
- Renewals in the same hold show nothing new, so the line is never repeated. This is the "updates instead of repeating"
  of decision 3 in its smallest form; an updating line would need a new page element.
- New string `phone.clip_paused` in `app/lang/en.json`, `nb.json` and `pl.json`:
  - en: "Clipboard sharing paused for the code"
  - nb: "Deling av utklippstavlen er satt på pause for koden"
  - pl: "Udostępnianie schowka wstrzymane na czas kodu"

### Agent boundary

- No HTTP route or tool endpoint is added. `CodePause` is reachable only from `Inbox.rows`.
- The `flux-cli` policy at `app/server.py:962` is unchanged.

### Docs

- `docs/GUIDE.md:163`: replace "pausing the clipboard from Nixi" with a short paragraph covering:
  - what triggers the pause, and that it lasts 2 min;
  - that it is a mitigation, with its limits (only while notifications are taken over; a copy made before the
    notification can still go out; a send already past Flux's check);
  - what a pause costs (copies made during it are not shared and stay out of Flux history; manual sends still work);
  - that a `fluxd` restart drops it.

### nixos_config

- After the Nixi PR merges: one PR bumps `nixarchy-flux` from `6eb6347` to `8267293` (the #77 merge) and
  `nixi-companion` to the #105 merge.
- Deploy to p620 and razer. Both restart `fluxd`. p510 doesn't run Flux.

## Alternatives rejected

- **Reuse the display gate.** It stops early when `notify_details` is off, which is the default (`:262`).
- **`resumeOwned` on dismiss.** Rejected by decision 2.
- **A per-hold random owner label.** It would fill Flux's 8-owner table on repeated holds and buys nothing: labels are
  not identity.
- **Calling inline from `Inbox.tick`.** `Phone.call` waits up to 10 s and would stall the 1 s lease loop.
- **Probing by calling `pauseOwned` on any Flux.** The `clipboardPauses` snapshot key says the same without an error
  on old builds.
- **A setting.** Not needed. The feature follows the Phone switch.
- **Mail codes.** Rejected by decision 4.

## Risks

- **False positives.** `OTP` also matches ordinary text such as "your PIN 1234 reminder", and `SECRET_LINE` matches
  some technical notifications. Either one pauses sharing for 2 min. The 5-request bound limits the cost. Accepted.
- **False negatives.** Codes the regexes miss are not paused. It is a mitigation.
- **A Flux version with `clipboardPauses` but different semantics.** Only the #77 build has that key.
- **On both p620 and razer:** the flux bump changes Flux from `6eb6347` to `8267293`. That includes other merged
  Flux work, which I will list in the nixos_config PR.

## Verification

- **New `tests/test_code_pause.py`**, run under `nixi_env`, with a fake `Phone`, covering:
  - a code row calls `pauseOwned` once with exactly `{owner, expires: 120}`;
  - the same key again does nothing;
  - 3 keys arriving together send one request;
  - the 6th request in a hold is refused, and is allowed again after the hold expires;
  - nothing is sent with Phone off, when not connected, or with no `clipboardPauses` key;
  - each failure kind claims nothing, shows no toast and logs at most one line;
  - a past `expires` claims nothing;
  - the toast appears once per hold;
  - detection works with `notify_details` off.
- **`tests/test_inbox.py`:**
  - detection runs before the button-card `continue`;
  - the published rows are unchanged (no new fields).
- **`tests/test_phone.py`:** `clipboard.resumeOwned`, `clipboard.pause` and `clipboard.resume` still raise.
- **Full suite:** `nix develop .#ci -c python3 -B .github/ci/run_tests.py --exclude test_character_fit.py --exclude test_accessories_fit.py`
  passes, then the fit tests.
- **Runtime on p620 after deploy:**
  - `flux-cli status --json` shows `clipboardPauses: []`;
  - a test notification with a code, sent with `notify-send "Your sign-in code" "123456"` while takeover is on, shows the
    toast;
  - `clipboardPauses` lists `nixi-otp` with an expiry about 120 s out;
  - after 2 min the list is empty.
