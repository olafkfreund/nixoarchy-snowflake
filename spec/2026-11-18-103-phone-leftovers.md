---
status: draft
issue: 103
intent: intent/2026-11-18-103-phone-leftovers.md
---

# Spec: finish the Phone leftovers from #100

Three small changes: answer Phone-off phrases, skip the chooser when nothing
runs, and replace seven nb/pl strings. Intent decisions carried over: Q1 = B,
Q2 = A, Q3 = A, and the seven wording replacements the owner approved.

## Design

### 1. Phone-off answer (`app/server.py`, `phone_quick`, now `:8245-8247`)

Q2 = A: fix it in `phone_quick`, not in `generic`. One small flag is added in
`quick._phone` for explicit SMS read phrases (below); `generic` is untouched.
`quick.handle` already matched a phone phrase before `phone_quick` is called.

Today the off branch answers only `ring|clip|shot|status` with `generic`.
Add a second condition to the same branch. When `not CFG["phone_on"]` or
`not Phone.connected`, also answer these with `phone.off` (Phone off) or
`phone.not_running` (on, but Flux down), the same pick the first condition
already makes:

- `do` in `note`, `when_done`, `notes`, `notify_reply`. Every phrase that
  produces these names the phone: en "tell my phone", "answer {name} on my
  phone", "show my phone notifications"; nb "telefonen min"; pl "mojemu
  telefonowi", "moim telefonie", "mojego telefonu". Their `name` is a sender
  or absent, never a device, so no device-name ambiguity.
- `do == "reply"` only when `r.get("sms")` is true. `handle` sets `sms` when
  the words before the text say sms, text message, melding or wiadomosc, so
  the phrase is about messages. Plain "reply to Ann, ..." and "text Ann ..."
  (no sms word) stay `None`: they may be an email or chat reply.
- `do == "read"` only when `r.get("sms")` is true. Q1 = B asks for read where
  the match is unambiguous. `quick._phone` returns `{"phone": {"do": "read"}}`
  for any `phone_read` phrase with no flag, so it cannot tell them apart today.
  Change: in its `phone_read` branch add `"sms": True` when the phrase
  contains the word sms (`re.search(r"\bsms", t)`). That is exactly nb
  "sjekk sms" and pl "przeczytaj moje smsy", "przeczytaj smsy", "sprawdz
  smsy". The other read phrases ("any new messages", "read my texts", "les
  meldingene mine", "przeczytaj moje wiadomosci", ...) name no SMS, so they
  may mean mail or chat and stay `None`. `phone_read_messages` ignores the
  extra key.
- `ring|clip|shot|status` keep their `generic` rule unchanged.

Sketch (one helper keeps both conditions short):

```python
if not CFG.get("phone_on") or not Phone.connected:
    ours = (do in ("ring", "clip", "shot", "status") and r.get("generic")) \
        or do in ("note", "when_done", "notes", "notify_reply") \
        or (do in ("reply", "read") and r.get("sms"))
    return {"say": lang.t("phone.off" if not CFG.get("phone_on") else "phone.not_running"), "mood": "curious"} if ours else None
```

The reply carries no device name, text or notification content. The unknown-`do`
guard at `:8241` still runs first, so a bogus action never reaches `phone_share`.
No new method, endpoint or key: `phone.off` and `phone.not_running` exist in
en, nb and pl. `phone_reply_quick` and `phone_notify_reply_quick` keep their
`return None` when Phone is off; they are reached only after the new branch,
and stay as the guard for a Phone that drops mid-dispatch (`:8191-8192`,
`:8207-8208`).

Not covered, as the intent says: a note over 200 characters (`quick.py:391`)
never matches, so it still goes on as a prompt. The `flux-cli` agent policy
stays the backstop.

### 2. No chooser with nothing running (`phone_quick`, `:8263-8266`)

Q3 = A. In the several-device branch, `turn` is read under `WATCH_LOCK`
already. Before `phone_pick_card`, add:

```python
if do == "when_done" and turn is None:
    return {"say": lang.t("phone.nothing_running"), "mood": "curious"}
```

`do == "note"` is untouched (it does not use `turn`). With a running turn the
card is built as today. This is a convenience only: `phone_pick_note`
(`:8013-8026`, including its `nothing_running` fallback) and `phone_when_done`
(`:7962-7964`, turn re-checked under `WATCH_LOCK`) stay as they are, since the
turn can end between card and click. The single-device path already checks in
`phone_when_done`. The `WATCH_LOCK` block ends before the new return, so no
lock is held across it, and `WATCH_LOCK` and `PHONE_LOCK` are never held
together.

### 3. nb/pl wording (`app/lang/nb.json`, `app/lang/pl.json`)

Value-only edits, same keys, no placeholders touched:

| file | key | new value |
|---|---|---|
| nb | `phone.when_done_button` (`:125`) | Si fra til telefonen når Nixi er ferdig |
| nb | `phone.turn_failed` (`:128`) | Nixi støtte på et problem. |
| nb | `phone.notify_none` (`:136`) | Jeg finner ikke noe varsel fra den avsenderen som du kan svare på. |
| pl | `phone.note_sent` (`:180`) | Przekazałem telefonowi. |
| pl | `phone.fingerprint` (`:191`) | odcisk klucza |
| pl | `phone_when_done` phrases 1 and 2 (`:258-259`) | powiadom mój telefon, gdy to będzie gotowe / powiadom mój telefon, gdy skończysz |
| pl | `phone.nothing_running` (`:184`) | Nic teraz nie działa. |

The pl third phrase ("daj znać mojemu telefonowi, gdy skończysz") stays.
Non-native reviewers only; the owner approved the wording.

## Alternatives rejected

- Q1 A (answer every matched phone phrase, including all reply and read):
  swallows ambiguous phrases that `:7794` and `:8219-8223` deliberately let
  fall through ("reply to Ann" meant for mail, "any new messages").
- Q2 B (set `generic` in `_phone` and the phrase loops): `generic` is a
  guard for the loose find/send phrases; touching every loop is a bigger
  change for the same effect. (The one `sms` flag on read is a single line.)
- Q3 B (check inside `phone_pick_card`): it has no turn and is called from
  other paths (ring, clip, shot) that would carry the check as dead code.
- Answering `reply` or `read` with `sms` unset: rejected with A above.
- Leaving `read` always `None` (no `quick.py` change): contradicts Q1 = B for
  the explicit-SMS read phrases, so rejected.
- A shared "phone phrase" predicate in `quick.py` that tags `do` values:
  more code than one condition in `phone_quick`.
- Dropping the click-time recheck in `phone_pick_note` now that the card is
  gated: rejected, the turn can end between card and click (intent
  constraint).

## Risks

- Behaviour change on every host: with Phone off, "tell my phone ..." now
  stops at Nixi instead of going to the agent. That is the goal. A user who
  says "tell my phone" about something else gets "Phone is off". The phrase
  list is narrow, so I judge this acceptable.
- `reply` with `sms` and Phone off now answers `phone.off`. "send sms to
  Ann, ..." meant as another tool's SMS would be caught. Accepted: sms is
  the phone's job here.
- The `sms` flag comes from a regex on the prefix (reply) or on the phrase
  (read), so a word like "text message" or "sms" in other contexts sets it;
  only matters for Phone-off hosts.
- nb/pl wording is not native-reviewed; a wrong phrase only changes text.
  The pl phrase change must not break phrase parsing: covered by tests.
- Existing tests at `tests/test_phone.py:528,531,1098,1116` assert `None`
  for ring-with-name and fall-through reply phrases; they must still pass
  unchanged. Any that assert `None` for a `do` now covered must be updated
  in the same commit as the code. Likewise any test that
  compares the exact `quick.handle` result for the four SMS read phrases.
- No Flux change, no new endpoint, no host deploy needed to test. p510 build
  or deploy needs the owner's OK.

## Verification

Tests in `tests/test_phone_flux_more.py` (style: `_ServerEnv`, `nixi_env`,
`StubPhone`, mocks on `s.Phone` and `s.CFG`; restore `CFG` with `addCleanup`).
Never import the server under the real HOME.

1. `DispatchGuardTest` (or a new `PhoneOffTest`): with `phone_on` False,
   `phone_quick` for `note`, `when_done`, `notes`, `notify_reply`, and `reply`
   or `read` with `sms=True` returns `phone.off`; with `phone_on` True and
   `Phone.connected` False returns `phone.not_running`. Assert the reply text
   has no device name or note text. Assert `phone_share`, `phone_note` and
   `Phone.call` are not called.
2. Fall-through still falls through: Phone off, `reply` without `sms`,
   `read` without `sms`, `ring` with a name and no `generic`, and `bogus` all return
   `None`.
3. End to end through `quick.handle`: for en, nb and pl, a note, a
   notify-reply and a notes phrase map to a `do` that gets the Phone-off line;
   "tell the X session: ..." still maps to `session_send`; a note over 200
   chars still does not match. Also: `quick.handle` on nb "sjekk sms" and pl
   "przeczytaj smsy" / "przeczytaj moje smsy" returns `read` with `sms`
   true; en "read my texts", nb "sjekk meldingene mine" and pl "przeczytaj
   moje wiadomosci" return `read` without it.
4. Chooser: two devices, `ST.active_turn = None`, `phone_quick({"do":
   "when_done"})` returns `phone.nothing_running`, publishes no stage (`BUS.pub`
   not called, `STAGES.current()` unchanged). With `active_turn = 12` the card
   is shown as before. The existing `test_chooser_token_...` (turn 12 then 13
   at click) keeps passing, proving the click-time recheck.
5. Wording: a test that loads nb and pl and asserts the seven new values
   (strings and the two pl phrases), that the pl third phrase is unchanged,
   and that `test_each_language_parses` still parses "powiadom mój telefon,
   gdy skończysz" to `when_done`. `test_every_new_key_exists_in_all_languages`
   stays green.
6. Run: `python3 -B tests/test_phone_flux_more.py`, `tests/test_phone.py` and
   the full test suite. README "Working on it" requires the plugin sandbox run
   only if `app/plugins.py`, `tests/test_plugin_sandbox.py` or the wrapper
   PATH change; they do not, so the PR says it was not needed.
7. Runtime check: none on a host needed. Optional, on request: with Phone
   off, say "tell my phone hello" and confirm Nixi answers and no agent turn
   starts. Not on p510 without the owner's OK.
