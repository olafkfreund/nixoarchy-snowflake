---
status: draft
issue: 107
author: olafkfreund
---

# Intent: pause clipboard sharing for codes while Nixi is hidden

## Problem

- **What #105 does:** when a notification carries a one-time code, Nixi asks Flux for a 2-minute owned clipboard pause.
- **Where it stops working:** Nixi only checks for codes in `Inbox.rows`, and `Inbox.rows` runs only while Nixi takes notifications over.
  - `Inbox.want()` (`app/server.py:3260`) is false while `Wake.asleep` is true.
  - Hiding Nixi posts `/api/sleep {on: true}` (`app/static/index.html:4690`, `app/server.py:9391`). So a hidden Nixi is asleep, and the shell shows its own popups.
  - Nixi is hidden most of the day, so the pause rarely runs.
- **Seen live on p620 (2026-11-19):** with Phone, takeover and `proactive` all on, four test codes showed as shell popups, and Flux listed no pause.
- **What is already safe:** the shell popup's own **Copy code** button copies with `wl-copy --sensitive` (omarchy `shell/plugins/notifications/Service.qml:1254`). Flux drops sensitive clips (`internal/desktop/clipboard.go:159` in nixarchy-flux). The gap is a code copied any other way while the notification is up: selected in the mail or chat app it came from, or typed from it into a field and copied again.

## Proposed outcome

- **The pause runs whether Nixi is shown or hidden,** as long as Nixi is running and Phone is on. Everything else stays as #105 set it:
  - 120 s;
  - renewed by a new code, at most 5 requests per hold;
  - never ended early;
  - the same detection (`Inbox.OTP` or `SECRET_LINE`) and the same Flux eligibility checks.
- **A hidden Nixi still doesn't take notifications over.** The shell keeps its popups, and a hidden Nixi shows nothing new on screen.
- **One notification is one code,** whichever way Nixi saw it.

## Affected users and systems

- **Nixi companion:** `app/server.py`, the notification and `CodePause` path. Possibly a new small reader for notifications that arrive while Nixi isn't taking them over.
- **nixos_config:** one `nixi-companion` input bump, deployed to p620 and razer. No Flux change.
- **The user,** on both machines.

## Constraints

- **Everything #105's intent required still holds:**
  - no pause path for the agent, and no `TOOL_TOKEN` endpoint;
  - only the owner label and the duration go to Flux;
  - Nixi never ends or shortens a pause;
  - notifications are never held up;
  - it's a mitigation, not a guarantee.
- **Notification text stays in memory only,** as it does during takeover today: not stored, logged or sent anywhere. Nixi keeps only the yes/no verdict and a key for dedupe.
- **The shell's popups and the takeover hand-off are unchanged.**
- **Nixi stays quiet while asleep:** no mic, no voice, no window.

## Open questions

1. **Where a hidden Nixi reads notifications from.** The shell's socket has no read-only method today: `ping`, `delegate`, `delegateRich` and `showKey` only.
   - **(a) A session-bus monitor** of `org.freedesktop.Notifications.Notify` calls. Tested on p620: `busctl --user monitor` with that match saw the summary and body of a `notify-send`. This needs no shell change. **Recommended.**
   - **(b) A new read-only method on the shell socket.** That is a change to basecamp/omarchy, which we don't own.
   - **(c) Keep the lease while hidden,** taking notifications over without showing them. Rejected up front: it would hide every notification while Nixi is hidden.
2. **One detection path or two.** With (a), the monitor could become the only detection path, shown or hidden, and `Inbox.rows` would keep only the display gate. Or the monitor could run only while Nixi is asleep. One path is simpler, and it can't count one notification twice. **Recommended: one path.**
3. **What a hidden Nixi shows when it pauses.** #105's toast lives in Nixi's page, so it isn't seen while hidden.
   - **(a) Nothing while hidden.** The pause is silent, and `flux-cli status` still lists it. **Recommended.**
   - **(b) A desktop notification.** It would be one more popup next to the code's popup.
