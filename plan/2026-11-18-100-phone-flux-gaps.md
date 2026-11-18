---
status: approved
issue: 100
spec: spec/2026-11-18-100-phone-flux-gaps.md
coders:
  1: coder    # the Flux client, the dispatch guard and lang strings: mechanical, with clear tests
  2: codex    # small, tricky: active turn, slot lifecycle, chooser with pending action, lock order
  3: coder    # Phone tab rows and their rendering
  4: coder    # sms.thread through stage tokens, scrubbed, caption fallback
  5: codex    # small, tricky: notification list, draft bound to nid+rev, consume-then-send
  6: coder    # GUIDE, full suite, fit tests
reviewers:
  - codex     # read-only review of each step's diff and of the whole branch against this plan
---

# Plan: use more of Flux from Nixi's phone feature

This plan includes the approved intent and spec decisions, so it can be
implemented without opening either.
- **Repo:** `/mnt/code/Source-home/GitHub/nixi-100-phone` (nixoarchy-snowflake)
- **Branch:** `feat/100-phone-flux-gaps`, from `origin/main` `e352682`

Line numbers refer to that commit.

## Decisions

- **Scope.** Four features:
  1. "Tell my phone": a note now, or one when the agent turn ends.
  2. A fuller Phone tab.
  3. A conversation's latest 100 texts.
  4. Answering a phone notification.

  Out of scope: incoming-file captions, and clipboard pause (waiting on
  olafkfreund/nixarchy-flux#77).
- **Flux keeps security.**
  - `Phone.METHODS` grows by exactly `notify.send`, `sms.thread` and
    `notification.reply`.
  - Never `settings.set`, `pair.*` or `addresses.*`.
  - No remote control, and no approve buttons.
- **Consent.**
  - **The agent can't send.**
    - Every new endpoint needs the window token. It is not in `TOOL_PATHS`,
      so `TOOL_TOKEN` gets 403.
    - The agent policy on `flux-cli` and the socket is unchanged.
  - **A note** needs your voice or a click.
  - **A reply to someone** needs a click on a single-use draft.
- **A "when done" note**:
  - covers one device, one turn and one send;
  - is cancelled when Phone goes off, Nixi restarts (it lives in memory),
    the device is unpaired, or 30 minutes pass;
  - carries generic text by outcome, never the answer;
  - is never retried after `NotSent` or a timeout;
  - is never queued for an offline phone.
- **A reply draft** is bound to `{device, nid, rev}`, where `rev` is the
  sha256 of app, title, text and replyId. It's single-use, lives 10 minutes,
  and is restored only on `NotSent`.
- **The accepted limit:** Flux can still change a notification between
  Nixi's check and its own lookup of the reply target
  (`internal/core/notifications.go:488`). Nixi catches every change it can
  see.
- **Privacy.**
  - **Scrubbing:** related fields are scrubbed together, with
    `mail_scrub([...])` on the `mail_clean`ed fields (`:6868`), so
    one-time-code context spanning fields is caught:
    - per message, `[name, body]`;
    - per notification and draft header, `[app, title, text]`;
    - device names, `[name]`.
  - **New stage kinds** (`phone_thread`, `phone_notes`, `phone_note_draft`):
    - they join `phone_on_screen()`, so they're never spoken;
    - they're marked `from_phone`, so `phone_reset` closes them;
    - `stageText()` returns `''` for any `from_phone` stage.
  - **Kept off the page:** device IDs for threads, thread IDs, numbers,
    `nid`, `rev` and `replyId` live only in the stage token map
    (`app/stages.py` `Store.put`, as `phone_sms` does at `:466-473`).
    `stage_event` forwards every page field (`server.py:6698`).
  - **Kept off everything else:** nothing new reaches the status line, the
    plugin feed, logs (exception type names only) or agent prompts.
- **Off means off.**
  - Each path checks `phone_on`, `Phone.connected` and `PHONE_GEN` at
    entry.
  - A sending helper takes the caller's `gen`, then checks `gen ==
    PHONE_GEN and CFG["phone_on"]` under `PHONE_LOCK` and releases the
    lock before `Phone.call`. A reset after that check can't recall a
    write already started, the same as `sms.send` today.
  - Showing phone content does the same check under `PHONE_LOCK` just
    before `STAGES.put`.
- **Lock order.**
  - Never hold `WATCH_LOCK` and `PHONE_LOCK` together.
  - Never call `Phone.call`, `Phone.stop()` or a thread join while holding
    either.
- **Two desktops** act independently. A double reply from both is accepted.
- **Older Flux:**
  - `not_supported` from `notify.send` gives `phone.note_update`;
  - a `RuntimeError` from `sms.thread` or `notification.reply` gives
    `phone.failed`.

### New `lines` strings

These go in `app/lang/en.json`, `nb.json` and `pl.json`:

| Group | Keys |
|---|---|
| Notes | `phone.note_sent`, `phone.note_update`, `phone.note_unsure`, `phone.note_offline` |
| When done | `phone.nothing_running`, `phone.when_done_set`, `phone.when_done_button`, `phone.turn_done`, `phone.turn_stopped`, `phone.turn_failed` |
| Phone tab | `phone.offline_hint`, `phone.fingerprint` |
| Threads | `phone.open_button`, `phone.thread_title`, `phone.thread_empty` |
| Notifications | `phone.notes_title`, `phone.notes_empty`, `phone.notify_none`, `phone.notify_changed`, `phone.notify_sent`, `phone.notify_draft_title` |

Existing keys are reused where they fit: `phone.reply_button`,
`phone.send_button`, `phone.failed`, `phone.not_running`,
`phone.draft_gone`, `phone.draft_open_failed`, `phone.text_length`.

## Execution

Each step runs as **one small Workflow**:
1. The step's implementer (from `coders:`) makes the edits and runs the
   step's check. Codex runs through `herdr-team` `implement`; the coder is
   the Sonnet `coder` agent.
2. Codex reviews the step's diff, read-only, through `herdr-team` `review`.
3. One fix pass handles confirmed findings.

No agent stages, commits, deploys or restarts. Between steps, the lead:
- re-runs the check;
- reviews the diff against the step;
- records any deviation here;
- commits.

The steps run in order, because most of them edit `app/server.py`.

## Steps

1. **`app/phone.py`, `app/server.py`, `app/quick.py` and `app/lang/*.json`:
   client, dispatch guard, strings and phrases.** By the coder.
   - **`Phone.METHODS`** (`phone.py:19-20`) adds the three methods.
   - **`devices()`** (`:113-130`): each row adds `fingerprint` and `ip`.
   - **New `notifications(device)`**, read under `self._lock`:
     - returns `[{id, app, title, text, time, can_reply, rev}]` for that
       paired device;
     - `can_reply = bool(n.get("replyId"))`;
     - `rev = sha256(json.dumps([app, title, text, replyId]))`;
     - never returns `replyId` or `actions`.
   - **Dispatch guard:** `phone_quick` (`server.py:7617-7633`) dispatches
     an explicit set, `{"ring", "clip", "shot", "status", "read",
     "reply"}`. Any other `do` returns `None`, so it is not handled and
     goes on to the agent, and it never reaches `phone_share`. Today an
     unknown action falls through to `phone_share` (`:7630`), which sends
     the clipboard (`:7507`). Steps 2 and 5 add their actions to the set.
   - **Strings:** every key in the table above, in all three languages.
   - **Phrases**, new `phrases` keys in all three files:
     - `phone_when_done`: exact phrases, such as "tell my phone when this is
       done", "tell my phone when it's done" and "ping my phone when you're
       done";
     - `phone_note`: "tell my phone {text}" and "send my phone a note:
       {text}";
     - `phone_notes`: "show my phone notifications";
     - `phone_notify_reply`: "answer {name} on my phone: {text}".
   - **Parsing** in `quick.handle`:
     - It happens where `phone_reply` is parsed (`:376-385`), on the
       case-kept `phone_text` and before the 120-character guard (`:386`).
     - The order is: `phone_when_done`, which gives `{"phone": {"do":
       "when_done", "name": …}}`; then `phone_note`, which gives `{"do":
       "note", "text"}` with 1–200 characters, case kept; then
       `phone_notify_reply`, which gives `{"do": "notify_reply", "name",
       "text"}`.
     - `phone_notes` joins the exact-match list in `_phone` (`:346-355`)
       as `{"do": "notes"}`.
   - **Tests** in the new `tests/test_phone_flux_more.py`:
     - the exact `METHODS` set;
     - the `devices()` fields;
     - `notifications()`: `rev` changes with the text or `replyId`, and no
       `replyId` key is returned;
     - for each of `note`, `when_done`, `notes` and `notify_reply`,
       `phone_quick` returns `None`, and `phone_share` (`:7503`, where
       the clipboard is read) is never called (patched);
     - "tell my phone when this is done" gives `when_done`, not a note;
     - a 200-character mixed-case note is kept, and 201 characters isn't a
       note;
     - "tell the build session: x" still gives `session_send`;
     - each language's phrases parse;
     - every new key exists in all three languages.
   - **Verify:**
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py test_phone_flux_more.py test_phone.py test_sessions.py test_stage_actions.py
     ```
   - *Deviations (step 1):*
     - `rev` hashes `json.dumps(parts)`, not a NUL join, because a NUL in
       a field could make two notifications collide (Codex review).
     - The new phrase block is parsed *before* the `phone_reply` loop.
       Nynorsk's `svar {name} {text}` would otherwise turn "svar Ola på
       telefonen min: Ja" into a plain reply. The order among the three
       new phrases is kept.
     - `when_done` matching ignores trailing `.!?` and curly apostrophes.
       Notes keep their punctuation.
     - `tests/test_phone.py`'s "refused method" example changes from
       `notification.reply` (now allowed) to `notification.dismiss`.
     - The nb and pl wording is the coder's own and needs a native check.
   - **Traps:**
     - Tests use `_ServerEnv`/`nixi_env`, never the real HOME (#176), and
       open no socket.
     - `lang.load` caches: add keys to every file that has `phone_reply`.

2. **`app/server.py`, `app/stages.py` and `index.html`: notes now and "when
   done".** By Codex.
   - **State:** `State.__init__` (`server.py:379`) adds
     `self.active_turn = None`.
   - **`phone_choose`** (`:7384`) gets capability `note`: paired and
     online, no plugin needed.
   - **`phone_note(dev, text, gen)`:**
     - The `gen` check follows the rule under "Off means off".
     - It calls `Phone.call("notify.send", device=dev["id"], title="Nixi",
       body=text)`.
     - On success it replies `phone.note_sent`.
     - `RuntimeError` containing `not_supported` gives `phone.note_update`;
       any other `RuntimeError` gives `phone.failed`.
     - `TimeoutError` gives `phone.note_unsure`, with no retry.
     - `NotSent` or `ConnectionError` gives `phone.not_running`.
   - **Active turn and outcome**, in the chat handler:
     - **Turn start.** At the `TURN` increment (`:9488-9494`), inside the
       existing `with WATCH_LOCK:` block and keeping its `SENDS.pop` and
       `send_watch` assignment as they are, add `ST.active_turn = turn`.
       Before the run, set `outcome = {"v": "failed"}`.
     - **Outcome tracking.** Wrap `emit` and `run_emit` in one recorder:
       - `result` with `is_error` false gives `done`;
       - `result` with `is_error` true, or `error`, gives `failed`;
       - `stopped` gives `stopped`.
       - An exception keeps the default, `failed`.
     - **Turn end.** In the `finally` (`:9527-9531`), inside the existing
       `with WATCH_LOCK:` (keep `ST.send_watch = None`):
       1. Set `slot = PHONE_WHEN_DONE` if its `turn == ST.active_turn`,
          else `None`.
       2. Set `PHONE_WHEN_DONE = None`, then `ST.active_turn = None`.
       
       Then, outside the lock, call `phone_fire(slot, outcome["v"])`.
   - **Arming, `phone_when_done(dev)`:** under `WATCH_LOCK`:
     - if `ST.active_turn is None`, reply `phone.nothing_running`;
     - else store `PHONE_WHEN_DONE = {"turn": ST.active_turn, "device":
       dev["id"], "name": dev["name"], "gen": PHONE_GEN, "at":
       time.monotonic()}`, replacing any earlier one, and reply
       `phone.when_done_set`.
   - **`phone_fire(slot, outcome)`:**
     - Drop the slot if any of these holds:
       - it's `None`;
       - `slot["gen"] != PHONE_GEN`, or Phone is off;
       - it's 1800 s old or more;
       - the device isn't among the paired `Phone.devices()`.
     - If the device is offline, show `BUS.pub(t="note",
       text=lang.t("phone.note_offline", name=…))`.
     - Otherwise start a daemon thread that runs `phone_note(dev,
       lang.t("phone.turn_" + outcome), slot["gen"])`.
   - **The device chooser, with a pending action:**
     - **One device:** both `do="note"` and `do="when_done"` act on it
       directly.
     - **Several devices and no name:** `phone_pick_card(devs, do,
       pending)` puts `phone_pick` with `do` and one button per device.
       The `pending` data is server-side only:
       - `text`, for a note;
       - `turn = ST.active_turn` (read under `WATCH_LOCK`), for when-done;
       - `gen`.
     - **`stages.Store.put`** (`app/stages.py`), for `phone_pick` with `do`
       of `note` or `when_done`: each device button gets a `pick` token
       mapped to `("phone_pick_note", {"device": id, "do": do, **pending})`.
       The page receives tokens, never text or turn.
     - **`POST /api/phone/pick {token}`** (window token):
       1. Look up the `phone_pick_note` entry. A missing or expired token
          gives 410 with `phone.draft_gone`.
       2. Check `gen == PHONE_GEN`.
       3. For `note`, call `phone_note(dev, text, gen)`.
       4. For `when_done`, arm only if `turn == ST.active_turn` (under
          `WATCH_LOCK`); else reply `phone.nothing_running`. A stale
          chooser never binds to a later turn.
     - **`stagePhone`** (`index.html:3130-3137`) posts `/api/phone/pick
       {token: d.pick}` when `ev.do` is `note` or `when_done`. Ring and
       share stay as they are.
   - **The quick path:** `note` and `when_done` join the dispatch set, and
     `phone_quick` routes them as above. A named device uses
     `phone_choose`.
   - **The click: `POST /api/phone/when-done`** (window token) does the
     same as the voice `when_done`, with no name.
   - **Unpaired:** `phone_state` (`:7296`) takes `WATCH_LOCK`. If
     `Phone.connected` and the slot's device isn't among the paired
     `Phone.devices()`, it drops the slot.
   - **`phone_reset`** (`:7646`): after its own `PHONE_LOCK` block, it
     takes `WATCH_LOCK` separately and sets `PHONE_WHEN_DONE = None`.
   - **The button** (`index.html`) is a new `<button id="phoneDone">`, a
     sibling of `#chip`, not inside it:
     - The chip has `pointer-events:none` (`:422`), and `workChip()`
       rewrites its contents every second (`:3461-3465`).
     - The button sits next to the chip and has `pointer-events:auto`.
     - It shows while `busy && info.phone_on && (info.phone_devices || []).some(d => d.online)`.
     - It's updated from `workChip()`'s busy branch, and hidden when not
       busy.
     - A click posts `/api/phone/when-done` and ticks the reply.
     - It never touches `#chip.act` (the attention action, `:436`).
   - **Tests:**
     - **A note now:**
       - one device;
       - several devices, through the full chooser: the `pick` token, then
         `/api/phone/pick`, then one `notify.send` with the text;
       - `not_supported`;
       - a timeout with no retry.
     - **When done:**
       - it's refused when `active_turn` is `None`;
       - armed, it fires once each for `done`, `stopped` and `failed`,
         with the generic body;
       - an arm racing the `finally` (threads plus an `Event`) gives
         neither a lost slot nor two sends;
       - it's dropped by a generation change, at 1800 s, when offline,
         and when unpaired (including unpaired, then paired again);
       - switching Phone off and on while `Phone.call` is blocked sends
         nothing;
       - a stale chooser token after the turn ended doesn't arm;
       - the existing `SENDS`/`send_watch` tests still pass.
     - **Tokens:** `TOOL_TOKEN` gets 403 on `/api/phone/when-done` and
       `/api/phone/pick`.
     - **The page:** a source check that `#phoneDone` sits outside `#chip`
       and that `stagePhone` routes `note` and `when_done` to
       `/api/phone/pick`.
   - **Verify:**
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py test_phone_flux_more.py test_phone.py test_show_agent.py test_phone_fit.py
     ```
   - *Deviations (step 2):*
     - **`PHONE_SEND_LOCK`** (Codex review). `phone_note` holds it across
       its generation check and `Phone.call`. `phone_reset` takes it once,
       after bumping `PHONE_GEN` and before `Phone.stop()`. So a note past
       its check leaves on the old connection, and none crosses a reset.
       The lock order is send lock, then `PHONE_LOCK`. Reset never holds
       both, so there's no cycle. A reset can wait up to the 10 s call
       timeout.
     - **`phone_pick_card(devs, do, pending, gen)`** checks `gen` and
       `phone_on` before publishing the chooser.
     - **`phone_note_say`** publishes a failed when-done send as a desktop
       note.
     - **Online-only `phone_devices`** go out in `phone_pub` already, for
       the 📱 button. Step 3 adds the full rows.
     - **The 📱 button** is also hidden in the bar, peek and hover modes,
       where the chip hides.
   - **Traps:**
     - `WATCH_LOCK` is also taken in `run_bridge` (`:6592`, `:6652`).
       Never call out while holding it.
     - #96's `SENDS`/`send_watch` behaviour stays exactly as it is.

3. **`app/server.py` + `index.html`: the Phone tab.** By the coder.
   - **`phone_devices()`** returns one row per paired device:
     - `name`: `mail_scrub([mail_clean(name, 60)])[0]`;
     - `online`;
     - `last_seen_ago`, from `_phone_ago`;
     - `charge` and `charging`;
     - `fingerprint`, in groups of 4;
     - `ip`;
     - `hint`: `lang.t("phone.offline_hint")` when offline.
     
     With Phone off or disconnected, it returns `[]`.
   - **`state_info`** adds `phone_devices`. **`phone_pub`** (`:7207`) sends
     `devices=phone_devices()` alongside `status`.
   - **`renderPhone()`** (`index.html:4159`) lists the rows under
     `#phoneStat` with `textContent` only. The `phone` bus handler
     (`:2817`) stores `ev.devices` in `info.phone_devices`.
   - **Tests:**
     - the row keys are exactly the ones listed;
     - no number, message or notification text appears;
     - the hint appears only when offline;
     - the result is `[]` when Phone is off.
   - **Verify:**
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py test_phone_flux_more.py test_phone.py test_phone_fit.py
     ```
   - *Deviations (step 3, Codex review):* each row also has `status`, the
     translated `_phone_where(d)`, so the page never hard-codes "online".
     `phone_pub` builds its message, then publishes under `PHONE_LOCK`
     only if `PHONE_GEN` is unchanged, so a reset's empty event always
     comes last.
   - **Traps:**
     - `phone_status()` stays the one-line summary.
     - The plugin feed gets no device rows.

4. **`app/server.py`, `app/stages.py` and `index.html`: threads.** By the
   coder.
   - **`phone_read_messages`** (`:7540`) adds `thread` to each row it puts.
   - **`Store.put`** for `phone_sms` (`stages.py:466-473`) adds an `open`
     token per row, mapped to `("phone_thread", {"device", "thread",
     "number", "name"})`. The page row never gets `thread`.
   - **`POST /api/phone/thread {token}`** (window token):
     1. Take `gen = PHONE_GEN`.
     2. Look up the `phone_thread` token; a missing one gives 410.
     3. Call `Phone.call("sms.thread", device=…, thread=…)`. A
        `RuntimeError` or timeout gives `phone.failed`.
     4. Run the show-content check (see "Off means off"), then put stage
        `phone_thread`:
        - up to 100 messages, oldest first, each `{name, body, outgoing,
          time}`;
        - `name` and `body` are `mail_scrub([mail_clean(name, 100),
          mail_clean(body, 500)])`;
        - one **Reply** token, reusing `("phone_reply", {device, number,
          name})`, so `/api/phone/draft` works as it does today;
        - `from_phone`.
   - **`phone_on_screen()`** (`:7073`) adds `phone_thread`.
   - **`index.html`:**
     - an **Open** button on `phone_sms` rows (`row.open`), posting
       `/api/phone/thread`;
     - a `phone_thread` renderer next to the `phone_sms` one, built with
       `textContent` only;
     - `stageText()` (`:3381`) returns `''` when `ev.from_phone`.
   - **Tests:**
     - the thread comes from the token, and a device or thread in the
       request body is ignored;
     - split-field OTP scrubbing: a name of "Verification" and a body of
       "123456" are hidden;
     - a reply that arrives late, after `phone_reset`, isn't put;
     - `phone_reset` closes the stage;
     - `TOOL_TOKEN` gets 403;
     - a source check of `stageText`.
   - **Verify:**
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py test_phone_flux_more.py test_phone.py test_phone_fit.py test_stage_actions.py
     ```
   - *Deviations (step 4):*
     - `phone_thread` joins `stages.Store._keep`'s private kinds, which
       never come back through the back history.
     - `phone_sms` gets an `open_label` field for the button.
     - (Codex review) The thread stage is put *and* published under
       `PHONE_LOCK`, so a reset's `stage_close` can't come first.
     - (Codex review) A late `sms.thread` reply is dropped with 410
       unless stages are on and the originating stage is still current
       (`STAGES.get(token)`), so it never covers a newer draft.
   - **Trap:** never send a device ID, thread ID or number to the page.

5. **`app/server.py`, `app/stages.py` and `index.html`: answering
   notifications.** By Codex.
   - **`phone_notes_stage(text=None, only=None)`:**
     - For each paired device, take up to 10 notifications, newest first.
       It doesn't matter whether the device is online. Sending checks
       that it's online.
     - Each row shows `app`, `title` and `text`:
       `mail_scrub([mail_clean(app, 60), mail_clean(title, 100),
       mail_clean(text, 300)])`.
     - `only` restricts the list to the given `nid`s. The dictated `text`
       is carried.
     - The stage is `phone_notes`, with `from_phone`.
   - **`Store.put`** for `phone_notes`:
     - rows with `can_reply` get a `reply` token mapped to
       `("phone_note_reply", {device, nid, rev, app, title, text: carried
       text})`;
     - the page row has only `app`, `title`, `text` and `reply`.
   - **Quick:**
     - **`notes`** puts the list.
     - **`notify_reply`** matches `can_reply` rows by case-folded title:
       - one match opens the draft directly, with the text;
       - several put the list with `only` set to those matches and the
         text carried;
       - none replies `phone.notify_none`.
     - Both join the dispatch set.
   - **`POST /api/phone/note-draft {token}`** (window token):
     - It looks up `phone_note_reply` and checks `gen`.
     - It sets `PHONE_NOTE_DRAFT = {id: secrets.token_urlsafe(18), device,
       nid, rev, app, title, gen, created}`, one at a time.
     - It puts stage `phone_note_draft`, with `from_phone`, holding:
       - `draft`, the opaque `id`;
       - the scrubbed `app` and `title`;
       - the editable `text`;
       - `send_label`, `length_error` and `send_error`.
   - **`POST /api/phone/note-reply {draft, text}`** (window token,
     `keyed`, as `phone_send` at `:7101`):
     1. **Under `PHONE_LOCK`**, every one of these must hold:
        - `draft == PHONE_NOTE_DRAFT["id"]`;
        - its `gen == PHONE_GEN`, and Phone is on;
        - it's under 600 s old;
        - the text is 1–1000 characters, with no whitespace-only text;
        - the device is online;
        - `Phone.notifications(device)` has a row with that `nid` and the
          same `rev`.
        
        Then set `PHONE_NOTE_DRAFT = None`, consuming that exact draft.
        On a mismatch, drop it and reply `phone.notify_changed`.
     2. **Outside the lock**, call `Phone.call("notification.reply",
        device=…, id=nid, message=text)`.
     3. **On `NotSent`**, restore the draft when the slot is empty and
        `gen` still matches. A `TimeoutError` or `RuntimeError` doesn't
        restore it: it replies `phone.failed`, since a lost reply may mean
        the reply went.
   - **`phone_on_screen()`** adds `phone_notes` and `phone_note_draft`.
     **`phone_reset`** sets `PHONE_NOTE_DRAFT = None`.
   - **`index.html`:** renderers for `phone_notes` (**Reply** posts
     `/api/phone/note-draft`) and `phone_note_draft` (**Send** posts
     `/api/phone/note-reply` with `keyed`, as the SMS draft does). Both
     use `textContent` only.
   - **Tests:**
     - a typed reply, through the list, the draft and the send;
     - one dictated match, through the draft and the send, with the text
       prefilled;
     - several dictated matches, through the filtered list, the draft and
       the send;
     - parallel clicks send once;
     - expiry;
     - a `rev` change or a gone `nid` drops the draft and sends nothing;
     - `NotSent` restores the draft, and a timeout doesn't;
     - the text bounds;
     - `TOOL_TOKEN` gets 403 on both endpoints;
     - nothing is left after `phone_reset`;
     - split-field OTP scrubbing in a row.
   - **Verify:**
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py test_phone_flux_more.py test_phone.py test_phone_fit.py test_stage_actions.py
     ```
   - *Deviations (step 5, Codex review):*
     - `phone_note_reply` holds `PHONE_SEND_LOCK` across the check, the
       consume and `Phone.call`, as `phone_note` does. A reset therefore
       waits for a reply that passed its check.
     - A missing draft, or a mismatched draft id, answers
       `phone.notify_changed` without clearing the current draft, so a
       stale click can't delete a newer one.
   - **Traps:**
     - The draft is consumed before Flux is called.
     - Only `NotSent` restores it.

6. **`docs/GUIDE.md` and the whole suite.** By the coder.
   - The phone section documents:
     - the new phrases in each language;
     - the 📱 button;
     - the Phone tab;
     - **Open** on a conversation;
     - phone notifications.
   - It also states the limits:
     - a note is generic and never queued;
     - replies are click-only;
     - the notification-change window;
     - what's out of scope.
   - **Verify:**
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py --exclude test_character_fit.py --exclude test_accessories_fit.py
     nix develop .#ci -c python3 -B .github/ci/run_tests.py --deadline 1800 test_character_fit.py test_accessories_fit.py
     ```

### Lead, after step 6

- **Reviews:**
  - a fresh Opus agent, given this plan and `git diff origin/main`;
  - Codex `review --base main`.
- **The PR:**
  - links the intent, spec and plan;
  - says which steps Codex and the coder did;
  - gets a "@codex review" comment.
- **Merge** after green CI. Then bump the `nixi-companion` input in
  nixos_config, from a clean worktree at `origin/main`.
- **Deploy** to p620 (`nh os switch .`) and razer
  (`just deploy-via-p620 razer`), as for #99:
  - Read the agent bus and post first.
  - Copy `~/.config/nixos/nixarchy-theme.nix` into the worktree if it
    differs. It's live but uncommitted, so leaving it out would change the
    theme.
  - Never build or deploy on p510.
- **Live checks** on p620, with the phone:
  - a note now;
  - "when done" during a turn;
  - the Phone tab;
  - **Open** on a conversation;
  - **Reply** to a notification.

## Tests

- Every new test goes in `tests/test_phone_flux_more.py`.
- The existing `test_phone.py`, `test_phone_fit.py`, `test_stage_actions.py`,
  `test_sessions.py` and `test_show_agent.py` pass unchanged.
- The full suite and the fit tests pass (step 6).

## Rollback

- **Before the merge:** close the PR and delete the branch.
- **After the merge:** revert the merge commit and bump nixos_config
  again. Nothing migrates: the new state is in memory, and no config keys
  are added.
