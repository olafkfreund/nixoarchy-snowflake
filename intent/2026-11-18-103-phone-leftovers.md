---
status: draft
issue: 103
author: olafkfreund
---

# Intent: finish two Phone leftovers from #100

Follow-up to `plan/2026-11-18-100-phone-flux-gaps.md`. Two small gaps remain.

## Problem

1. **Phone-off phrases go to the agent as prompts.** `phone_quick`
   (`app/server.py:8239`) returns `None` when Phone is off or not
   connected, except for ring, clip, shot and status phrases that say "my
   phone" (`:8245-8247`). So "tell my phone ...", "answer X on my phone:
   ..." and "show my phone notifications" (`do` = `note`, `notify_reply`,
   `notes`; `app/quick.py:360-385`, `_phone` at `:346`) are not handled.
   They return `None`, which `phone_quick`'s docstring and `:7794` define as
   "the phrase isn't ours", so the caller goes on with it as a normal
   request (what the client or model does after that is not shown in
   `app/`; `:9712` only returns `handled: false`). The `flux-cli` agent
   policy is the known backstop; this intent does not claim it is the only
   one. The reply and read phrases do the same today. The user is told
   nothing, and a private phrase about their phone may leave the machine.
2. **A "when done" chooser can be shown with nothing running.** With
   several devices, `phone_quick` (`app/server.py:8263-8266`) reads
   `ST.active_turn` and calls `phone_pick_card` with `turn=None` even when
   no turn is active. The card is shown. The click then goes through
   `phone_pick_note` (`:8013`; its `nothing_running` fallback is at `:8024-8026`), which answers `phone.nothing_running`.
   The user picks a device and only then learns there was nothing to wait
   for. The single-device path already checks, in `phone_when_done`
   (`:7964`).

## Proposed outcome

1. With Phone off (or not running), each phone phrase that is clearly
   for the phone is answered by Nixi with the existing `phone.off` or
   `phone.not_running` line instead of going on as a prompt. This covers
   note, when-done, notify-reply and notes, and reply and read only where
   the match is unambiguous (see Open question 1). Phrases that today
   deliberately fall through stay as they are. This is not a guarantee
   that nothing reaches the agent: a note over 200 characters does not
   match at all (`app/quick.py:391`, `len(text) <= 200`), and the reply
   helpers can still return `None` if Phone drops after the dispatch check
   (`app/server.py:8191-8192`).
2. "Tell my phone when done" with several devices and no running turn
   gets `phone.nothing_running` at once, with no chooser card. With a
   running turn, nothing changes.

## Affected users and systems

- Users who say phone phrases with Phone off, and users with several
  paired devices.
- `app/server.py` (`phone_quick`), possibly `app/quick.py` (`_phone`,
  `handle`) and the phone tests. No Flux change. No host needs a deploy
  to test.

## Constraints

- Scope is these two items only.
- Keep the click-confirmed consent from #100 (`plan/2026-11-18-100-phone-flux-gaps.md:38-40`,
  the agent cannot send): drafts and chooser tokens stay single-use and
  need a click. `phone_pick_note` (`:8013-8026`) must keep re-checking
  `gen`, `phone_on` and `connected`, and `phone_when_done` must keep
  re-checking the turn under `WATCH_LOCK` (`:7962-7964`) at click time.
  The early "nothing running" answer in item 2 is a convenience only; it
  does not replace those click-time checks, since the turn can end
  between card and click.
- Must not weaken the agent policy on `flux-cli` and the socket. It stays
  as the backstop.
- Must not say anything private about the phone (device names, content)
  in the Phone-off reply.
- Must not break phrases that look similar but are not for the phone, for
  example "tell the X session: ...", which is handled first in
  `quick.handle`.
- No new `Phone.METHODS`, no new endpoints.
- Lock order from #100 stays: never hold `WATCH_LOCK` and `PHONE_LOCK`
  together.
- Tests must not import the server under the real HOME (use `nixi_env`).
  Before a PR, README "Working on it" says whether plugin sandbox tests
  must be run.
- p510 needs the owner's OK before any build or deploy.

## Open questions

1. **Which phrases get the Phone-off answer?**
   - A: all phone phrases that `quick.handle` matched, including reply
     and read.
   - B: only note, when-done, notify-reply and notes, plus reply and read
     where the match is unambiguous.
   - Recommendation: B. `:7794` and `:8219-8223` show that `None` is
     deliberate for ambiguous find/send/status and reply phrases: unknown
     device names, channel wording, and no-contact matches that are not
     SMS. Answering "Phone is off" for those would swallow phrases meant
     for something else. The plan must list which reply/read shapes are
     unambiguous and test that the fall-through ones still fall through.
2. **Where to fix item 1?**
   - A: in `phone_quick`, answer for the `do` values chosen in question 1
     when Phone is off.
   - B: set `generic` in `_phone` and the phrase loops.
   - Recommendation: A. Phrases matched by `handle` for those `do` values
     are already phone phrases. It is a smaller change and `generic` is only a guard for
     the loose find/send phrases.
3. **Where to check "nothing running" for the chooser?**
   - A: in `phone_quick`, before `phone_pick_card`, when `do` is
     `when_done` and `turn` is `None`.
   - B: inside `phone_pick_card`.
   - Recommendation: A. It is the only caller that has a turn.
