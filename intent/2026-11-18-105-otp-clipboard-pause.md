---
status: draft
issue: 105
author: olafkfreund
---

# Intent: pause Flux clipboard sharing while a one-time code is around

## Problem

- **What happens today:** when a sign-in or verification code arrives, you often copy it.
  - Flux shares every local copy with your paired devices, so the code goes to your phone (and any other device) too.
  - Nixi already recognises these notifications: `Inbox.OTP` (`app/server.py:3191`) blanks their text on screen (`:3320`, `:3331`). It does nothing about the clipboard.
- **Why it waited:** #100 left this out because Flux's pause was one boolean with no owner.
  - Nixi could not pause without risking ending a pause you set yourself, or leaving sharing paused after a crash.
- **What changed:** Flux now has owned pauses that end by themselves (olafkfreund/nixarchy-flux#77, merged in #78). That block is gone.

## Proposed outcome

- **The pause:** when Nixi sees a notification that `Inbox.OTP` or `SECRET_LINE` flags, it asks Flux for an owned clipboard pause under its own label, for a short time.
  - "Short" is a proposal, not decided: about 2 minutes.
  - A second code during the pause renews it.
- **A pause you set yourself** (Flux's Chat page or `flux-cli clipboard pause`) is never ended or shortened by Nixi.
- **If Nixi crashes or restarts,** its pause still ends by itself, at the latest when its time runs out.
- **When nothing happens:** with Phone off, Flux not running, or an older Flux without the new methods, Nixi simply does not pause.
  - There is no error card and no retry loop.
  - At most one line goes to the log.
- **What you see:** you may see a short line that sharing is paused for the code, without the code itself. Whether to show it is an open question.
- **nixos_config** moves its `nixarchy-flux` input to a Flux with owned pauses, for p620 and razer.

## Affected users and systems

- **Nixi companion:**
  - `app/phone.py`: the allowed methods grow by `clipboard.pauseOwned`, and maybe `clipboard.resumeOwned`.
  - `app/server.py`: the notification path, where `Inbox.rows` runs.
- **nixos_config:** the `nixarchy-flux` input bump. It restarts `fluxd` on p620 and razer.
  - p510 doesn't run Flux, so no owner OK is needed.
- **The user,** on both machines.

## Constraints

- **The agent can't control your clipboard.** As with #100, `TOOL_TOKEN` and the agent's tools never reach the pause.
  - Nixi pauses only on its own detection.
- **Nothing about the code leaves Nixi.** The owner label carries no notification text.
- **Only Nixi's own pause is touched.** It never calls plain `clipboard.pause`/`resume` or `resume` with `force`.
- **The pause is a mitigation, not a guarantee:**
  - detection runs only while Nixi takes notifications over;
  - a copy made before the notification is seen can still go out;
  - Flux's docs say a send that passed its check can still go out.
  - The docs and the PR will say so.
- **No new setting unless needed.** It follows the existing Phone switch.

## Open questions

1. **Duration:** 2 minutes, or another value? Flux allows 1 s to 1 h.
2. **Ending early:** should Nixi end its pause early (`resumeOwned`) when the code's notification is dismissed? Or only let it expire, which is simpler?
3. **Showing the pause:** show a short line ("Clipboard sharing paused for the code"), or stay silent?
4. **Mail codes:** also pause when the mail board finds a code (`mail_otp`, `app/server.py:7246`)? Or only for notifications?
