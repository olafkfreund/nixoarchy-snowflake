---
status: draft
issue: 115
author: olafkfreund
---

# Intent: take phone calls on the host with a ringing retro handset

## Problem

When the phone rings, Nixi says who is calling (`phone_on_call`,
`app/server.py:7993`) and goes quiet while the call lasts. That is all he can
do. To answer, the owner has to find the phone, and the call then runs on the
phone, away from the desk's speakers and mic.

On screen there is nothing to see or press for a call. A missed call is a small
card title ("Missed call from …").

What exists today:

- Flux (`nixarchy-flux`) sends `ringing` / `talking` / cancel events with the
  number and the contact name (`internal/core/telephony.go`). Nixi reads them
  through `app/phone.py`.
- The Flux Android app can read call state and contacts. It cannot answer or
  hang up.
- An ordinary Android app cannot carry mobile-call audio over the network:
  Android keeps call audio away from apps. The way a computer can carry the
  call's audio is Bluetooth hands-free (HFP), with the computer acting as the
  phone's headset.
- p620 and razer both have a Bluetooth controller and PipeWire 1.6.11.
  PipeWire already runs `org.pipewire.Telephony` on the user bus, an
  oFono-compatible API that can answer and hang up a call and give the
  caller's number when the host is the phone's hands-free unit. The phone is
  not paired with either host over Bluetooth today.

## Proposed outcome

- A call rings: next to Nixi a small, old-style candybar mobile phone appears,
  shaking and ringing. Its screen, lit in the theme's colours, shows the
  contact name, or the number when there is no contact.
- The phone's green button answers and its red button rejects. With the call
  answered, the screen shows the name and a running call timer, and the red
  button hangs up.
- An answered call's audio runs on the host's speakers and mic. Nixi stops
  listening and speaking for the whole call, so he neither hears nor talks
  over it.
- When the call ends, from either side, the handset shows "call ended" for
  a moment and leaves. A call nobody answers becomes the missed-call card it
  is today, with the name readable.
- The handset is our own drawing in the spirit of a late-90s candybar phone.
  It uses no real brand, logo or product shape.
- When the phone is not connected to the host over Bluetooth, the handset
  still rings and shows the caller. Its buttons work through Flux, with the
  audio staying on the phone, and the handset says so.

## Affected users and systems

- The owner on p620 and razer. p510 has no companion and is not affected.
- `nixoarchy-snowflake`: the page (`app/static/index.html`), the server's
  phone code (`app/server.py`, `app/phone.py`), and the language files.
- `nixarchy-flux`: the Android app (answer and hang up) and the daemon's
  socket methods.
- `nixos_config`: PipeWire/WirePlumber Bluetooth roles (the hands-free role)
  on p620 and razer, and pairing the phone with each host.

## Constraints

- Answering and hanging up need an explicit click on the handset. No voice
  command and no automatic answer in this task.
- Phone features stay off until the owner turns Phone on (`phone_on`), as
  today. The call buttons run only for a paired Flux device or a Bluetooth
  device the owner paired.
- Call audio never leaves the host: no recording, no transcription, nothing
  sent to the agent or to ElevenLabs.
- Nixi's mic capture (wake word, push-to-talk) must give the mic up for the
  call and take it back afterwards.
- The Pixel Buds and other headsets keep working. A call answered on the
  phone or on the buds is left alone.
- Changes in `nixos_config` follow that repo's rules: deploy from `main`,
  announce on the agent bus, and never touch p510.
- The page stays readable at the page zoom (#109) and honours reduced motion:
  no shaking, a still ringing state instead.

## Open questions

1. **Audio path:** is Bluetooth hands-free the way to go, with the phone
   paired to p620 and razer? A phone usually holds one hands-free link at a
   time, so it links to the host it is near.
2. **Without Bluetooth:** should the handset still offer answer and hang up
   through Flux, which needs an Android change and a new permission, with the
   audio staying on the phone? Or should it show the caller only?
3. **Outgoing calls:** out of scope for this task (dialling from the
   handset)?
4. **Extras in the call:** mute and volume buttons on the handset, or only
   answer and hang up for now?
5. **Ringtone:** a short old-phone ring played on the host while the handset
   shakes, or silent (the phone rings anyway)?
