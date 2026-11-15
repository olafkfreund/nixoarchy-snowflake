---
status: draft
issue: 91
author: olafkfreund
---

# Intent: the react_fit "calm" blocker stops flaking

## Problem

`test_react_fit` failed once in CI on PR #90 (run 43726068858). That PR doesn't touch reactions:

```
AssertionError: 1 != 0 : CUT  nothing plays with calm  → [true,false,{"id":"rain"}]
```

The "calm" blocker in `tests/react_fit.mjs:67` fakes calm by adding the class to `body` directly, then waits 60 ms
before `rxPlay('rain')`. The app owns that class. `calmCheck()` (`app/static/index.html:4651`) recomputes it from
whether a panel is open (`setEl`, `panelEl`, `apEl`), and it runs on every `sendRegion()`, which has 38 callers. If one
of them runs during the 60 ms, `calm` is cleared and rain plays.

The "calm" cases in section 3 (`mid`/`undo`, `:89`) fake it the same way. They can fail by the same route, and they can
also pass for the wrong reason.

A red `test` job blocks merges and costs a 40-minute rerun.

## Proposed outcome

- The "calm" cases in `react_fit` reach calm the way the app does, so `calmCheck()` keeps it on instead of clearing it.
- The run that failed on #90 can't happen again by this route.
- The checks still prove what they claim: no reaction plays while calm holds, and one arriving mid-reaction empties
  the groups.

## Affected users and systems

- `tests/react_fit.mjs` (run by `tests/test_react_fit.py`), and CI's `test` job.
- No app behaviour changes, and no user sees a difference.

## Constraints

- Test-only. Don't change `calmCheck()` or the app to suit the test.
- The test must clean up after each case: no panel left open for the next case or the next section.
- Headless Chromium with `--disable-gpu` only, started by the test.
- Don't loosen the checks or lengthen waits to hide the race.

## Open questions

- Which panel should the test open to get calm: Settings (`setEl`), the side panel (`panelEl`) or the approval card
  (`apEl`)? Settings is the likely choice, since `stages_fit.mjs:511` already resets it, but opening it for real may
  draw more than the case needs. The spec decides from a measurement.
- Do any other `*_fit.mjs` files fake `calm` the same way? A grep finds only `react_fit`, but the spec confirms it.
