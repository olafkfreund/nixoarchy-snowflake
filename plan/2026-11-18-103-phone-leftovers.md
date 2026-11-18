---
status: approved
issue: 103
spec: spec/2026-11-18-103-phone-leftovers.md
coders:
  1: codex    # small, tricky: the Phone-off branch and the sms flag, which must not swallow fall-through phrases
  2: coder    # one guard line, eight value edits in two JSON files, one test phrase
  3: coder    # tests for 1 and 2, then the full suite
reviewers:
  - codex     # read-only review of each step's diff and of the whole branch against this plan
---

# Plan: finish the Phone leftovers from #100

This plan carries the approved intent and spec decisions, so it can be
implemented without opening either.

- **Repo:** `/mnt/code/Source-home/GitHub/nixi-103-leftovers` (nixoarchy-snowflake)
- **Branch:** `fix/103-phone-leftovers`, from `f927e1c`. Line numbers refer to it.

## Decisions (all approved)

Three small changes. Intent Q1 = B, Q2 = A, Q3 = A, and the seven nb/pl
wording replacements the owner approved.

1. **Phone-off answer, in `phone_quick` (`app/server.py:8245-8248`), not in `generic`.**
   With `not CFG["phone_on"]` or `not Phone.connected`, answer `phone.off`
   (Phone off) or `phone.not_running` (on, Flux down), the same pick the branch
   already makes, for:
   - `ring|clip|shot|status` only when `r.get("generic")` (unchanged);
   - `do` in `note`, `when_done`, `notes`, `notify_reply` (their phrases always
     name the phone; `name` is a sender or absent, never a device);
   - `do` in `reply`, `read` only when `r.get("sms")` is true. Plain "reply to
     Ann, ..." and "any new messages" stay `None` (they may be mail or chat).
   Everything else returns `None`. The unknown-`do` guard at `:8243` runs
   first, so `bogus` never reaches `phone_share`. The reply carries no device
   name, text or notification content. No new method, endpoint or key:
   `phone.off` and `phone.not_running` exist in en, nb and pl.
   `phone_reply_quick` and `phone_notify_reply_quick` keep their `return None`
   when Phone is off (guard for a Phone that drops mid-dispatch).
2. **`sms` flag on read, in `app/quick.py` `_phone` (`:350-351`).** The
   `phone_read` branch returns `{"phone": {"do": "read", "sms": True}}` when
   the phrase has the word sms (`re.search(r"\bsms", t)`), else
   `{"phone": {"do": "read"}}`. That is exactly nb "sjekk sms" and pl
   "przeczytaj moje smsy", "przeczytaj smsy", "sprawdź smsy". Other read
   phrases ("any new messages", "read my texts", "les meldingene mine",
   "przeczytaj moje wiadomości") stay unflagged. `phone_read_messages` ignores
   the extra key. `reply` already sets `sms` (`quick.py:399-401`); untouched.
3. **No chooser with nothing running (`phone_quick`, `:8264-8267`).** In the
   several-device branch, after `turn` is read under `WATCH_LOCK` (the block
   ends before the new line, no lock held across the return), add
   `if do == "when_done" and turn is None: return {"say": lang.t("phone.nothing_running"), "mood": "curious"}`
   before the `phone_pick_card` call at `:8267`. `note` is untouched. `phone_pick_note`
   (`:8013-8026`) and `phone_when_done` (`:7962-7964`) keep their click-time
   recheck, since the turn can end between card and click. Single-device path
   unchanged.
4. **nb/pl wording**, value-only edits, same keys, no placeholders:

   | file | key (line) | new value |
   |---|---|---|
   | nb | `phone.when_done_button` (125) | Si fra til telefonen når Nixi er ferdig |
   | nb | `phone.turn_failed` (128) | Nixi støtte på et problem. |
   | nb | `phone.notify_none` (136) | Jeg finner ikke noe varsel fra den avsenderen som du kan svare på. |
   | pl | `phone.note_sent` (180) | Przekazałem telefonowi. |
   | pl | `phone.fingerprint` (191) | odcisk klucza |
   | pl | `phone_when_done` phrase 1 (258) | powiadom mój telefon, gdy to będzie gotowe |
   | pl | `phone_when_done` phrase 2 (259) | powiadom mój telefon, gdy skończysz |
   | pl | `phone.nothing_running` (184) | Nic teraz nie działa. |

   (That is eight edits; the spec's "seven" counts the two phrases as one.)
   The pl third phrase ("daj znać mojemu telefonowi, gdy skończysz", 260)
   stays. Keep the file's exact existing Unicode and JSON indentation.

Not covered: a note over 200 characters never matches (`quick.py`), so it
still goes on as a prompt; the `flux-cli` agent policy stays the backstop.
Not changed: no Flux change, no host deploy, no `app/plugins.py`, so the
README plugin-sandbox run is not needed (the PR says so).

## Steps

1. `app/server.py:8245-8248` and `app/quick.py:350-351`: replace the off
   branch in `phone_quick` with
   ```python
   if not CFG.get("phone_on") or not Phone.connected:
       ours = (do in ("ring", "clip", "shot", "status") and r.get("generic")) \
           or do in ("note", "when_done", "notes", "notify_reply") \
           or (do in ("reply", "read") and r.get("sms"))
       return {"say": lang.t("phone.off" if not CFG.get("phone_on") else "phone.not_running"), "mood": "curious"} if ours else None
   ```
   and in `quick._phone` set `"sms": True` on the read result when
   `re.search(r"\bsms", t)`. -> verify by
   `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_phone.py test_phone_flux_more.py`
   (existing tests must still pass; update in the same commit any that assert
   `None` for a `do` now covered, and any that compare the exact `handle`
   result of the four SMS read phrases).
   Traps: `quick.py` has `re` imported already (used at `:399`); `t` there is
   the lowercased, stripped text. Keep `generic` untouched. The existing
   `None` asserts at `tests/test_phone.py:528,531,1098,1116` (ring with a
   name, fall-through replies) must pass unchanged. Do not touch
   `phone_reply_quick`/`phone_notify_reply_quick`.

2. `app/server.py:~8267` (chooser), the two lang files at the lines
   above and the one phrase in `tests/test_phone_flux_more.py:109`: add the `when_done and turn is None` return before
   `phone_pick_card`; apply the eight value edits. -> verify by
   `python3 -c "import json;[json.load(open(f'app/lang/{c}.json')) for c in ('nb','pl')]"`
   and the test command from step 1.
   Traps: put the return after the `with WATCH_LOCK:` block, not inside it.
   Do not hold `PHONE_LOCK` there. Edit values only; never reorder keys or
   change `{placeholders}`.
   `tests/test_phone_flux_more.py:109` (`test_each_language_parses`) uses the
   pl note phrase "powiedz mojemu telefonowi, gdy skończysz". That phrase
   parses as a `note` with text ", gdy skończysz"; the "gdy" fallback in
   `quick.py:382` only applies when the text starts with "gdy", and this text
   starts with a comma, so it does not match. After this step's phrase edits
   the test would fail, so change that phrase to "powiadom mój telefon, gdy
   skończysz" in this same step's commit (it is the `when_done` phrase 2).
   *Deviation (Opus branch review):* the claim above is wrong. The note pattern
   needs a space before `{text}`, so "powiedz mojemu telefonowi, gdy skończysz"
   parses to `None`, not a note; no junk note reaches the phone. The test phrase
   change stands, because the old phrase no longer parses as `when_done`.

3. `tests/test_phone_flux_more.py` (`DispatchGuardTest` at `:128`, `PhraseTest`
   at `:67`, new tests in the same file): add the tests listed under Tests (the `test_each_language_parses` phrase
   change is already done in step 2).
   -> verify by `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_phone_flux_more.py test_phone.py`,
   then the full suite (below).
   Traps: use `_ServerEnv`/`nixi_env` (#176), never the real HOME. Restore
   `s.CFG` with `addCleanup`. Mock `s.Phone` with `StubPhone`, and assert
   `s.phone_share`, `s.phone_note` and `Phone.call` are not called. Set
   `self.server.lang.active` back as the neighbouring tests do. Leave
   `test_every_new_key_exists_in_all_languages` green.

Before each step name it in the commit message ("plan step N"). If the code
must deviate from this plan, update `plan/` in the same commit. Do not stage,
commit, push, deploy or switch from an agent; the owner or the session does.

## Tests

In `tests/test_phone_flux_more.py`:

1. Phone off (`phone_on` False): `phone_quick` for `note`, `when_done`,
   `notes`, `notify_reply`, and `reply`/`read` with `sms=True` returns the
   `phone.off` text; with `phone_on` True and `Phone.connected` False returns
   `phone.not_running`. The reply has no device name or note text.
   `phone_share`, `phone_note`, `Phone.call` are not called.
2. Fall-through: Phone off, `reply` and `read` without `sms`, `ring` with a
   name and no `generic`, and `bogus` all return `None`.
3. End to end through `quick.handle` (en, nb, pl): a note, a notify-reply and
   a notes phrase map to a `do` that gets the Phone-off line; "tell the X
   session: ..." is still `session_send`; a note over 200 characters still
   does not match. nb "sjekk sms" and pl "przeczytaj smsy" / "przeczytaj moje
   smsy" give `read` with `sms` true; en "read my texts", nb "sjekk
   meldingene mine" and pl "przeczytaj moje wiadomości" give `read` without it.
4. Chooser: two devices, `ST.active_turn = None`,
   `phone_quick({"do": "when_done"})` returns `phone.nothing_running` and
   publishes no stage (`BUS.pub` not called, `STAGES.current()` unchanged).
   With `active_turn = 12` the card is shown as before. The existing
   `test_chooser_token_...` (turn 12, then 13 at click) keeps passing.
5. Wording: load nb and pl, assert the eight new values, the unchanged pl
   third phrase, and that "powiadom mój telefon, gdy skończysz" parses to
   `when_done` (the `test_each_language_parses` update lands in step 2).

Commands:
- Targeted: `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_phone.py test_phone_flux_more.py`
- Full suite: `nix develop .#ci -c python3 -B .github/ci/run_tests.py --exclude test_character_fit.py --exclude test_accessories_fit.py`
- Fit tests (regression only): `nix develop .#ci -c python3 -B .github/ci/run_tests.py --deadline 1800 test_character_fit.py test_accessories_fit.py`.
  They use the default language (no `lang`/`language` setting in either file),
  so they do NOT exercise the longer nb/pl Phone button text. The translated
  button fit is not covered by any test here; the PR says so, and the owner
  may eyeball it in nb/pl.

No host runtime check is needed. Optional on request: Phone off, say "tell my
phone hello", confirm Nixi answers and no agent turn starts. Not on p510
without the owner's OK.

## Rollback

All changes are in `app/server.py`, `app/quick.py`, two lang files and tests,
with no data, config or Flux change. Revert the branch commits (or the PR
merge). Behaviour returns to: Phone-off phrases go to the agent, the chooser
shows with no running turn, and the old nb/pl wording.
