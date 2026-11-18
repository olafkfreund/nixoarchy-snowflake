---
status: draft
issue: 105
author: olafkfreund
---

# Intent: pause Flux clipboard sharing while a one-time code is around

## Problem

- **What happens today:** when a sign-in or verification code arrives, you often copy it.
  - With automatic clipboard sharing on, Flux shares every local copy with your paired devices, so the code goes to your phone (and any other device) too.
  - Nixi already recognises these notifications. `Inbox.OTP` (`app/server.py:3191`) and `SECRET_LINE` hide their text on screen (`:3320`, `:3331`), or hand a card with buttons back to the shell. It does nothing about the clipboard.
- **Why it waited:** #100 left this out because Flux's pause was one boolean with no owner.
  - Nixi could not pause without risking ending a pause you set yourself, or leaving sharing paused after a crash.
- **What changed:** Flux now has owned pauses that end by themselves (olafkfreund/nixarchy-flux#77, merged in #78). That block is gone.

## Proposed outcome

- **The pause:** when Nixi sees a notification that `Inbox.OTP` or `SECRET_LINE` flags, it asks Flux for an owned clipboard pause under its own label, for a short time.
  - "Short" is a proposal, not decided: about 2 minutes.
  - A *new* code during the pause renews it. An update or repeat of the same notification is not a new code.
  - Renewal is bounded on Nixi's side too, so a storm of matching notifications can't keep sharing paused indefinitely. Flux's cap covers only one continuous hold, and a fresh hold may start after it expires.
  - Detection is its own check, separate from the display gate. Today's gate stops early when details are off (`:3320`), so it can't be reused as it is.
- **A pause you set yourself** (Flux's Chat page or `flux-cli clipboard pause`) is never ended or shortened by Nixi.
- **If Nixi crashes or restarts,** its pause still ends by itself, at the latest when its time runs out.
- **If `fluxd` restarts,** Flux drops owned pauses at once. Nixi does not restore them. This gap is accepted and documented.
- **Switching Phone off** stops Nixi's Flux client but doesn't end a pause Nixi already set. That pause expires on its own.
- **When nothing happens:** with Phone off, Flux not running, or an older Flux without the new methods, Nixi simply does not pause.
  - There is no error card, and this feature adds no retry loop. Flux's own reconnect logic is unchanged.
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

- **No pause path for the agent.** No endpoint reachable with `TOOL_TOKEN` can start or end the pause, and Nixi pauses only on its own detection.
  - This is narrower than "the agent can't touch the clipboard". The agent runs as the same user, Flux's socket identifies only the Unix user, and owner labels are not identity.
  - The existing `flux-cli` command policy (`app/server.py:962`) stays as it is.
- **The pause request carries only an owner label and a duration.** The label is fixed text naming this Nixi instance, reused for its renewals, with no notification content.
  - It must meet Flux's label rules: 1–64 bytes of valid UTF-8, no control characters and no U+FFFD.
  - A rejection (`too_many`, an old Flux, `bad_params`) means Nixi doesn't claim the pause.
  - Nixi reads the returned `expires` before it says anything about protection: near Flux's cap, it can be earlier than asked.
- **Notifications are never held up.** `Phone.call` can wait up to 10 s for Flux, so the pause request runs off the notification path, and quick repeats are folded into one request.
- **Only Nixi's own pause is touched.** It never calls plain `clipboard.pause`/`resume` or `resume` with `force`.
- **The pause is a mitigation, not a guarantee:**
  - detection runs only while Nixi takes notifications over;
  - a copy made before the notification is seen can still go out;
  - Flux's docs say a send that passed its check can still go out.
  - The docs and the PR will say so.
- **What a pause costs:** it stops only automatic sharing.
  - Manual sends and incoming clips still work.
  - Copies made during the pause, including unrelated ones, are not shared and stay out of Flux history.
  - Copying the same value again after the pause may not sync.
- **No new setting unless needed.** It follows the existing Phone switch.

## Open questions

1. **Duration:** 2 minutes, or another value? Flux allows 1 s to 1 h. Codex suggests 120 s.
2. **Ending early:** should Nixi end its pause early (`resumeOwned`) when the code's notification is dismissed? Or only let it expire, which is simpler? Codex suggests letting it expire: a dismissal doesn't mean the clipboard is safe.
3. **Showing the pause:** show a short line ("Clipboard sharing paused for the code"), or stay silent? Codex suggests one line, without the code, after Flux confirms. A renewal updates the line instead of repeating it.
4. **Mail codes:** also pause when the mail board finds a code (`mail_otp`, `app/server.py:7246`)? Or only for notifications? Codex suggests notifications only. Reopening the mail board can rediscover old codes, and `mail_otp` also serves the scrubbers.
