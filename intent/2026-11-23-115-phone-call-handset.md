---
status: approved
issue: 115
author: olafkfreund
---

# Intent: take phone calls on the host with a ringing retro handset

## Problem

When the phone rings, Nixi says who is calling (`phone_on_call`,
`app/server.py:7993`) and goes quiet while the call lasts
(`phone_call_sync`, `:7974`). That is all he can do. To answer, the owner has
to find the phone, and the call then runs on the phone, away from the desk's
speakers and mic.

Flux already posts a plain desktop notification while the phone rings
(`nixarchy-flux` `internal/core/telephony.go:196-206`). Nothing next to Nixi
can be pressed for a call. A missed call ends up as a small card title
("Missed call from …").

What exists today:

- Flux sends `ringing` / `talking` / cancel events with the number and the
  contact name, sometimes in two `ringing` packets (`telephony.go:74-206`).
  Nixi reads them through `app/phone.py`. Flux keeps one call per phone with
  no call id, and its `since` is when ringing started, not when the call was
  answered (`telephony.go:135-158`).
- The Flux Android app (minSdk 29, targetSdk 36) can read call state, the
  call log and contacts. It cannot answer or hang up. Android's
  `acceptRingingCall()` / `endCall()` are deprecated, take no call id
  (`endCall()` can end the active call instead of rejecting a waiting one),
  and are restricted for apps that are not the phone's dialer.
- An ordinary Android app cannot carry mobile-call audio: Android keeps call
  audio away from apps. The way a computer carries a call's audio is
  Bluetooth hands-free (HFP), with the computer acting as the phone's
  headset.
- p620 and razer both have a Bluetooth controller and PipeWire 1.6.11.
  PipeWire runs `org.pipewire.Telephony` on the user bus (seen on p620). It
  offers its own `org.pipewire.Telephony.*` interfaces and oFono-compatible
  ones (`org.ofono.Manager` is live), and can answer, reject and hang up a
  call and give the caller's number when the host is the phone's
  hands-free unit (WirePlumber role `hfp_hf`). The phone is not paired with
  either host over Bluetooth today.
- When the phone starts ringing, Nixi stops speaking and cancels a listen.
  He does that once, as the ringing starts. An announcement he starts after
  that point is not cut off when the call is answered.

## Proposed outcome

- A call rings: next to Nixi a small, old-style candybar mobile phone appears,
  shaking and ringing. Its screen, lit in the theme's colours, shows the
  contact name, the number when there is no contact, or "Unknown" for a
  withheld number.
- When the host carries the call's audio, the phone's green button answers
  and its red button rejects. With the call answered, the screen shows the
  name and a timer that starts at the answer, and the red button hangs up.
- An answered call's audio runs on the host's speakers and mic, with echo
  cancellation so the caller doesn't hear themselves. Nixi stops listening
  and speaking for the whole call, including anything he was still saying
  when it was answered.
- Side buttons on the handset turn the call volume up and down, and a mute
  button mutes the desk mic for the caller (the screen shows it).
- While it shakes, the host plays a short old-phone ring of our own, quiet
  enough not to compete with the phone, and off in quiet times.
- When the phone isn't linked to the host over Bluetooth, the handset still
  rings and shows the caller, and its green and red buttons answer and reject
  through Flux. The audio then stays on the phone, and the screen says so
  ("Answer on phone"). A Flux button only acts on the one call the handset
  shows: with a second call waiting, or when Flux can't tell which call it
  is, the buttons are disabled instead of guessing.
- When the call ends, from either side, the handset shows "Call ended" for a
  moment and leaves. A call nobody answers becomes the missed-call card it is
  today, with the name readable. When the handset can't tell how a call
  ended, for example because the link dropped, it says nothing it doesn't
  know.
- The handset is our own drawing in the spirit of a late-90s candybar phone.
  It uses no real brand, logo or product shape.

## Affected users and systems

- The owner on p620 and razer. p510 has no companion and is not affected.
- `nixoarchy-snowflake`: the page (`app/static/index.html`), the server's
  phone code (`app/server.py`, `app/phone.py`), and the language files.
- `nixos_config`: PipeWire/WirePlumber Bluetooth roles and echo cancellation
  on p620 and razer, and pairing the phone with each host.
- `nixarchy-flux`: the Android app answers and rejects a ringing call (a new
  `ANSWER_PHONE_CALLS` permission the owner grants), and the daemon offers
  those actions on its socket.

## Constraints

- Answering and hanging up need an explicit click on the handset. No voice
  command and no automatic answer in this task.
- Phone features stay off until the owner turns Phone on (`phone_on`), as
  today. The buttons act only on a phone the owner paired.
- Call audio never leaves the host: no recording, no transcription, nothing
  sent to the agent or to ElevenLabs.
- Nixi's wake word and push-to-talk are off for the whole call, so a caller
  over the speakers can't wake him. They come back only when the call has
  ended, even if Flux drops while Bluetooth still carries the call.
- The Pixel Buds and other headsets keep working. A call answered on the
  phone or on the buds is left alone. Pairing the phone with a host must not
  pull call audio off the buds.
- The phone's media (music, videos) does not start playing on the desk
  speakers because it is paired.
- Two hosts can be awake at once. Only the host that holds the phone's
  hands-free link offers answer. The other may show the caller.
- The handset and its numbers follow the existing quiet rules: nothing while
  the desk is locked. The Phone tab and status line keep their "never
  numbers" rule (`app/server.py:7915`, `:7930`).
- Changes in `nixos_config` follow that repo's rules: deploy from `main`,
  announce on the agent bus, and never touch p510.
- The page stays readable at the page zoom (#109) and honours reduced motion:
  no shaking, a still ringing state instead.
- Out of scope: outgoing calls, call waiting (a second call while one is
  active), and app calls (WhatsApp, Signal).

## Decisions (owner, 2026-11-23)

1. **Audio path:** Bluetooth hands-free. p620 first; razer once audio, echo,
   the Pixel Buds and both hosts in range are tested on p620.
2. **Without Bluetooth:** answer and reject through Flux as well, audio on the
   phone, with the one-call guard above.
3. **Numbers on screen:** the number shows for a caller who isn't a contact,
   desk unlocked only.
4. **In-call extras:** mute and volume buttons.
5. **Ringtone:** a short old-phone ring on the host while the handset shakes.

## Open questions

- Should Flux's own desktop call notification stay while the handset is up?
  The spec will propose hiding it while Nixi shows the handset.
