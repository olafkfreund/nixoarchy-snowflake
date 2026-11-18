---
status: draft
issue: 100
spec: spec/2026-11-18-100-phone-flux-gaps.md
coders:
  1: coder    # the Flux client: allowlist, device fields, notifications() with rev
  2: coder    # phrase parsing order and lang strings, mechanical across en/nb/pl
  3: codex    # small, tricky: active-turn identity, slot lifecycle, generation rechecks
  4: coder    # Phone tab rows and their rendering
  5: coder    # sms.thread stage from the held stage, scrubbed, caption fallback
  6: codex    # small, tricky: reply draft bound to nid+rev, consume-then-send, NotSent restore
  7: coder    # GUIDE, full suite, fit tests
reviewers:
  - codex     # read-only review of each step's diff and of the whole branch against this plan
---

# Plan: use more of Flux from Nixi's phone feature

The decisions in the approved intent and spec are copied here, so this plan
can be implemented without opening either. Repo and branch:
`/mnt/code/Source-home/GitHub/nixi-100-phone` (nixoarchy-snowflake),
`feat/100-phone-flux-gaps`, from `origin/main` `e352682`. Line numbers
refer to that commit.

## Decisions

- **Scope.** Four features:
  1. "Tell my phone": a note now, or one when the agent turn ends.
  2. A fuller Phone tab.
  3. A conversation's latest 100 texts.
  4. Answering a phone notification.
  
  Incoming-file captions and clipboard pause are out of scope. Clipboard
  pause waits on olafkfreund/nixarchy-flux#77.
- **Flux keeps security.** `Phone.METHODS` grows by exactly `notify.send`,
  `sms.thread` and `notification.reply`. Nixi never calls `settings.set`,
  `pair.*` or `addresses.*`, and never adds remote control or approve
  buttons.
- **Consent.**
  - The agent can't send. Every new endpoint needs the window token and
    refuses `TOOL_TOKEN`, and the agent policy on `flux-cli` and the socket
    stays as it is.
  - A note needs your voice or a click.
  - A reply to someone needs a click on a single-use draft.
- **A "when done" note:**
  - one device, one turn, one send;
  - cancelled by Phone off, a restart (it's in memory), the device being
    unpaired, or 30 minutes;
  - generic text by outcome, never the answer;
  - no retry after `NotSent` or a timeout;
  - never queued for an offline phone.
- **A reply draft** is bound to `{device, nid, rev}`, where `rev` is the
  sha256 of app, title, text and replyId. It's single-use, lives 10
  minutes, and is restored only on `NotSent`.
- **The accepted limit (approved):** Flux can still change a notification
  between Nixi's check and its own lookup of the reply target
  (`internal/core/notifications.go:488`). Nixi catches every change it can
  see.
- **Privacy:**
  - every phone-derived field shown is scrubbed with `mail_clean` and
    `mail_scrub`;
  - the new stage kinds join `phone_on_screen()` (never spoken) and are
    marked `from_phone` (closed by `phone_reset`);
  - `stageText()` returns `''` for `from_phone`;
  - none of this content reaches the status line, the plugin feed, logs
    or agent prompts.
- **Off means off.** Each path checks `phone_on`, `Phone.connected` and
  `PHONE_GEN` at entry, and checks `PHONE_GEN` again under `PHONE_LOCK`
  before each sending `Phone.call` and before showing phone content.
- **Two desktops** act independently. A double reply from both is
  accepted.

## Execution

Each step runs as **one small Workflow**:
1. The step's implementer (from `coders:`) makes the edits and runs the
   step's check. Codex runs through `herdr-team` (`implement`); the coder
   runs as the Sonnet `coder` agent.
2. Codex reviews that step's diff, read-only (`herdr-team` `review`).
3. One fix pass for confirmed findings.

No agent stages, commits, deploys or restarts. Between steps, the lead
re-runs the check, reviews the diff against the step, records any deviation
here, and commits. The steps run in order, because most of them edit
`app/server.py`.

## Steps

1. **`app/phone.py`: the Flux client.**
   - `METHODS` (`:19-20`) adds `notify.send`, `sms.thread` and
     `notification.reply`.
   - `devices()` (`:113-130`): each row adds `fingerprint` and `ip`.
   - **New `notifications(device)`:**
     - It returns, for that paired device, `[{id, app, title, text, time,
       can_reply, rev}]`.
     - `can_reply = bool(n.get("replyId"))`.
     - `rev = sha256("\0".join(app, title, text, replyId))`.
     - It never returns `replyId` or `actions`.
     - It's read under `self._lock`, as the other readers are.
   - Tests in `tests/test_phone_flux_more.py`:
     - the exact `METHODS` set;
     - `devices()` fields;
     - `notifications()` rows: `rev` changes when the text or `replyId`
       changes, and there's no `replyId` key.
   - Verify:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py test_phone_flux_more.py test_phone.py
     ```
   - Traps: tests use `_ServerEnv`/`nixi_env`, never the real HOME (#176),
     and never open a socket.

2. **`app/quick.py` + `app/lang/{en,nb,pl}.json`: phrases.**
   - **New `phrases` keys:**
     - `phone_when_done`: exact phrases such as "tell my phone when this
       is done", "tell my phone when it's done" and "ping my phone when
       you're done";
     - `phone_note`: "tell my phone {text}", "send my phone a note:
       {text}";
     - `phone_notes`: "show my phone notifications";
     - `phone_notify_reply`: "answer {name} on my phone: {text}".
     
     Each language gets its own phrasings, plus the `lines` strings the
     later steps name.
   - **In `handle()`, where `phone_reply` is parsed** (`:376-385`), on the
     case-kept `phone_text` and before the 120-character guard (`:386`), in
     this order:
     1. `phone_when_done` returns `{"phone": {"do": "when_done", "name":
        …}}`;
     2. `phone_note` returns `{"phone": {"do": "note", "text": …}}`, with
        the text 1–200 characters and case kept;
     3. `phone_notify_reply` returns `{"phone": {"do": "notify_reply",
        "name": …, "text": …}}`.
     
     `phone_notes` joins the exact-match list in `_phone` (`:346-355`).
   - Tests:
     - "tell my phone when this is done" gives `when_done`, not a note;
     - a 200-character mixed-case note is kept as typed, and 201 isn't a
       note;
     - "tell the build session: x" still gives `session_send`;
     - each language's phrases parse.
   - Verify:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py test_phone_flux_more.py test_quick.py
     ```
     If there's no `test_quick.py`, use the quick tests that `ls tests`
     shows.
   - Traps: `lang.load` caches. Add the keys to every language file that
     has `phone_reply`.

3. **`app/server.py` + `index.html`: notes now and "when done".** By Codex.
   - **`phone_choose`** (`:7384`) gets the capability `note`: paired and
     online, with no plugin needed. With several devices and no name, the
     caller shows `phone_pick_card` (`:7529`) with `do="note"` or
     `do="when_done"`. `phone_pick_act` (`:7636`) accepts both.
   - **`phone_note(dev, text)`:**
     - Under `PHONE_LOCK`, check `PHONE_GEN` and `phone_on`. Then call
       `Phone.call("notify.send", device=id, title="Nixi", body=text)`.
     - `RuntimeError` with `not_supported` gives
       `lang.t("phone.note_update", name=…)`.
     - `TimeoutError` gives `phone.note_unsure`, with no retry.
     - `NotSent`/`ConnectionError` gives `phone.not_running`.
   - **Active turn.** Set `ST.active_turn = turn` under `WATCH_LOCK` where
     `TURN` increments (`:9488-9491`). In the chat handler's `finally`
     (`:9527-9531`), under `WATCH_LOCK`:
     1. take `PHONE_WHEN_DONE` if its `turn == ST.active_turn`;
     2. set it to `None`;
     3. set `ST.active_turn = None`.
     
     Record the outcome (`done`, `stopped` or `failed`) where the handler
     already knows it.
   - **Arming:**
     - Choose the device outside the lock.
     - Then, under `WATCH_LOCK`: if `ST.active_turn is None`, reply
       `phone.nothing_running`. Otherwise store `PHONE_WHEN_DONE = {"turn",
       "device", "name", "gen": PHONE_GEN, "at": monotonic}`, replacing
       any earlier one, and reply `phone.when_done_set`.
     - Arming comes from the quick `do="when_done"`, through
       `phone_quick` (`:7617`), and from the new `POST
       /api/phone/when-done` (window token).
   - **Firing**, with the slot already consumed:
     - Drop it if `gen != PHONE_GEN`, Phone is off, or it's 1800 s old.
     - If the device is unpaired, drop it silently. If it's offline, show
       the desktop note `phone.note_offline`.
     - Otherwise, a daemon thread runs `phone_note` with
       `lang.t("phone.turn_" + outcome)`.
   - **Unpaired:** in `phone_state` (`:7296`), under `WATCH_LOCK`, drop the
     slot when the device isn't among the paired `Phone.devices()`, with
     the snapshot connected.
   - **`phone_reset`** (`:7646`) also clears `PHONE_WHEN_DONE`.
   - **`index.html`:** while `busy`, a 📱 button inside `#chip` (`.work`,
     `:438`) posts `/api/phone/when-done` and ticks the reply. It's hidden
     when Phone is off.
   - Tests:
     - a note now: one device, several (the pick card), `not_supported`,
       and a timeout with no retry;
     - when done:
       - refused with no active turn, including between taking the lock
         and `TURN`'s increment (simulate `active_turn` `None`);
       - armed, it fires once each on done, stopped and failed, with the
         generic body;
       - a concurrent arm and finish (threads with an `Event`) give
         neither a lost slot nor two sends;
       - dropped by a generation change, at 1800 s, offline, and unpaired,
         including unpaired then paired again;
       - Phone off and on while the send is blocked sends nothing;
     - `TOOL_TOKEN` gets 403 on `/api/phone/when-done`.
   - Verify:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py test_phone_flux_more.py test_phone.py test_show_agent.py
     ```
   - Traps:
     - `WATCH_LOCK` is already taken in `run_bridge` (`:6592`). Never call
       `Phone.call` while holding it.
     - Keep `SENDS`/`send_watch` behaviour from #96 unchanged.

4. **`app/server.py` + `index.html`: the Phone tab.**
   - **`phone_devices()`** returns one row per paired device:
     - `name`, through `mail_clean(…, 60)`;
     - `online`, and `last_seen_ago` (`_phone_ago`);
     - battery `charge` and `charging`;
     - `fingerprint` split into groups of 4;
     - `ip`;
     - `hint = lang.t("phone.offline_hint")` when offline.
     
     With Phone off or disconnected, it returns `[]`.
   - **`state_info`** adds `phone_devices`. **`phone_pub`** (`:7207`)
     sends `devices=phone_devices()` with `status`.
   - **`renderPhone()`** (`index.html:4159`) shows the rows under
     `#phoneStat` as `.note`-style lines, built with `textContent` only.
     The bus `phone` handler (`:2817`) stores `ev.devices`.
   - Tests:
     - the rows' keys are exactly those;
     - no number, message or notification text appears;
     - the hint appears only when offline;
     - `[]` when off.
   - Verify:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py test_phone_flux_more.py test_phone.py
     ```
   - Traps: `phone_status()` stays the one-line summary. The plugin feed
     stays without device rows.

5. **`app/server.py` + `index.html`: threads.**
   - **`phone_read_messages`** (`:7540`) also keeps each row's `thread`
     inside the stage (a server-side field that `stage_event` doesn't
     send). Check `stage_event` (`:6698`), and if every key is sent, keep
     a server-side map `{stage token: [(device, thread)]}` instead.
   - **New `POST /api/phone/thread {stage, index}`** (window token):
     1. Look up the held stage.
     2. Check `PHONE_GEN`.
     3. Call `sms.thread(device, thread)`.
     4. Check `PHONE_GEN` again under `PHONE_LOCK`.
     5. Put stage `phone_thread`: up to 100 messages, oldest first, each
        `{name: scrub(mail_clean(name, 100)), body: scrub(mail_clean(body,
        500)), outgoing, time}`, a **Reply** that reuses
        `phone_reply`/`phone_draft` (`:7078-7099`), and `from_phone`.
   - **`phone_on_screen()`** (`:7073`) adds `phone_thread`.
   - **`index.html`:**
     - an **Open** button on `phone_sms` rows, and a renderer for
       `phone_thread` in the stage code next to `phone_sms`;
     - `stageText()` (`:3381`) returns `''` when `ev.from_phone`.
   - Tests:
     - the thread comes from the held stage, ignoring any device or
       thread in the body;
     - scrubbing;
     - a late reply after `phone_reset` isn't put;
     - `phone_reset` closes it;
     - `TOOL_TOKEN` gets 403;
     - `stageText` (assert on the source, as other page tests do).
   - Verify:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py test_phone_flux_more.py test_phone.py
     ```
     Also run `test_phone_fit.py`.
   - Traps: never send `device`, `thread` or a number to the page.

6. **`app/server.py` + `index.html`: answering notifications.** By Codex.
   - **`phone_notes_stage(text=None, only=None)`:**
     - The stage `phone_notes` lists up to 10 notifications per online
       device, newest first: app, title and text cut to 300 characters,
       all scrubbed. **Reply** appears where `can_reply`.
     - It carries the dictated `text` when given, and is marked
       `from_phone`.
     - Each row's `(device, nid, rev)` stays server-side.
   - **Quick:**
     - `do="notes"` opens the list.
     - `do="notify_reply"` matches by case-folded title among `can_reply`
       rows. One match opens the draft with the text. Several open the
       list filtered to them, carrying the text. None replies
       `phone.notify_none`.
   - **`PHONE_NOTE_DRAFT`**, mirroring `PHONE_DRAFT`:
     - `phone_note_draft(token, index, text)` makes `{id:
       token_urlsafe(18), device, nid, rev, app, title, gen, created}` and
       puts the stage `phone_note_draft`, which is `from_phone`, with only
       the scrubbed app/title and the text.
   - **`POST /api/phone/note-reply {draft, text}`** (window token, `keyed`
     as `phone_send` `:7101`):
     1. Under `PHONE_LOCK`, require all of: a matching id, `gen`, under
        600 s old, text of 1–1000 characters, and a current
        `Phone.notifications(device)` row with that `nid` and the same
        `rev`.
     2. Set `PHONE_NOTE_DRAFT = None`, consuming that exact draft.
     3. After the `PHONE_GEN` recheck, call
        `Phone.call("notification.reply", device=…, id=nid,
        message=text)`.
     4. On `NotSent`, restore it if the slot is empty and `gen` still
        matches. On a mismatch at step 1, drop it with
        `phone.notify_changed`.
   - **`phone_on_screen()`** adds `phone_notes` and `phone_note_draft`.
     **`phone_reset`** clears `PHONE_NOTE_DRAFT`.
   - **`index.html`:** renderers for both stages, built with `textContent`
     only. The draft's **Send** posts with `keyed` as the SMS draft does.
   - Tests:
     - parallel clicks send once;
     - it expires;
     - a `rev` change or a gone `nid` drops the draft and sends nothing;
     - `NotSent` restores, and a timeout doesn't;
     - text bounds;
     - a `TOOL_TOKEN` 403;
     - after `phone_reset`, nothing is left.
   - Verify:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py test_phone_flux_more.py test_phone.py
     ```
   - Traps: the draft is consumed before Flux is called. Only `NotSent`
     restores it, because a lost reply may mean it went.

7. **`docs/GUIDE.md` and the whole suite.**
   - In the phone section of `docs/GUIDE.md`, document the new phrases,
     the 📱 button, the Phone tab, Open on a conversation, and phone
     notifications.
   - State the limits:
     - a note is generic and never queued;
     - replying is click-only;
     - the notification-change window;
     - the out-of-scope items.
   - Verify:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py --exclude test_character_fit.py --exclude test_accessories_fit.py
     nix develop .#ci -c python3 -B .github/ci/run_tests.py --deadline 1800 test_character_fit.py test_accessories_fit.py
     ```

### Lead, after step 7

- **Reviews:**
  - a fresh Opus agent, given this plan and `git diff origin/main`;
  - Codex `review --base main`.
- **The PR**, linking intent, spec and plan, and saying which steps Codex
  and the coder did. Comment "@codex review".
- **Merge** after green CI. Then bump `nixi-companion` in nixos_config and
  deploy to p620 and razer, as for #99: read and post on the agent bus,
  and copy the uncommitted theme file.
- **Live checks on p620, with the phone:**
  - a note now;
  - "when done" during a turn;
  - the Phone tab;
  - **Open** on a conversation;
  - **Reply** to a notification.

## Tests

- `tests/test_phone_flux_more.py` holds every new test.
- The existing `test_phone.py` and `test_phone_fit.py` pass unchanged.
- The full suite and the fit tests pass (step 7).

## Rollback

- **Before the merge:** close the PR and delete the branch.
- **After the merge:** revert the merge commit and bump nixos_config
  again. No data migrates: the new state lives in memory, and no config
  keys are added.
