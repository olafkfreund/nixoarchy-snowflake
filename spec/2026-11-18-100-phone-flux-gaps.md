---
status: approved
issue: 100
intent: intent/2026-11-18-100-phone-flux-gaps.md
---

# Spec: use more of Flux from Nixi's phone feature

## Design

The work is four features, plus one Flux-client change and one set of
lifecycle and privacy rules shared by all of them. Line numbers refer to
`origin/main` at `e352682`.

### 0. Shared

**The Flux client (`app/phone.py`)**

- **`Phone.METHODS`** (`:19-20`) gains exactly `notify.send`, `sms.thread`
  and `notification.reply`. A test asserts the full set.
- **`devices()`** (`:113-130`) adds `fingerprint` and `ip` to each row.
- **New `notifications(device)`** returns the paired device's phone
  notifications from the snapshot:
  - each row is `{id, app, title, text, time, can_reply}`, with
    `can_reply = bool(replyId)`;
  - each row also gets `rev`, the sha256 of `app`, `title`, `text` and
    `replyId`, joined with NULs. Flux replaces a notification under the
    same ID when its text or reply target changes
    (`internal/core/notifications.go:257-277`), so `rev` catches that;
  - `replyId` and `actions` themselves never leave the module.
- **`sms_threads()`** (`:136-139`) already passes each conversation's
  `thread` field through (`internal/core/sms.go:90`).

**The device chooser.** Every target goes through `phone_choose`
(`app/server.py:7384`) with a new capability, `note`:
- it means "paired and online", with no plugin needed. `notify.send` is
  checked by Flux (`internal/core/telephony.go:255`), and `share` is the
  wrong gate;
- several online devices with no name given get the existing
  `phone_pick_card` (`:7529`), never a silent first pick. The 📱 button
  behaves the same.

**Lifecycle: off means off, for asynchronous work too**
- Every path checks `CFG.get("phone_on")`, `Phone.connected` and
  `PHONE_GEN` at entry.
- It checks `PHONE_GEN` again under `PHONE_LOCK`:
  - right before each `Phone.call` that sends (`notify.send`,
    `notification.reply`);
  - right before each `STAGES.put`/`BUS.pub` of phone content (the
    `sms.thread` reply, which can take up to 8 s, `sms.go:263`).
- `phone_reset` increments `PHONE_GEN` under `PHONE_LOCK` before
  `Phone.stop()` (as today, `:7646-7690`). So once reset holds the lock,
  no new send starts and no late reply is shown. A socket write that
  already started can't be recalled. That's the same accepted limit as
  `sms.send` today.
- Tests block each operation, then switch Phone off and on, and assert
  nothing is sent or shown.

**Privacy, for every new view**
- **What's scrubbed:** every phone-derived field that's shown, meaning
  names, app, title, bodies and draft headers. Each goes through
  `mail_clean` plus `mail_scrub`, as `phone_read_messages` does (`:7558`).
- **New stage kinds:** `phone_thread`, `phone_notes` and
  `phone_note_draft`.
  - All three join `phone_on_screen()` (`:7073`), so they're never spoken.
  - All three are marked `from_phone`, so `phone_reset` closes the current
    and previous views (`:7681`).
- **The page's caption fallback** `stageText()` (`index.html:3381`)
  returns `''` for any `from_phone` stage, not only `mail` and
  `phone_pick`. A stage that can't show never leaks its title into the
  caption.
- **Nowhere else:**
  - nothing new reaches the status line, the plugin feed or the logs (only
    exception type names, as today);
  - `phone_pub` gains only the device rows in §2;
  - agent prompts never see phone content: stages are page-only.
- **Endpoints:** every new one needs the window token. A test asserts that
  `TOOL_TOKEN` is refused on each (route check `:8641`).

### 1. "Tell my phone" (`notify.send`)

**Parsing** (`app/quick.py`)
- The new phrases are parsed where `phone_reply` is (`:376-385`), on the
  case-kept text and before the 120-character guard (`:386`). The order
  is fixed:
  1. **`phone_when_done`**, exact phrases: "tell my phone when (this
     is|it's) done", "ping my phone when you're done", plus each
     language's own.
  2. **`phone_note`**: "tell my phone {text}", "send my phone a note:
     {text}". The text is case-kept, at most 200 characters, and
     non-empty.
- "tell the X session:" (`:364`) needs `session`, so it doesn't collide.
- Tests: the overlap ("tell my phone when this is done" arms; it doesn't
  send the text "when this is done") and a 200-character mixed-case body.

**Now** (`phone_note`)
- Choose the device (§0). Under the `PHONE_GEN` recheck, call
  `notify.send(device, title="Nixi", body=text)`.
- The text is your own words, so it isn't scrubbed.
- `not_supported` answers "Update Flux on {name} to get notes". A timeout
  answers "I couldn't confirm {name} got it", with no retry.

**When done: an explicit active-turn identity**
- **One lock, `WATCH_LOCK`** (it already guards `TURN`, `:9488`):
  - the chat handler sets `ST.active_turn = turn` where it increments
    `TURN`;
  - in its `finally` (`:~9527`) it reads, clears and consumes the
    completion slot, then sets `ST.active_turn = None`.
- **Arming** (`/api/phone/when-done`, or the phrase through
  `/api/quick`):
  - Choose the device first, outside the lock.
  - Then, under `WATCH_LOCK`: if `ST.active_turn is None`, the reply is
    "Nothing is running right now." Otherwise store
    `PHONE_WHEN_DONE = {"turn": ST.active_turn, "device": id, "gen":
    PHONE_GEN, "at": monotonic}`.
  - There's one slot, and a newer request replaces it.
  - A request in the few milliseconds between the lock and `TURN`'s
    increment sees no active turn and is refused, never bound to the old
    turn.
- **Firing** (in the `finally`, with the slot consumed under
  `WATCH_LOCK`):
  - Drop it if any of these holds:
    - `gen != PHONE_GEN` or Phone is off;
    - it's older than 30 minutes;
    - the device isn't paired or isn't online. An offline device gets the
      desktop note "{name} was offline, so I didn't send it".
  - Otherwise, a background thread rechecks `PHONE_GEN` (§0) and sends
    one generic body by outcome ("Your agent turn finished", "… stopped",
    "… failed"). The body is never the answer or any output.
  - `NotSent` and `TimeoutError` are never retried.
- **The device disappears.** `phone_state` (`:7296`) drops the slot when
  a snapshot shows its device no longer paired. A device that is unpaired
  and paired again can't receive it.
- **The 📱 button** sits on the page's busy indicator and posts
  `/api/phone/when-done` (window token).
- **The agent can't send.** `notify.send` is reached only by these paths,
  all of which need the window token. The agent policy's refusal of
  `flux-cli` and the socket is unchanged.

### 2. The Phone tab

- `state_info` and `phone_pub` (`:7207`) add `phone_devices`, one row per
  paired device:
  - `name` (scrubbed), `online` and `last_seen_ago` (`_phone_ago`);
  - battery `charge` and `charging`;
  - `fingerprint`, formatted `ABCD EF01 2345 6789`;
  - `ip`, the last link's address;
  - when offline, `hint`: "Not reachable now. Same network, or Tailscale
    on?". It's a check to try, never a diagnosis.
- No numbers, notifications or texts. `phone_status()` stays the one-line
  summary.
- `renderPhone()` (`index.html:4159`) lists the rows under the switch.
  With Phone off or no devices, it shows nothing more.

### 3. A conversation's latest 100 texts (`sms.thread`)

**Opening a thread**
- Each `phone_sms` row (`:7540`) gets **Open**, which posts
  `/api/phone/thread {stage, index}`.
- The server finds the row in the stage it holds (`STAGES.get`), with
  `device` and `thread` kept server-side and never sent to the page. It
  then calls `sms.thread(device, thread)`.

**The `phone_thread` stage**
- Before the stage is shown, `PHONE_GEN` is checked again (§0).
- It shows up to 100 messages, oldest first.
- Each message's name and body are scrubbed (§0), and the body is cut to
  500 characters.
- Each message is marked outgoing or not.
- **Reply** reuses `phone_reply` → `phone_draft` (`:7078-7099`).

### 4. Answering a phone notification (`notification.reply`)

**What Nixi adds.** Flux's own desktop notification already has a reply
field when the phone allows it (`docs/features.md:359`). Nixi adds a voice
path and a card you can come back to. Sending is still a click.

**Phrases**
- **`phone_notes`** ("show my phone notifications") opens `phone_notes`:
  - up to 10 recent notifications per device: app, title, and text cut to
    300 characters, all scrubbed;
  - **Reply** where `can_reply`.
- **`phone_notify_reply`** ("answer {name} on my phone: {text}") is parsed
  like `phone_reply`. It matches reply-capable notifications whose title
  equals `{name}` (case-folded):
  - one match opens the draft with the text filled in;
  - several open the list, carrying the text;
  - none gives "I don't see a notification from {name} you can answer".

**The draft.** `PHONE_NOTE_DRAFT` follows `PHONE_DRAFT` (`:7078-7129`):
- It's `{id: token_urlsafe(18), device, nid, rev, app, title, gen,
  created}`, one at a time, and lives 10 minutes.
- It's restored only on `NotSent`.

**Sending** (`POST /api/phone/note-reply {draft, text}`, window token,
`keyed` click as `phone_send`)
- Under `PHONE_LOCK`, the server takes the draft. It must match the id,
  generation and age, and the latest snapshot must still hold a
  notification with that `nid` and the **same `rev`**. On a match it
  consumes that exact draft. On a mismatch it drops the draft and answers
  "That notification changed or is gone. Open it again".
- Then it sends `notification.reply(device, id=nid, message=text)`, with
  text of 1–1000 characters, after the `PHONE_GEN` recheck.

> [!WARNING]
> **Remaining limit, accepted at approval (2026-11-18).** Flux takes the reply target from the
> notification ID at the moment it handles the call
> (`internal/core/notifications.go:488`), and `notification.reply` accepts
> no expected revision (`internal/core/api.go:478`). A change on the phone
> in the moments between Nixi's check and Flux's lookup can't be caught
> from Nixi. Nixi catches every change it can see. The full guarantee
> needs a Flux change, a `notification.reply` with an expected revision,
> filed with olafkfreund/nixarchy-flux#77's follow-up.

### Two desktops

Each desktop keeps its own slots and drafts. A note is sent only by the
desktop where you asked. Both desktops can answer the same notification,
with one click each. That's accepted.

## Alternatives rejected

- **An agent tool that sends phone notes.** It breaks "the agent can't send
  one by itself" and puts model-chosen text on the phone.
- **The agent's answer in the "when done" note.** It can hold secrets or
  code.
- **Queueing a note for an offline phone.** That's the indefinite replay
  the intent rules out.
- **Binding the turn by reading `ST.lock.locked()` and `TURN`.** That
  races with turn start and end. The explicit `active_turn` under
  `WATCH_LOCK` replaces it.
- **Binding a reply draft to only ID, app and title.** Flux replaces the
  content under the same ID, so `rev` is needed.
- **Trusting the page's device, number or thread.** The server keeps them
  in the stage it holds.
- **Gating notes on `share`.** That's the wrong capability.
- **Out of scope by the approved intent:** `transfer.open` captions and
  clipboard pause (waiting on olafkfreund/nixarchy-flux#77).

## Risks

- **Older Flux.** An old Android app answers `notify.send` with
  `not_supported`, which gets a spoken line. An old `fluxd` without
  `sms.thread` or `notification.reply` gives a `RuntimeError`, handled as
  `phone.failed`.
- **The phone resends its notifications on reconnect**
  (`docs/features.md:374`). An ID can change, and then the `rev`/ID check
  drops the draft.
- **The 📱 button** is new UI in a crowded spot. The fit tests must pass.
- **The remaining notification-reply window** (the warning above) is a
  known limitation until Flux supports an expected revision.
- **Hosts:** p620 and razer, through the usual deploy. Nothing on p510.

## Verification

**Unit tests** go in `tests/test_phone_flux_more.py`, under
`_ServerEnv`/`nixi_env`, with a fake `Phone.call` and no socket:

- **Methods:** the exact `METHODS` set.
- **Parsing:** "when done" takes precedence over a note; a 200-character
  mixed-case body is kept as typed.
- **A note now:** the device is chosen; with several devices, the pick
  card appears; `not_supported`; a timeout isn't retried.
- **When done:**
  - it's refused with no active turn, including during turn start;
  - armed mid-turn, it fires once each on `done`, `stopped` and `failed`,
    with the generic body;
  - arming at the same moment as a finishing turn ends with neither a lost
    slot nor a double send;
  - it's dropped on a generation change, at 30 minutes, when offline, and
    when the device is unpaired, including unpaired and then paired again;
  - a disable and re-enable while the send is blocked sends nothing.
- **A thread:**
  - built from the held stage, never from the request;
  - names and bodies scrubbed;
  - a late reply after Phone is switched off isn't shown;
  - closed by `phone_reset`.
- **A notification reply:**
  - the draft is single-use: parallel clicks send once;
  - it expires;
  - it's dropped when its notification is gone or changed (`rev`);
  - it's restored only on `NotSent`;
  - text length is bounded.
- **Privacy:**
  - the new kinds are in `phone_on_screen()`;
  - `stageText` gives `''` for `from_phone` stages;
  - the Phone tab rows carry no numbers or texts;
  - `TOOL_TOKEN` is refused on every new endpoint.

**Then:**
- the existing phone tests, unchanged (`ls tests | grep -i phone`);
- the full suite and the fit tests.

**Live on p620, with the phone:**
- a note now;
- "when done" during a turn gives one note at its end;
- the Phone tab shows the device and its fingerprint;
- **Open** shows a thread;
- **Reply** answers a notification.
