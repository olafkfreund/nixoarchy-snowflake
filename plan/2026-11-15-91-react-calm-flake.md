---
status: draft
issue: 91
spec: spec/2026-11-15-91-react-calm-flake.md
coders:
  2: codex   # small, tricky test code in one file: browser-side strings inside Node template literals, a per-case guard
reviewers:
  - codex    # whether each forced route really fails before and passes after (not independent of step 2; agy and the fresh Opus review are)
  - agy      # an independent read of the diff against the spec
---

# Plan: the react_fit "calm" blocker stops flaking

## Summary of the approved spec

Test-only, in `tests/react_fit.mjs`. No app change.

- **Route 1, `calmCheck()`:** the page owns `body.calm`. `calmCheck()` (`app/static/index.html:4650`) sets it to "a
  panel is open" (`setEl`, `panelEl`, `apEl`), and every `sendRegion()` calls it, in the test page too (`:4669-4671`).
  The test fakes calm with the class alone, so the next `sendRegion()` clears it.
- **Route 2, the state poll:** `refresh()` runs every 15 s (`:4964`) and replaces `info` with `/api/state`
  (`:4626-4629`). The test's `fetch` shim forces `proactive:true, reactions:true` into that reply, so a poll during
  "reactions off" or "proactive off" clears that blocker.
- **The fix:**
  1. calm comes from an open Settings panel
  2. section 3 undoes it the same way
  3. `rxReset()` closes Settings
  4. each section-2 blocker case checks a clean start and a gate holding, plus `calm` by name for the calm case
  5. the shim keeps the page's own `proactive`/`reactions`
- **Not changed:** `hover`, `bar` and `peek` stay faked (the app writes them only on real events), there are no
  longer waits and no looser checks, and the app is untouched.

## Steps

1. **Reproduce both routes on the unfixed test** (lead, no commit). Use temporary edits to `tests/react_fit.mjs` and
   run `test_react_fit.py` through the CI runner (Tests). Three runs each:
   - **Route 1:** after `${js};` in the section-2 case (`:71`), add `sendRegion(true);`. The calm case must fail
     every run, with `[true,false,{"id":"rain"}]`.
   - **Route 2:** in the same place, add `if(${JSON.stringify(name)}==='reactions off') await refresh();`. The
     "reactions off" case must fail every run.

   Then `git checkout tests/react_fit.mjs`.
   → verify: 3 red calm runs and 3 red "reactions off" runs, then `git status --porcelain` is empty.

   Trap: if route 2 doesn't fail, check whether `refresh()` returned early: it stops at `staleToken()` when the reply
   has no `cwd` (`:4627`). Stop and report. Don't change the forcing until it does fail.

2. **`tests/react_fit.mjs`, the fix** (Codex). The line numbers are from before the edits.
   - **`:27`, the `fetch` shim:** `proactive:true,reactions:true` becomes
     `proactive:info.proactive,reactions:info.reactions`. Leave `look_meeting`, `look_weather`, `look_music` and
     `click_through` as `true`.
   - **`:33-37`, `rxReset()`:** add `setEl.classList.remove('on');` immediately before
     `document.body.classList.remove('bar','hover','calm','peek');`.
   - **`:67`, `blockers.calm`:** `"document.body.classList.add('calm')"` becomes
     `"setEl.classList.add('on'); calmCheck()"`.
   - **`:70-73`, the section-2 loop:**
     - After `rxReset();`, read `const base0=rxBase();`.
     - Return `[ok, empty(), RX, base0, rxBase()]`. For the calm case only, append
       `document.body.classList.contains('calm')`.
     - Expect `[false, true, null, true, false]`, with `true` appended for calm. Compute the expected array in Node
       from `name`. In the browser string, use `${JSON.stringify(name)}` to test the name, never a bare `${name}`.
   - **`:89`, `undo.calm`:** `"document.body.classList.remove('calm')"` becomes
     `"setEl.classList.remove('on'); calmCheck()"`.

   → verify:
   - `nix develop .#ci -c python3 -B .github/ci/run_tests.py --deadline 1800 test_react_fit.py` is `ok`.
   - `git diff --stat` shows only `tests/react_fit.mjs`.

   Traps:
   - The page code sits inside Node template literals (`ev(\`…\`)`). Any `${…}` is evaluated by Node, so page names
     (`info`, `setEl`, `rxBase`) must never be inside `${}`. An inner backtick ends the literal.
   - Don't change sections 1, 4 onward, the waits, or any other blocker.
   - Never start Chromium yourself. Only the test may, headless with `--disable-gpu` (a GPU Chrome hung p620's AMD GPU
     twice).

3. **Prove the fix against both routes** (lead, no commit). The lead commits step 2 first. On top of it, add the same temporary forcing:
   - **Route 1, section 2:** `sendRegion(true);` after `${js};`
   - **Route 1, section 3:** `sendRegion(true);` right after `${on};` and right after `${off};` (`:94`, `:96`)
   - **Route 2:** `if(${JSON.stringify(name)}==='reactions off') await refresh();` after `${js};`

   Run `test_react_fit.py` three times. It must be `ok` every run. Then `git checkout tests/react_fit.mjs`.
   → verify: 3 green runs with the forcing, then `git status --porcelain` is empty.

4. **The PR** (lead):
   - Push and open the PR, linking the intent, spec and plan, and saying Codex did step 2. Comment `@codex review`
     (memory).
   - The PR's CI must have `test` green.

## Tests

- **Local, on p620, through the CI runner:**

  ```bash
  nix develop .#ci -c python3 -B .github/ci/run_tests.py --deadline 1800 test_react_fit.py
  ```

  It must be `ok`. Every section-2 blocker shows its guard values, and section 3's calm cases pass all three checks.
- Steps 1 and 3: the forced routes are red before the fix and green after.
- **The PR's CI:** `test` green.

## Rollback

Revert the PR. The test goes back to faking calm and forcing the flags. No app, data or config changes.
