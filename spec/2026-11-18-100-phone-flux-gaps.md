---
status: draft
issue: 100
intent: intent/2026-11-18-100-phone-flux-gaps.md
---

# Spec: use more of Flux from Nixi's phone feature

## Design

Four features. They share one Flux client change and one set of privacy
rules. Line numbers are `origin/main` at `e352682`.

### 0. Shared: the Flux client (`app/phone.py`)

- **`Phone.METHODS`** (`:19-20`) gains exactly `notify.send`, `sms.thread`
  and `notification.reply`. A test asserts the full set, so nothing else
  can slip in.
- **`devices()`** (`:113-130`) adds `fingerprint`, `ip` and `addresses` to
  each row.
- **A new `notifications(device)`** returns the paired device's phone
  notifications from the snapshot. Each row has `id`, `app`, `title`,
  `text`, `time` and `can_reply` (`bool(replyId)`). `replyId` itself and
  `actions` aren't returned.
- **`sms_threads()`** already passes each conversation through
  (`:136-139`). Its `thread` field (`internal/core/sms.go:90`) is used as
  is.

### 1. "Tell my phone" (`notify.send`)

- **Phrases** (`app/quick.py` `_phone`, and new lang `phrases` keys in every
  language file that has the phone phrases):
  - `phone_note`: "tell my phone {text}", "send my phone a note: {text}".
    The text is case-kept and at most 200 characters, like `phone_reply`
    (`:376-385`).
  - `phone_when_done`: "tell my phone when (this is|it's) done", "ping my
    phone when you're done".
  - Neither collides with "tell the X session:", whose regex needs
    `session` (`:364`).
- **Now** (`phone_note`):
  - `phone_choose(name, "share")` picks the device. A "can't" or "offline"
    reply is spoken as today.
  - Nixi calls `notify.send(device, title="Nixi", body=text)`. The text is
    your own words. It isn't scrubbed, but is capped at 200 characters.
  - `not_supported` gives "Update Flux on {name} to get notes".
- **When done** (`phone_when_done`):
  - The quick path runs outside the turn lock (`/api/quick`,
    `app/server.py:8979`), so it works mid-turn.
  - With no turn running (`not ST.lock.locked()`), the reply is "Nothing is
    running right now."
  - Otherwise it sets `PHONE_WHEN_DONE = {"turn": TURN, "device": id,
    "gen": PHONE_GEN, "at": monotonic}`. That's one slot, so a newer
    request replaces it. The reply is "I'll tell {name} when it's done."
  - **The click:** a 📱 button on the page's busy indicator posts
    `/api/phone/when-done` (window token) and does the same.
- **Firing**: in the chat handler's `finally` (`app/server.py:~9527`, after
  `emit(t="done")`), when `PHONE_WHEN_DONE["turn"] == turn`:
  1. Take the slot under `PHONE_LOCK` (consume first).
  2. Drop it if any of these holds:
     - `gen != PHONE_GEN` or `phone_on` is off;
     - it's more than 30 minutes old;
     - the device is no longer paired, or is offline. An offline device
       gets a desktop `note`: "{name} was offline, so I didn't send it".
  3. Otherwise send one generic body from a background thread: "Your agent
     turn finished", "… stopped" or "… failed", by outcome. Never the
     answer or any output.
  4. `NotSent` and `TimeoutError` aren't retried. A timeout gets "I
     couldn't confirm {name} got it".
- **The agent can't send one.** `/api/phone/when-done` needs the window
  token, not `TOOL_TOKEN`. `notify.send` is reachable only from these two
  paths. The agent policy's refusal of `flux-cli` and the socket is
  unchanged.

### 2. The Phone tab (`app/static/index.html`, `phone_status`)

- **`state_info`** and the `phone` bus event (`phone_pub`, `:7207`) add
  `phone_devices`, one row per paired device:
  - `name`, `online`, `last_seen_ago` (`_phone_ago`), and the battery
    `charge` and `charging`;
  - `fingerprint`, formatted `ABCD EF01 2345 6789`;
  - `ip`, the last link's address, shown only in the tab;
  - `hint` when offline: "Not reachable now. Same network, or Tailscale
    on?". It's a check to try, never a diagnosis.

  No numbers, notifications or texts. `phone_status()` stays the one-line
  summary.
- **`renderPhone()`** (`:4159`) lists the rows under the switch, as
  `.note`-style lines. With Phone off or no devices, nothing more is shown.

### 3. A conversation's latest 100 texts (`sms.thread`)

- **Opening it:** each row of the `phone_sms` stage (`phone_read_messages`,
  `:7540`) gets **Open**. The button posts `/api/phone/thread {stage,
  index}`. The server finds the row in the stage it holds (`STAGES.get`),
  never in what the page sends, and calls `sms.thread(device, thread)`.
  The thread is the conversation's `thread` field, stored in the row
  server-side and not sent to the page.
- **The `phone_thread` stage:**
  - up to 100 messages, oldest first, each with name, time and an
    outgoing flag;
  - each body goes through `mail_clean(…, 500)` and `mail_scrub` (the same
    scrubbing as `phone_read_messages`, `:7558`);
  - a **Reply** button reuses the existing `phone_reply` → `phone_draft`
    path;
  - marked `from_phone`, so `phone_reset` closes it (`:7681`).
- **Never spoken**, and `phone_thread` joins the kinds in
  `phone_on_screen()` (`:7073`).

### 4. Answering a phone notification (`notification.reply`)

- **What Nixi adds.** Flux's own desktop notification already carries a
  reply field when the phone allows it (`docs/features.md:364-366`). Nixi
  adds a voice path and a card you can come back to, with the same
  click-to-send rule.
- **Phrases:**
  - `phone_notes` ("show my phone notifications") opens the `phone_notes`
    stage. It lists up to 10 recent notifications per device: app, title,
    and `text` through `mail_clean(…, 300)` and `mail_scrub`. **Reply**
    appears only where `can_reply`.
  - `phone_notify_reply` ("answer {name} on my phone: {text}") matches
    notifications whose title equals `{name}`, case-folded, and that can
    reply. One match opens a draft with the text. Several open the list
    with the text carried. None gives "I don't see a notification from
    {name} you can answer."
- **The draft.** `PHONE_NOTE_DRAFT` mirrors `PHONE_DRAFT` (`:7078-7129`):
  - `{id: token_urlsafe(18), device, nid, app, title, gen, created}`;
  - one at a time;
  - it lives 10 minutes;
  - it's consumed before Flux is called;
  - it's restored only on `NotSent`.
- **Sending** (`POST /api/phone/note-reply {draft, text}`, window token,
  keyed by a click like `phone_send`):
  - Before the call, the server checks the latest snapshot. That device
    must still have a notification with `nid`, and the same `app` and
    `title`. If not, the draft is dropped with "That notification is gone
    from your phone."
  - Then `notification.reply(device, id=nid, message=text)`, with text of
    1–1000 characters.
- **Not spoken.** The `phone_notes` and `phone_note_draft` stages join
  `phone_on_screen()`, are marked `from_phone`, and are cleared by
  `phone_reset`, along with `PHONE_NOTE_DRAFT` and `PHONE_WHEN_DONE`.

### Privacy rules (all four)

- No new text reaches:
  - the status line;
  - `phone_pub`, apart from the device rows above;
  - the plugin feed (`plugins.forget` on reset, as today);
  - logs (only exception type names are printed, as today);
  - agent prompts. Stages are page-only; a stage Run never carries phone
    content.
- Off means off: every new path starts with `CFG.get("phone_on")` and
  `Phone.connected`, and each draft and slot carries `PHONE_GEN`.

### Two desktops

Each desktop has its own slots and drafts. A note is sent only by the
desktop you asked. Both desktops can answer the same notification, with one
click each. That's accepted.

## Alternatives rejected

- **Let the agent send phone notes as a tool.** That breaks "the agent
  can't send one by itself". It also puts model-chosen text on the phone.
- **Put the agent's answer in the "when done" note.** It can hold secrets
  or code.
- **A queued note when the phone is offline.** That's the indefinite
  replay the intent rules out.
- **Show notification reply only through Flux's own popup.** It's there
  already. Nixi's value is the voice path and the card, so both stay.
- **Pass the page's device and number for thread and reply.** That's
  trusting the client. The server keeps them in the stage it holds.
- **`transfer.open` and incoming-file captions, and clipboard pause.**
  Out of scope by the approved intent. Clipboard pause waits on
  olafkfreund/nixarchy-flux#77.

## Risks

- **Flux versions:**
  - An older Flux on the phone answers `notify.send` with `not_supported`.
    That's handled with a spoken line.
  - An older `fluxd` may lack `sms.thread` or `notification.reply`, giving
    a `RuntimeError` like the other calls. It's handled as `phone.failed`.
- **Notification IDs change.** The phone resends notifications on
  reconnect (`docs/features.md:375`), so an ID can change. The check
  before sending drops a draft whose notification is gone. You open a new
  one.
- **The busy-indicator button** is new UI in a crowded spot. The fit
  tests must still pass.
- **Hosts:** p620 and razer, through the usual deploy. Nothing on p510.

## Verification

- **Unit tests** (new `tests/test_phone_flux_more.py`, under
  `_ServerEnv`/`nixi_env`, with a fake `Phone.call` and no socket):
  - the exact `METHODS` set;
  - note now;
  - when-done:
    - armed mid-turn;
    - refused with no turn;
    - fired once on `done`, `stopped` and `failed`, with the generic body;
    - dropped on generation change, age, offline and unpaired;
    - no retry on timeout;
  - the thread:
    - built from the held stage, not the request;
    - scrubbed;
    - closed by `phone_reset`;
  - the notification reply:
    - the draft is single-use;
    - expiry;
    - dropped when the notification is gone or changed;
    - restored only on `NotSent`;
    - text bounds;
  - every new stage kind is in `phone_on_screen()`;
  - the Phone tab rows carry no texts or numbers.
- **Existing phone tests** pass unchanged: `ls tests | grep -i phone`.
- **The full suite** and the fit tests.
- **Live on p620,** with the phone:
  - "tell my phone buy milk" shows on the phone;
  - "tell my phone when this is done" during a turn gives one note at the
    end;
  - the Phone tab shows the device and its fingerprint;
  - **Open** on a conversation shows its thread;
  - "show my phone notifications" lists one, and **Reply** answers it.
