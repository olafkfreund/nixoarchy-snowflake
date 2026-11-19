---
status: draft
issue: 107
author: olafkfreund
---

# Intent: pause clipboard sharing for codes while Nixi is hidden

## Problem

- **What #105 does:** when a notification matches the code-or-secret checks (`Inbox.OTP` or `SECRET_LINE`), Nixi asks Flux for a 2-minute owned clipboard pause.
  - `SECRET_LINE` (`app/server.py:6829`) also matches passwords, API keys and long token-shaped strings, so "code" here means that whole set.
  - Flux eligibility and #105's request cap can still stop a request.
- **Where it stops working:** the check sits in `Inbox.rows`, which runs only while `Inbox.want()` is true (`app/server.py:3260`).
  - `want()` needs `proactive`, notification takeover, an open page stream, no fullscreen window, and Nixi awake.
  - Hiding Nixi posts `/api/sleep {on: true}` (`app/static/index.html:4690`) and sets `Wake.asleep` (`app/server.py:9392`). A hidden Nixi is therefore asleep, and the shell shows its own popups.
  - Nixi is hidden most of the day, so the pause rarely runs. Fullscreen and takeover-off have the same effect.
- **Seen live on p620 (2026-11-19):** with Phone, takeover and `proactive` all on and Nixi hidden, four test codes showed as shell popups, and Flux listed no pause.
- **What is already safe:** the shell popup's own **Copy code** button copies with `wl-copy --sensitive` (omarchy `shell/plugins/notifications/Service.qml:1254`). Flux drops sensitive clips (nixarchy-flux `internal/desktop/clipboard.go:159`).
  - The gap is a code copied any other way while it is around, for example selected in the mail or chat app it came from.

## Proposed outcome

- **The pause depends only on Nixi running and Phone being on.** Hidden or shown, fullscreen or not, takeover on or off.
  - `proactive`, takeover, the page stream and fullscreen keep governing what Nixi shows. They no longer govern the pause.
- **#105's rules are unchanged:**
  - 120 s;
  - renewed by a new code, at most 5 requests per hold;
  - never ended early;
  - the same `OTP`/`SECRET_LINE` checks, on visible text (markup stripped, as #105 does for rich text), plus action labels;
  - the same Flux eligibility checks.
- **Coverage widens on purpose.** The check sees every notification sent to the desktop's notification server. Today it only sees the rows the shell hands Nixi, which the shell's categories and `Inbox.KEY` filter first.
  - **The cost:** more false positives, each one a 2-minute pause. The docs will say so.
- **A hidden Nixi still doesn't take notifications over.** The shell keeps its popups, and the shell's delivery is never touched.
- **One notification is one code.** An update of a notification, or a repeat of it, is not a new code, within #105's dedupe bounds (64 keys, 10 min). A notification updated from clean text to a code counts once, when the code appears.
- **`Inbox.rows` keeps its display protection** (blanking text, handing cards back) exactly as today. The two checks never loosen each other: neither unblanks text nor changes delivery.

## Affected users and systems

- **Nixi companion:** `app/server.py`, where `CodePause` gets a new feed of notifications. There may also be a new small reader for the notification server's calls.
- **nixos_config:** one `nixi-companion` input bump, deployed to p620 and razer. No Flux or shell change.
- **The user,** on both machines.

## Constraints

- **Everything #105's intent required still holds:**
  - no pause path for the agent, and no `TOOL_TOKEN` endpoint;
  - only the owner label and the duration go to Flux;
  - Nixi never ends or shortens a pause;
  - notifications are never held up;
  - it's a mitigation, not a guarantee.
- **Privacy:** Nixi now reads notification text while hidden, including notifications it would never show. That is a real widening, accepted only because of the following:
  - It reads only while Phone is on. Turning Phone off stops it.
  - It asks the bus for the narrowest match: `Notify` calls on `org.freedesktop.Notifications`, and the replies it needs to learn a notification's id.
  - Text stays in memory, only for the length of the check. It is never stored, logged, published to the page, or passed to plugins or the agent. Nixi keeps only the yes/no verdict and a dedupe key.
  - Processing and kept state are bounded.
- **The way in is the bus's own monitoring interface** (`org.freedesktop.DBus.Monitoring.BecomeMonitor`), as the same user. Nothing more:
  - no root;
  - no policy change;
  - no legacy eavesdropping.
- **Failure is quiet and safe:**
  - If monitoring is refused or stops, shell delivery is untouched, and Nixi prints at most one line without content.
  - It tries again on a slow, bounded schedule.
  - While monitoring is down, #105's takeover check still pauses, so this is never worse than today.
- **No new dependency:** the Python D-Bus support Nixi already ships (PyGObject `Gio`, `nix/package.nix:45`), on its own private connection. The reader doesn't parse `busctl` text: `busctl` isn't on Nixi's PATH.
- **Nixi stays quiet while asleep:** no mic, no voice, no window.

## Decisions (approver, 2026-11-19: the recommendations taken)

1. **Source:** a session-bus monitor of `Notify` calls and their replies, through `BecomeMonitor` on a private Gio connection.
2. **Sharing the pause:** the monitor feeds it. #105's `Inbox.rows` hook stays as the fallback and feeds it only when the monitor hasn't counted a code in the last 10 s. *(Amended 2026-11-19 after Codex's spec review: an "is the monitor up" switch loses or double-counts codes around reconnects. Pending re-approval.)*
3. **While hidden:** nothing is shown. The #105 toast stays while Nixi is shown.

## Open questions

None. The earlier options, for the record:

1. **Where a hidden Nixi reads notifications from.**
   - **(a) A session-bus monitor of `Notify` calls and their replies.** No shell change needed.
     - **p620:** `busctl --user monitor` saw a `notify-send`'s summary and body. `busctl` uses `BecomeMonitor`.
     - **razer:** not tested yet.
     - **Recommended.**
   - **(b) A new read-only method on the shell socket.** That's a basecamp/omarchy change, which we don't own.
   - **(c) Keep the lease while hidden.** Rejected: it would hide every notification while Nixi is hidden.
2. **How the two checks share the pause.**
   - **(a) The monitor feeds the pause whenever it runs, and #105's `Inbox.rows` hook feeds it only while the monitor is down.** There is one source at a time, so a notification is never counted twice by key mismatch. **Recommended.**
   - **(b) Both feed it all the time.** A notification seen both ways would use 2 of the 5 requests in a hold.
   - **(c) Monitor only.** This gives up today's pause whenever monitoring fails.
3. **What a hidden Nixi shows when it pauses.**
   - **(a) Nothing while hidden.** The pause is silent, and `flux-cli status` lists it. While Nixi is shown, the #105 toast stays. **Recommended.**
   - **(b) A desktop notification.** That's one more popup next to the code's popup.
