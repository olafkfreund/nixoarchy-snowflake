---
status: draft
issue: 105
spec: spec/2026-11-18-105-otp-clipboard-pause.md
coders:
  1: coder    # two small, mechanical phone.py edits plus tests
  2: codex    # small, tricky gate logic where a slip leaks a code to the screen
  3: codex    # small, tricky concurrency and accounting (lock, unconfirmed requests, session)
  4: coder    # prose in GUIDE.md and three lang strings
reviewers:
  - codex     # a branch review (`codex review --base origin/main`) after step 4, on top of the Opus review
---

# Plan: pause Flux clipboard sharing while a one-time code is around

## Approved decisions, carried over

- **Trigger:** a notification row whose full raw text matches `Inbox.OTP` or `SECRET_LINE`, whatever `notify_details` says.
  Notifications only: `mail_otp` is untouched.
- **The same full-text verdict also blanks the row's text.** This closes the cut-text leak; it never shows more than today.
- **The pause:** `Phone.call("clipboard.pauseOwned", owner="nixi-otp", expires=120)`, made from one worker thread, never
  inline.
  - `Phone.METHODS` gains only `clipboard.pauseOwned`.
  - Nixi never calls `resumeOwned`, `pause` or `resume`.
- **Dedupe:** by row key, at most 64 keys, each forgotten after 10 min.
- **Coalescing:** a `pending` count, taken under a lock before the call. Arrivals during the call go to the next turn.
- **Bound:** at most 5 requests per hold.
  - A hold ends when `until`, the latest time Nixi's pause may still be in force, has passed. Only then does `sent` reset.
  - Unconfirmed requests push `until` to `call start + 120`: a timeout or connection error after the write, a bad
    reply, or a good reply from a changed session.
  - `NotSent`, and an eligibility check that fails, give `sent` back.
- **Eligibility:** `CFG.get("phone_on") is True`, `Phone.connected`, and `"clipboardPauses"` in `Phone.snap`.
- **Session check:** a good reply counts only when `Phone.session` is unchanged since the work was taken. `Phone.session`
  is a new counter that rises once per live connection.
- **Toast:** each confirmed request publishes `BUS.pub(t="toast", text=lang.t("phone.clip_paused"))`. The single chip
  updates in place.
- **Failures:** at most one stderr line per process, `[nixi] code pause: <ExceptionType>`. No retry. No row text anywhere.
- **No new route or setting.** The `flux-cli` policy (`server.py:962`) is unchanged.
- **Deploy:** nixos_config bumps `nixarchy-flux` `6eb6347` → `8267293` and `nixi-companion` to the #105 merge, for p620
  and razer. p510 doesn't run Flux.

## Steps

1. **`app/phone.py`: the allowlist and `Phone.session`**
   - Add `"clipboard.pauseOwned"` to `METHODS` (`:20`–`:22`).
   - Add `self._session = 0` in `__init__`, and `self._session += 1` where the reader sets `self._connected = True`
     (`:261`).
   - Add a read-only `session` property under `self._lock`, like `connected` (`:98`).
   - Tests, in `tests/test_phone.py`, using `FakeFlux` (`:48`):
     - `Phone.call("clipboard.pauseOwned", owner="nixi-otp", expires=120)` sends exactly that method and params and
       returns the fake's `{"expires": n}`;
     - `clipboard.resumeOwned`, `clipboard.pause` and `clipboard.resume` raise `ValueError`;
     - `session` rises by 1 on a reconnect and not on a second snapshot.
   - Verify: `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_phone.py test_phone_flux_more.py`
   - Traps:
     - `_session` is changed only under `self._lock`, as `_connected` is;
     - `Phone.call` must never run on the reader thread (`:193`);
     - tests use the existing `FakeFlux`/`_FluxCase` helpers, not a real socket path.

2. **`app/server.py` `Inbox.rows` (`:3305`–`:3373`): the full-text verdict, and the hook**
   - After the key and category checks, compute `hit` from untruncated text:
     - `str(x.get("summary") or "")`;
     - `str(x.get("body") or "")`;
     - `str(x.get("rich") or "")`;
     - the full `text` of each dict in `x["actions"]` whose `text` is a `str`.
   - The test: `hit = bool(cls.OTP.search(t) or SECRET_LINE.search(t))`, joined with `"\n"`.
   - Line `:3320`: `if not CFG.get("notify_details") or hit or SECRET_LINE.search(...) or cls.OTP.search(...)`. Keep the
     existing tests and add `hit`.
   - Card gate `:3331`: add `or hit` to its condition.
   - Right after `hit` is computed and before any `continue`: `if hit: CodePause.seen(x["key"])`.
     - In this step `CodePause` is a stub in `server.py` with only `seen`, so the step is testable alone. Step 3 fills
       it.
   - Tests, in `tests/test_inbox.py`:
     - **Regression:** with `notify_details` on, the summary `"123456 " + "hello " * 22 + "sign-in code"` returns blank
       `summary`/`body`.
     - **Clean rows:** a row with no code comes back unchanged, with no new keys.
     - **Hook calls:** `CodePause.seen` (patched) is called once with the key for:
       - a code row with `notify_details` off;
       - a `SECRET_LINE`-only row;
       - a button card that the shell keeps (the `showKey` path);
       - a code only in `rich` past 600 characters;
       - a code only in a button label.
     - It is not called for a clean row.
   - Verify: `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_inbox.py test_notify_fit.py`
   - Traps:
     - never log or store row text;
     - tests must use `nixi_env`, or the existing `_ServerEnv`, and never import `server` under the real `HOME`
       (#176);
     - `SECRET_LINE` is defined at module level further down (`:6710`). That is fine at call time, but don't use it at
       class-definition time.

3. **`app/server.py`: `CodePause`, next to `Inbox`, filling the step 2 stub**
   - **Constants:** `OWNER = "nixi-otp"`, `SECS = 120`, `MAX = 5`, `KEEP = 64`, `FORGET = 600`.
   - **State:** `lock`, `wake = threading.Event()`, `keys = {}`, `pending = 0`, `sent = 0`, `until = 0.0`,
     `logged = False`, `thread = None`.
     - `keys`, `pending`, `sent`, `until` and `logged` are read and written only under `lock`.
     - The session number `g` is a local of each turn.
   - **`seen(key)`:**
     - under `lock`: drop keys older than `FORGET`; if `key in keys`, return;
     - otherwise store `keys[key] = time.monotonic()`, evict the oldest past `KEEP`, and do `pending += 1`;
     - then `wake.set()`.
   - **`turn()`, one worker turn,** following the spec's table:
     - Under `lock`, using `now = time.time()`:
       - if `pending == 0`, return;
       - if `until <= now`, set `sent = 0`;
       - if `sent >= MAX`, set `pending = 0` and return;
       - otherwise take the work: `pending = 0`, `sent += 1`, `g = Phone.session`.
     - **Eligibility,** outside the lock. If it fails, under `lock` do `sent -= 1` and return.
     - **The call:** `start = time.time()`, then `Phone.call(...)`.
     - **Account under `lock`,** per outcome:

       | Outcome | `until` | `sent` | Shown |
       |---|---|---|---|
       | `phone.NotSent`, checked **before** `ConnectionError`, since it subclasses it | unchanged | `-= 1` | nothing |
       | `TimeoutError` or `ConnectionError` | `max(until, start + SECS)` | kept | nothing |
       | `RuntimeError` or `ValueError` | unchanged | kept | nothing |
       | A reply that isn't a dict with an `int` (not `bool`) `expires > time.time() + 1` | `max(until, start + SECS)` | kept | nothing |
       | `Phone.session != g` | `max(until, start + SECS)` | kept | nothing |
       | Otherwise | `max(until, expires)` | kept | toast, published after the lock is released |

     - Every failure branch calls `_log(exc_or_reason_type)`, which prints once per process.
   - **`loop()`:** `while True: wake.wait(); wake.clear(); turn()`, inside `try/except Exception`, as `Inbox.loop` does
     (`:3428`). After `turn()`, read `pending` under `lock`; if it is above 0, set `wake` again, so arrivals during the
     call are sent.
   - **Start:** `Inbox.start()` (`:3435`) also calls `CodePause.start()`. That starts one daemon thread, only if
     `CodePause.thread` is unset.
   - **Strings:** add `phone.clip_paused` to the three lang files, next to `phone.off`:
     - `en.json:62`: "Clipboard sharing paused for the code"
     - `nb.json:62`: "Deling av utklippstavlen er satt på pause for koden"
     - `pl.json:123`: "Udostępnianie schowka wstrzymane na czas kodu"
   - **Tests,** in a new `tests/test_code_pause.py`, under `nixi_env`. They call `turn()` directly, with `Phone.call`,
     `Phone.session`, `Phone.connected`, `Phone.snap`, `time.time` and `BUS.pub` patched, plus one threaded test:
     - **The request:** exactly `("clipboard.pauseOwned", owner="nixi-otp", expires=120)`.
     - **Dedupe:**
       - the same key again does nothing;
       - the 65th key evicts the oldest, which then counts as new;
       - a key older than 600 s counts as new.
     - **Coalescing:** 3 keys before one `turn()` send 1 request.
       - **Threaded:** `Phone.call` blocks on an `Event`. `seen()` of a new key returns at once, and the following
         turn sends it.
     - **The bound:**
       - the 6th request in a hold is dropped;
       - after `until` passes, requests go out again.
     - **Unconfirmed requests:**
       - a hold is confirmed to t=120;
       - a renewal starts at t=119 and raises `TimeoutError`;
       - at t=130, a new code still counts in the same hold (`sent` is not reset).
     - **Accounting per outcome:** one table-driven test asserts `sent`, `until` and the toast for every row of the
       table:
       - `NotSent`;
       - `TimeoutError`;
       - a plain `ConnectionError`;
       - `RuntimeError`;
       - `ValueError`;
       - each bad reply: `{}`, `{"expires": "x"}`, `{"expires": True}`, `{"expires": now - 5}`, `None`;
       - a good reply from a changed session;
       - a good reply.
       - Stderr gets exactly one line over all failures, and it holds no row text.
     - **Session change:** a hold is confirmed, then a renewal gets a good reply from a changed session. A new code
       after the old `until` still counts in the same hold.
     - **Start:** calling `Inbox.start()` twice starts one `CodePause` thread.
     - **Not eligible:** nothing is sent with Phone off, when not connected, or with no `clipboardPauses` key; `sent` is
       given back. `clipboardPauses: []` is enough to send.
     - **The toast:** 2 confirmed renewals publish the same toast twice.
   - Verify:
     ```bash
     nix develop .#ci -c python3 -B .github/ci/run_tests.py test_code_pause.py test_inbox.py test_phone.py test_lang.py test_lang_words.py
     ```
   - Traps:
     - `phone.NotSent` must be caught before `ConnectionError`;
     - `bool` is an `int` subclass, so check `type(...) is int`;
     - never call `Phone.call` while holding `CodePause.lock` or from the reader thread;
     - publish the toast outside the lock;
     - all three lang files get the key, or `test_lang` fails;
     - no new HTTP route.

4. **`docs/GUIDE.md:163`: the paragraph**
   - Replace "pausing the clipboard from Nixi" in the "Not included" line with a short paragraph under the Phone section
     (`:133`–`:165`). It covers:
     - **The trigger:** a notification with a code or secret, while Nixi takes notifications over.
     - **How long:** 2 min, renewed by a new code, for about 10 min at most, then not again until it has run out.
     - **The limits:**
       - only while notifications are taken over;
       - a copy made before the notification can still go out;
       - a send already past Flux's check still goes out;
       - a notification seen again after 10 min, or after 64 other code notifications, counts as new.
     - **The costs:**
       - copies made during the pause aren't shared and stay out of Flux history;
       - copying the same value again after it may not sync;
       - manual sends still work.
     - **Restarts:** a `fluxd` restart drops it.
   - Verify: read it back, and run
     `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_docs_names.py`.
   - Traps: keep the GUIDE's plain, short style; no promises beyond the spec.

5. **Lead only: checks, the PR, then nixos_config**
   - **Checks:**
     - the full suite: `nix develop .#ci -c python3 -B .github/ci/run_tests.py --exclude test_character_fit.py --exclude test_accessories_fit.py`;
     - the fit tests: `nix develop .#ci -c python3 -B .github/ci/run_tests.py --deadline 1800 test_character_fit.py test_accessories_fit.py`;
     - the README's sandbox tests, if this change needs them.
   - **Reviews:** Opus on the plan plus `git diff origin/main`, then `codex review --base origin/main`.
   - **The PR:** it links all three files, names the coders per step, and gets "@codex review".
   - **After merge:** a nixos_config branch from a clean `origin/main` worktree, with `nixarchy-theme.nix` copied in:
     - `nix flake update nixarchy-flux nixi-companion`;
     - confirm the locks show `8267293` and the #105 merge.
     - Open its PR; it merges after CI.
   - **Deploy:**
     - p620: `AGENT_BUS_ANNOUNCED=1 nh os switch .`
     - razer: `AGENT_BUS_ANNOUNCED=1 just deploy-via-p620 razer`, using `NIX_SSHOPTS` with the Tailscale host name if
       razer is off the LAN.
     - Announce on the agent bus first.
     - Restart Nixi on both, with the live Hypr signature.
   - **Runtime check** on p620, as in the spec:
     1. `clipboardPauses` is empty;
     2. `notify-send "Your sign-in code" "123456"` shows the toast, and `nixi-otp` appears about 120 s out;
     3. a second, different code notification within 2 min moves the expiry and updates the toast;
     4. after the pause runs out, the list is empty.
   - Traps:
     - deploy from a clean worktree, never a dirty `~/.config/nixos`;
     - copy the uncommitted theme file in;
     - no p510;
     - no gh polling loops.

## Tests

| Command | Expected |
|---|---|
| Step checks 1–4 | pass |
| Full suite, without the fit tests | pass, as on `main` |
| Fit tests | pass |
| Runtime on p620 | the toast; `nixi-otp` listed about 120 s out, then gone |

## Rollback

- **Nixi:** revert the #105 merge commit on `main`, then move nixos_config `nixi-companion` back to `a6c2124`.
- **Flux:** move `nixarchy-flux` back to `6eb6347`. #77 only adds methods, so the old Nixi works on the new Flux and the
  reverse.
- Re-deploy p620 and razer.
