---
status: draft
issue: 91
intent: intent/2026-11-15-91-react-calm-flake.md
---

# Spec: the react_fit "calm" blocker stops flaking

## What the code shows

- **The app owns `body.calm`.** `calmCheck()` (`app/static/index.html:4650`) sets it to "a panel is open": Settings
  (`setEl`), the side panel (`panelEl`) or the approval card (`apEl`). `sendRegion()` calls it first, before its
  `NATIVE` check (`:4670`), so it runs in the test page too. `sendRegion(` appears 41 times, so 40 call sites.
- **The test fakes calm with the class alone** (`tests/react_fit.mjs:67`, `"calm": "document.body.classList.add('calm')"`).
  With no panel open, the next `calmCheck()` takes the class back off. Section 1 then waits 60 ms before
  `rxPlay('rain')` (`:71`), so rain plays whenever a `sendRegion()` lands in that window.
- **The CI failure fits that route, but the exact trigger isn't known.** The log shows only the result
  (`[true,false,{"id":"rain"}]`). The mechanism is shown below by forcing it (Verification).
- **Section 3 uses the same faked class** (`arrive` takes `blockers.calm`, `undo.calm` removes the class, `:80-90`). If
  `calmCheck()` runs there, calm drops early. The case can then fail, or pass without calm holding at the moment
  the checks look.
- **The other faked classes are written by the app too, but not by a routine sweep:**
  - `hover`: only `setHoverClass()` (`:3858`), on a real hover change.
  - `bar`: only the notch animation (`:3936-3950`).
  - `peek`: only `setIdle()` (`:4723`), on an idle state change.

  None is recomputed on every `sendRegion()` the way `calm` is, so they stay as they are (see Risks).
- **A second route, found in review (agy): the state poll.** `refresh()` runs every 15 s (`:4964`) and replaces
  `info` with the reply from `/api/state` (`:4626-4629`). The test's `fetch` shim (`tests/react_fit.mjs:26-27`) forces
  `proactive:true, reactions:true` into that reply, to keep the flags the test turned on. So a poll that lands while
  "reactions off" or "proactive off" is being tested turns the blocker back off:
  - in section 2, inside the 60 ms wait: about 0.4% per case
  - in section 3, inside the wait of up to 2 s: up to about 13% per case

  It's the same kind of flake as calm, in the same table, so it's fixed here too. That goes slightly past the
  intent's wording ("the calm cases"); approving this spec covers it.
- **Other fit tests:** `grep -n "'calm'" tests/*.mjs` finds the faked class only in `react_fit.mjs`.
  `stages_fit.mjs:511` and `mirror_fit.mjs:114` only clear or read it.

## Design

In `tests/react_fit.mjs` only:

1. **Calm comes from an open Settings panel.** In `blockers`, `"calm"` becomes
   `"setEl.classList.add('on'); calmCheck()"`. `calmCheck()` then keeps calm on, because a panel really is open.
   - Adding the class to `setEl` only, not calling `settings(true)`, keeps the case small. `settings()` also renders
     the tabs, loads mics and plugins, and posts `/api/update/check` (`:4063-4068`), none of which the case needs.
   - Settings is the panel `stages_fit.mjs:511` already resets the same way.
2. **Section 3 undoes it the same way.** `undo["calm"]` becomes `"setEl.classList.remove('on'); calmCheck()"`.
3. **`rxReset()` closes it** (`:33-37`). Add `setEl.classList.remove('on');` before the existing
   `document.body.classList.remove(...)`, so no case or section starts with Settings open.
4. **Every blocker case shows a clean start, then a gate holding when it played.** In section 1, the case reads
   `rxBase()` twice: right after `rxReset()` (`base0`), and again just before `rxPlay('rain')`. It returns
   `[ok, empty(), RX, base0, rxBase()]` instead of `[ok, empty(), RX]`, and expects `[false, true, null, true, false]`.
   - `rxBase()` (`:1781`) is false while any of its gates holds. Each blocker in the table maps to one of them
     (checked for all ten in review).
   - `base0 === true` proves the case started clean: no gate, and no leaked panel keeping `calm` on, survived
     `rxReset()`.
   - The later `false` proves *a* gate held at play time. Between the two reads the case sets only its own
     blocker, so it is that one unless another gate switched on by itself within 60 ms. The guard doesn't rule that
     last case out; it does rule out the one that failed on #90, where rain played because no gate held.
   - For calm, the case also returns `document.body.classList.contains('calm')`, expected `true`, so the blocker
     this issue is about is checked by name.

5. **The shim keeps the flags the test set, not fixed `true`s.** In the `fetch` shim (`:27`),
   `proactive:true, reactions:true` becomes `proactive:info.proactive, reactions:info.reactions`. The `look_*` and
   `click_through` values stay as they are.
   - The shim reads the page's own `info` at the moment the reply arrives, so a poll keeps "reactions off" off.
   - Every case still starts with both flags on: `rxReset()` sets them (`:36`).
   - Section 3's `off` for these two (`info.reactions=true;showInfo()`) is unchanged.

The checks stay the same otherwise: no longer waits, no looser expectations, no app change.

## Alternatives rejected

- **Open Settings for real with `settings(true)`:** it brings rendering, network posts and window sizing into a reaction
  test. That's more surface to flake, for no gain.
- **The approval card (`apEl`) or the side panel (`panelEl`):** `apEl` brings a pending approval (`pendingAppr`), and
  `openPanel()` is async and fills content. Settings by class is the smallest real state.
- **Stub `calmCheck` in the test:** it hides the very code that decides calm, so the test would stop matching the app.
- **Drop the 60 ms wait:** it narrows the race but doesn't remove it, and section 3 still has it.
- **Change `calmCheck()` to keep a class it didn't set:** ruled out by the intent (test-only).

## Risks

- **Settings left open leaks into later cases.** `rxReset()` closes it (Design 3), and section 3's `undo` does too.
  The guard in Design 4 catches a leak as `base0 === false` in the next case. `rxReset()` doesn't close `panelEl` or
  `apEl`. Neither is opened by this test, and the same `base0` check would catch it if one were.
- **An open `setEl` also counts as "active" for idle** (`idleActive()`, `:4716`). That holds idle back during the
  calm case only, which is harmless. It is cleared again by `rxReset()`.
- **`hover`, `bar` and `peek` stay faked.** The app changes them only on real events (hover, the notch animation, an
  idle step), not on every `sendRegion()`. `peek` could still flip if the idle timer fires mid-case. That has not been
  seen, and it is left alone here. If it ever flakes, the `rxBase()` guard shows which case it was.
- **The shim's first poll:** before the first `rxReset()`, `info` holds the server's values. The setup runs
  `rxReset()` (`:38`) before any case, so the flags are already `true` by then.
- **CI time:** unchanged. Same cases, same waits.

## Verification

- **Reproduce the race before the fix,** on p620, headless Chromium with `--disable-gpu`, started by the test. Add
  `sendRegion(true);` at the start of the 60 ms wait in the section 1 case. The calm case must fail every run (3 of 3),
  with rain playing. That proves the route.
- **The same forced `sendRegion(true)` with the fix:** the calm case passes 3 of 3.
- Remove the forced call, and check that `git diff` holds only the Design changes.
- **The whole file through the CI runner:**

  ```bash
  nix develop .#ci -c python3 -B .github/ci/run_tests.py --deadline 1800 test_react_fit.py
  ```

  It must be `ok`. The output must show every blocker case with its four values, and the section 3 calm cases
  passing.
- **The poll route, forced:** in the "reactions off" case, call `await refresh()` inside the wait.
  - Before the fix (the shim with `true`s): the case fails 3 of 3.
  - After it: the case passes 3 of 3.
  - Then remove the forced call.
- **The PR's CI:** `test` green.
