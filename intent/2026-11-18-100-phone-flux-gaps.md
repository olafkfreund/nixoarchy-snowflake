---
status: draft
issue: 100
author: olafkfreund
---

# Intent: use more of Flux from Nixi's phone feature

## Problem

Nixi's phone feature is a thin client of Flux's local daemon: it talks to
`fluxd`'s Unix socket and allows 8 methods (`app/phone.py:19-20`). Flux
does the pairing, encryption and phone apps. Nixi adds voice, cards and
quiet behaviour. A review against nixarchy-flux (2026-11-18) found Flux
offers more that Nixi leaves unused:

1. **No way to reach you on the phone.** When you step away from p620 or
   razer, Nixi can't tell you an agent turn finished. Flux has
   `notify.send` (`docs/ipc.md:232`).
2. **The Phone tab says little.** It shows one status line. Nixi already
   holds each device's name, battery, last seen and online state
   (`app/phone.py:113-130`, `phone_board` `app/server.py:7336`), and Flux's
   snapshot adds the last link's address and extra addresses
   (`docs/ipc.md:163`).
3. **Only the latest text per conversation.** Flux returns a
   conversation's latest 100 messages (`sms.thread`, `docs/ipc.md:460`).
4. **Phone notifications can't be answered from the desk.** Flux has
   `notification.reply` (`docs/ipc.md:230`).

Two items from the review are **not** taken up here:

- **Files the phone sends.** Flux already shows a desktop notification for
  each received file with **Open** and **Show in folder**
  (`internal/core/share.go:513`), which Nixi's notification takeover
  already shows. A Nixi caption would duplicate it.
- **Pausing clipboard sync while a one-time code is on screen.** Flux's
  pause is one boolean with no owner, "the last call wins"
  (`docs/ipc.md:452`), and it survives a `fluxd` restart (`:62`). Nixi can't
  both make sure its pause never sticks (a crash defeats its timer) and
  never undo a pause you set yourself. Detection is also late and partial:
  it runs only while Nixi takes notifications over (`app/server.py:3142`),
  and a send that passed its check can still go out (`docs/ipc.md:446`).
  This needs a Flux change first (a pause with an owner and an expiry), as
  its own Flux issue.

## Proposed outcome

- **"Tell my phone when this is done"**: on an agent turn you can ask
  Nixi, by voice or a click, to send your phone one short note when that
  turn ends. You can also send yourself a note now ("tell my phone: buy
  milk").
- **The Phone tab** lists each device: name, online or last seen, battery,
  Flux's fingerprint, and the last link's address. When a device is
  offline it shows a troubleshooting hint ("not reachable: same network or
  Tailscale?"). It says *may*, not *why*: Flux's fields can't tell the
  cause.
- **A conversation's latest 100 texts** can be read on screen.
- **A phone notification that offers a reply** can be answered from the
  desk with a click-only draft, as texts are today. You can type or dictate
  the reply. Sending is always the click.

## Affected users and systems

- nixoarchy-snowflake: `app/phone.py` (the method allowlist, snapshot
  readers), `app/server.py` (phone handlers, stages, drafts, the
  agent-turn end), `app/quick.py` (`_phone` phrases),
  `app/static/index.html` (Phone tab), `docs/GUIDE.md`, tests.
- Flux: used as is.
- p620 and razer, each with its own `fluxd`, through the usual deploy.

## Constraints

- **Flux stays in charge of security.** Nixi never calls `settings.set`,
  `pair.*`, `addresses.*`, remote input or desktop, herdr control,
  terminals, Browse PC or the SSH key. It adds no approve buttons for
  sudo/ssh. The method allowlist grows by exactly `notify.send`,
  `sms.thread` and `notification.reply`.
- **A note to your phone is bound and bounded.** A "when done" request
  belongs to one device, one agent turn and one send. It's cancelled when
  Phone is switched off, Nixi restarts, the device disappears, or it's
  over 30 minutes old. Its text is generic ("Nixi: your agent turn
  finished"), never the agent's answer or command output. An uncertain
  send (a socket timeout, `app/phone.py:192`) is never retried. The agent
  can't send one by itself, and the agent policy keeps refusing
  `flux-cli` and the socket.
- **A reply draft is bound to its notification.** It names the device,
  the notification ID and the app/sender you saw. It's single-use and
  expires like an SMS draft (`phone_draft`/`phone_send`,
  `app/server.py:7096-7129`). It's dropped when that notification goes
  away or changes. It's restored only when the send certainly wasn't
  written, as today (`:7117`).
- **New views stay private.** Thread text, notification text and numbers:
  - show only on screen. Nothing is spoken; the new stages join
    `phone_on_screen()` (`app/server.py:7073`), including draft pickers.
  - stay out of agent prompts, the plugin feed, the status line and logs;
  - are scrubbed (`SECRET_LINE`/OTP) before they're published;
  - are cleared when Phone is switched off (`phone_reset`).
- **Off means off.** With `phone_on` false nothing new runs.
- **Two desktops, one phone.** p620 and razer act independently. A note is
  sent only by the desktop where you asked. Two desktops answering the
  same notification is an accepted limitation: each draft needs its own
  click.

## Open questions

1. **"When done" for shell commands too** (the `commandDone` hook)?
   Recommendation: not now. Agent turns first, `commandDone` later once a
   command can be identified and bound the same way.
2. **The Flux clipboard-pause change:** open the Flux issue now, or leave
   it? Recommendation: open it, with the owner-and-expiry design above, and
   come back to Nixi's side after.
