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
quiet behaviour. A review against nixarchy-flux (2026-11-18) found that
Flux already offers more that Nixi leaves unused:

1. **No way to reach you on the phone.** When you step away from p620 or
   razer, Nixi can't tell you a build finished or a reminder is due. Flux
   has `notify.send` (`docs/ipc.md:232`).
2. **Files the phone sends go unnoticed.** Nixi tracks only transfers it
   started. Flux marks each transfer `dir: "in"|"out"`
   (`internal/core/share.go:79`) and can open a finished incoming one
   (`transfer.open`, `docs/ipc.md:223`).
3. **A one-time code can reach the phone.** Nixi already spots secrets and
   one-time codes in notifications (`app/server.py:3074`, `:3203`) and hides
   them on screen. Flux's clipboard sync keeps running, so a copied code
   goes to the phone. Flux has `clipboard.pause`/`resume`
   (`docs/ipc.md:442-446`).
4. **The Phone tab says little.** It shows one status line, though Nixi
   already holds each device's name, battery, last seen and online state.
5. **Only the latest text per conversation.** Flux returns a thread's last
   100 messages (`sms.thread`, `docs/ipc.md:460`).
6. **Phone notifications can't be answered from the desk.** Flux has
   `notification.reply` (`docs/ipc.md:230`).
7. **An offline phone gives no hint.** On razer away from home the phone
   is usually just not on the same network, and Nixi doesn't say so.

## Proposed outcome

- **"Tell my phone"**: you can send yourself a short note on the phone, by
  voice or a click, and ask for one when the current agent turn ends.
- **Incoming files** show a caption, "Pixel sent photo.jpg", with
  **Open** and **Show in folder**. Nothing opens by itself.
- **Clipboard sync pauses** while Nixi is holding back a secret or
  one-time code, and resumes by itself afterwards.
- **The Phone tab** lists each device: name, online or last seen, battery,
  and its Flux fingerprint.
- **A whole SMS thread** can be read on screen, behind the same privacy
  gate as reading texts today.
- **A phone notification that offers a reply** can be answered from the
  desk through a click-only draft, as texts are today.
- **An offline phone** says why it's likely offline: "not on this network:
  is Tailscale on?" when the device has a Tailscale address among Flux's
  extra `addresses` (`docs/ipc.md:163`) and the last link wasn't through
  one, or "last seen 2 h ago" otherwise.

## Affected users and systems

- nixoarchy-snowflake: `app/phone.py` (the method allowlist, snapshot
  readers), `app/server.py` (phone handlers, cards, quick phrases via
  `app/quick.py`, the notification path), `app/static/index.html` (Phone
  tab), `docs/GUIDE.md`, tests.
- Flux (nixarchy-flux): used as is. No change to Flux.
- p620 and razer, through the usual deploy. Both run their own `fluxd`.

## Constraints

- **Flux stays in charge of security.** Nixi never calls `settings.set`,
  `pair.*`, remote input or desktop, herdr control, terminals, Browse PC or
  the SSH key, and never adds approve buttons for sudo/ssh approvals. The
  method allowlist grows only by the methods named here.
- **Anything that reaches another person needs your click.** A
  notification reply goes through a single-use draft, like `sms.send`
  (`phone_draft`/`phone_send`). A note to your own phone (`notify.send`)
  needs a voice command or a click; the agent can't send one by itself, and
  the agent policy keeps refusing `flux-cli` and the socket.
- **Received files are untrusted.** Never opened, previewed or parsed
  without a click. Opening uses `transfer.open`, so Flux's own rules
  apply.
- **A pause must never stick.** Flux keeps `clipboard.pause` across a
  `fluxd` restart (`docs/ipc.md:62`), so Nixi resumes on a timer, when the
  secret is gone, when Phone is switched off and when Nixi stops. A pause
  Nixi didn't start is never resumed by Nixi.
- **Privacy as today.** Thread text, notification text and numbers stay out
  of logs, the status line, the plugin feed and anything spoken unless the
  existing gates allow it (`notify_details`, the on-screen check,
  `SECRET_LINE`/OTP scrubbing).
- **Off means off.** With `phone_on` false nothing new runs, and switching
  it off clears new state (drafts, captions, pause) as `phone_reset` does
  today.
- Works the same with the phone paired to both p620 and razer.

## Open questions

1. **"Tell my phone when this is done":** offer it for an agent turn only,
   or also for a shell command (the existing `commandDone` hook)?
   Recommendation: agent turns and `commandDone`, opt-in each time, never
   automatic.
2. **Clipboard pause trigger:** only Nixi's own secret and one-time-code
   detection, or also when a password manager copies? Recommendation:
   Nixi's own detection only, for 60 s or until the notification goes; a
   password manager is out of scope.
3. **Notification reply by voice:** dictate the reply text, or only type
   it in the draft? Recommendation: either, but the send is always the
   click.
4. **Incoming files:** caption only, or also say "Pixel sent a photo"?
   Recommendation: caption, spoken only when `notify_speak` includes
   `download`.
