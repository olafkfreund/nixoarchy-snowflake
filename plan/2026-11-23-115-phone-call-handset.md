---
status: draft
issue: 115
spec: spec/2026-11-23-115-phone-call-handset.md
coders:
  1: coder   # Android call id + hands-free list: plain Kotlin plumbing across 5 files
  2: codex   # Android action guard: small, safety-critical logic (wrong call = dropped call)
  3: codex   # fluxd call.action + snapshot fields: small, tricky state checks with -race tests
  5: coder   # phone.py: two small edits, same session as step 7 keeps the cache warm
  6: codex   # hfp.py: D-Bus discovery at two levels and reseeding, small and subtle
  7: coder   # server.py Call state, /api/call, ringtone, tests: the largest step, follows house patterns
  8: coder   # page handset (SVG, CSS, JS) + page test: big but needs judgement, not mechanical
  9: agy     # nb/pl strings and pairing docs: mechanical, many small text edits
reviewers:
  - codex    # reads each PR diff natively (codex review --base)
  - agy      # independent second read of the whole diff per repo
---

# Plan: take phone calls on the host with a ringing retro handset

## Summary of the approved decisions

Use this summary instead of reopening the spec.

- **Two paths, one handset.**
  - **Host:** Bluetooth hands-free (HFP). PipeWire's `org.pipewire.Telephony`
    reports calls and answers and hangs up. WirePlumber auto-links the call's
    streams. Our only audio work is config: an echo canceller and the uplink
    target.
  - **Phone:** no hands-free link. Flux answers or rejects a ringing call on
    the phone, and the audio stays there. There is no hang-up through Flux.
  - **Watch:** another fleet host holds the link. Show the caller, no keys,
    "Ringing on <host>".
- **PipeWire 1.6.11 facts (from source):**
  - Calls are announced on each gateway's ObjectManager (`/org/pipewire/Telephony/agN`),
    and gateways on the root.
  - `AudioGatewayTransport1.State == "active"` means the audio is here.
  - The call stream nodes have `api.bluez5.profile = "headset-audio-gateway"`,
    `Stream/Output/Audio` (the caller's voice) and `Stream/Input/Audio` (our
    mic), and `node.autoconnect = true` (WirePlumber `name-node.lua:64-68`).
  - `wpctl` needs numeric ids.
- **Flux call identity.** The phone makes `callId` (random 64-bit hex) when
  the line leaves idle. fluxd's `since` is its own clock and is never used to
  identify a call. The phone also sends `handsFree`: the names of its
  connected hands-free devices. The hosts' adapter names equal their host
  names.
- **The Android guard.** Act only when the permission is held,
  `CallTracker`'s state is ringing, and its id equals the packet's `id`. Then
  `acceptRingingCall()` / `endCall()`. No `getCallState()`.
- **Nixi `Call`.**
  - Correlate the HFP and Flux sides of one call: within 15 s, and the last 8
    digits match or one side has no number.
  - One `id` per call, plus a `gen` that changes with the path.
  - The name comes from Flux's contact (not "Unknown caller"), then HFP
    `Name`. The number is shown only with no name and only while unlocked.
  - `answered_at` is our clock at the first active/talking.
  - `ended` only after answered. `gone` on a link drop, lock, Phone off, or
    socket loss.
  - One missed card per call.
- **`/api/call`** needs the token and the click key, and is not in
  `TOOL_PATHS`. At dispatch, under a lock, it re-checks `phone_on`,
  unlocked, `id` and `gen`, and that `act` is in `keys`. One action at a
  time. No phase change in 6 s → "Didn't work. Use your phone".
- **Ringtone.** A synthesised two-tone trill every 3 s, quiet. Its own gate:
  `phone_on`, unlocked, no meeting, no DND, not asleep, not muted. It starts
  after Nixi's announcement and stops on any phase change.
- **Privacy.** `phone_on_screen()` is true while the handset shows
  (`/api/capture` refuses). The handset is cleared on lock and on Phone off.
  No audio is written anywhere.
- **Handset.** Our own SVG candybar phone: green LCD, shake while ringing
  (still under reduced motion), green, red and mute keys, a volume rocker,
  an `mm:ss` timer. A compact pill in bar mode. Real buttons.
- **nixos_config.** `calls.enable` in
  `hosts/common/nixos/omarchy-nixi-companion.nix` writes:
  - `pipewire.conf.d/61-nixi-call-echo-cancel.conf`: webrtc, monitor mode,
    `ifexists nofail`, nodes `nixi-call-echo-cancel-source` / `-capture`;
  - `wireplumber.conf.d/z-nixi-phone.conf`: phone cards get
    `bluez5.auto-connect = [ hfp_ag ]`, and HFP `Stream/Input/Audio` gets
    `target.object = "nixi-call-echo-cancel-source"`.
  p620 first; razer after the live test passes.
- Flux's desktop call notification stays.

## Steps

Branches:
- `nixarchy-flux`: `feat/80-call-action`, issue olafkfreund/nixarchy-flux#80;
- `nixoarchy-snowflake`: `feat/115-phone-call-handset` (this branch);
- `nixos_config`: `feat/115-nixi-calls`.

Flux goes first: Nixi's phone path needs its snapshot fields.

### Flux (`/mnt/code/Source-home/GitHub/nixarchy-flux`)

1. **Android: call id and hands-free list** (coder).
   - `android/app/src/main/java/org/omarchy/flux/core/Calls.kt:28-98`:
     `CallTracker` makes `callId` on leaving idle and clears it on idle.
     `CallPackets.body` adds `callId` and `handsFree` (a list of strings).
   - `service/CallMonitor.kt:~111-115`: pass the hands-free names when
     sending.
   - `Android.kt:~381-391`: a `handsFreeNames()` helper using the
     `BluetoothHeadset` profile proxy. Return an empty list when
     `BLUETOOTH_CONNECT` is not granted.
   - `AndroidManifest.xml:23-26`: add `BLUETOOTH_CONNECT` and
     `ANSWER_PHONE_CALLS`.
   - `ui/SyncScreen.kt:186-193`: ask for both with the "Call alerts" set.

   Verify: `./gradlew :app:testDebugUnitTest`. New cases in
   `src/test/.../core/BridgesTest.kt`: the id is the same for one call, new
   for the next, absent when idle, and the body has `callId` and `handsFree`.

   Traps: a packet without `callId` (an old app) must still parse on fluxd
   (step 3). Flux CI runs `:app:lintDebug`, so new permissions need the
   right `tools:` or SDK checks.
2. **Android: answer or reject on request** (codex).
   - New `core/CallControl.kt`: a pure `fun allowed(state, trackerId, packetId,
     hasPermission): Boolean`, plus the `TelecomManager` call.
   - Route `flux.telephony.action` in `core/Plugins.kt:90-140`.
   - Add the type constant and put it in `INCOMING` in
     `protocol/Identity.kt:9-138`.

   Verify: `./gradlew :app:testDebugUnitTest :app:lintDebug`, with
   `CallControlTest.kt` covering every refusal and both actions.

   Traps: never call `getCallState()`. Use `CallTracker`'s state only.
   `endCall()` only when ringing.
3. **fluxd: store the fields and add `call.action`** (codex).
   - `internal/core/telephony.go:74-215`: `callBody` gets `CallID` and
     `HandsFree`, stored on `dev.call`.
   - `internal/core/device.go:133-144,~299,348-355`: JSON `id`, `handsFree`.
   - `internal/core/api.go`: an `ID string` param (struct `~:240-260`), a
     `call.action` case modelled on `dnd.set` (`:496-509`), and the name in
     `deviceMethods` (`:515-525`). List `telephony.action` in the device's
     plugins when the phone accepts the type.
   - `docs/ipc.md:~165-216`: document it.

   Verify: `go test -race ./cmd/... ./internal/... ./scripts/...`,
   `go vet ./...` and `gofmt -l .` (Makefile `:56-61`). New tests in
   `telephony_test.go` use `dnd_test.go:210-249` as the template: fields
   stored, plus refusals for a wrong id, not ringing, offline, not paired and
   not accepted, and success.

   Traps: `callEvent`'s lock sections (`telephony.go:117-136`) are where the
   view is written. Keep the writes inside them (see the #57 spec).
4. **Flux release** (Claude).
   - PR on `olafkfreund/nixarchy-flux` (always `gh ... -R olafkfreund/nixarchy-flux`:
     a bare `gh` targets the upstream `bjarneo/flux`), linking #80 and this
     plan, then a `@codex review` comment.
   - Codex and agy review the diff (`reviewers:`). Merge on green.
   - Release per `docs/releasing.md`. The owner installs the new APK on the
     Pixel and grants the two new permissions under "Call alerts".

   Verify: CI green (`build.yml`), and after the deploy (step 11)
   `flux-cli` shows `telephony.action` for the Pixel.

### Nixi (`/mnt/code/Source-home/GitHub/nixoarchy-snowflake`)

5. **`app/phone.py`** (coder).
   - `:20`: add `call.action` to `METHODS`.
   - `:128-130`: map the plugin `telephony.action` to `can` `answer`.
   - `devices()` already copies `call`. Confirm that `id` and `handsFree` pass
     through.

   Verify: `tests/test_phone.py` cases for both.
6. **`app/hfp.py`, new** (codex), plus `tests/test_hfp.py`.
   - The `Hfp` class: Gio on the session bus, following the notification
     watch pattern in `app/server.py:3300-3440`. Load Gio lazily and log a
     failure once.
   - Discovery at both levels: one signal subscription on the service name,
     `GetManagedObjects` on the root and on each `agN`, and a reseed on
     `NameOwnerChanged`.
   - Records: gateway `{path, address, transport}`, call
     `{path, ag, state, number, name}`, where `"withheld"` means no number.
   - `answer`, `hangup` → `{ok, error}`.
   - `audio_here(call)`.
   - `streams(address)` via `pw-dump` JSON, matched on `api.bluez5.address`,
     the profile and the `media.class`.
   - `volume(step)` / `mute()` via `wpctl` with numeric ids and
     `set-volume -l 1.5`, reading back with `wpctl get-volume`.
   - `any_call()`.
   - An `on_change` callback.

   Verify:
   - The tests use a fake connection object and a recorded `pw-dump` fixture
     in `tests/fixtures/`, so no real D-Bus or PipeWire.
   - Run with `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_hfp.py`.

   Traps: tests must not import `server` under the real HOME, and any test
   server uses the `nixi_env` helper (it overwrote the live config, #176).
   Subprocesses use `pdeathsig_preexec` from `app/floor.py:10`.
7. **`app/server.py`: `Call`, `/api/call`, the ringtone and the gates**
   (coder), plus `tests/test_call.py`.
   - A `class Call` next to the phone code (`:7900-8070`):
     - correlation;
     - path (host, phone, watch), using the fleet peers from the
       `nixi-fleet` config;
     - `id` and `gen`, phases, keys and note;
     - `publish()` → `BUS.pub(t="call", …)`, and on lock or Phone off
       `phase:"gone"`.
     The page's `/api/events` connection (`:10012`) also gets the current
     call on connect.
   - Wire it up:
     - `Phone.on_state` (`phone_state`, about `:7960`) and `Hfp.on_change` →
       `Call.sync()`;
     - `phone_call_sync` (`:7974`) uses `Phone.call_active or Hfp.any_call()`,
       and also stops speech and cancels a listen on the edge to answered;
     - `phone_on_screen` (`:7796`) is true while `Call.visible()`;
     - a missed-card helper shared with `phone_on_missed` (`:7903`), deduped
       by call key.
   - The `/api/call` POST route goes beside `/api/phone/send` (`:10083`): the
     token plus `click_ok` (`:83`), the re-checks under the call's lock, and
     dispatch to `Hfp` or to `Phone.call("call.action", …)`. A 6 s watchdog
     sets the note.
   - Ringtone: synthesise the trill with `wave` once and cache the bytes.
     Play through the player at `:6035` every 3 s while ringing, with its own
     gate, and wait while the call announcement (`Speaker.phone_call_sids`,
     `:6067`) plays.
   - Start `Hfp` where `Phone` starts.
   - Language keys `call.*` in `app/lang/en.json`.

   Verify:
   - `tests/test_call.py` covers every case in the spec's Verification
     list, with fake `Phone` and `Hfp` objects.
   - The full CI run:
     `nix develop .#ci -c python3 -B .github/ci/run_tests.py --exclude test_character_fit.py --exclude test_accessories_fit.py`.

   Traps:
   - Same HOME and `nixi_env` rules as step 6.
   - Never send numbers to the Phone tab or status line (`:7915`, `:7930`).
   - Ringtone and speech share the speakers. Don't play the ring while
     `Speaker` is speaking.
8. **`app/static/index.html`: the handset** (coder), plus
   `tests/handset_fit.mjs` and `tests/test_handset_fit.py`.
   - CSS: next to `#mailPop` (`:165-181`) and `#stgTab` (`:377-397`). The
     shake keyframes, and reduced motion in the `@media` block at `:397`. In
     the hidden list for `body.bar` / `body.calm` (`:396`) the handset is
     hidden, and the bar pill takes its place in bar mode.
   - HTML: an SVG `#handset` beside `#stgTab` (`:869`).
   - JS:
     - a `HANDSET` module handling `t:"call"` in the event switch (near
       `ev.t==='phone'`, `:2825`);
     - the side from `stgSide` (`:3096`);
     - the timer from `answered_at`;
     - keys `POST /api/call` with `hdr(Object.assign({...},CLICKKEY.hdr()))`
       as at `:3195`;
     - a stale reply re-renders;
     - `sendRegion` adds the handset (`:4757`);
     - key events stop propagation as at `:3468`.

   Verify:
   - A page test modelled on `tests/stages_fit.mjs` + `test_stages_fit.py`,
     on headless Chromium with `--disable-gpu`. It covers every phase and
     path, only the `keys` enabled, the posted body, reduced motion, zoom 1
     and 1.5, and the bar pill.
   - Then a screenshot for the owner's look-over.

   Traps:
   - Never use a desktop or GPU Chrome for previews (it hung the AMD GPU
     twice).
   - Our own drawing only: no brand name, logo or real model's outline.
9. **Text and docs** (agy).
   - `app/lang/nb.json` and `pl.json`: the `call.*` keys from step 7.
   - `docs/GUIDE.md`: a "Take calls on Nixi" section with the pairing steps,
     including "Media audio" off on the phone, and the two paths.
   - A README feature line.

   Verify: the lang test in the CI run (missing keys fail).

### nixos_config (`~/.config/nixos`, worktree from `origin/main`)

10. **`calls.enable`** (Claude).
    - In `hosts/common/nixos/omarchy-nixi-companion.nix`: an option that
      writes the two files above through home-manager `xdg.configFile`.
    - `true` in `hosts/p620/nixos/nixarchy.nix`, razer left off.
    - Bump the `nixi-companion` and `nixarchy-flux` inputs only.

    Verify: `nix build .#nixosConfigurations.p620.config.system.build.toplevel`,
    plus `diff-closures` showing only those files and the two packages.

    Traps:
    - `~/.config/nixos` may be dirty with someone else's work. Never touch it,
      and work in a worktree.
    - `nixarchy-theme.nix` is uncommitted: copy it into the deploy worktree
      if it differs.
    - Never touch p510.
11. **Deploy p620** (Claude).
    - Announce on the agent bus (`#agents:freundcloud.org.uk`), then
      `AGENT_BUS_ANNOUNCED=1 nh os switch .` from a clean worktree at
      `origin/main`.
    - Restart PipeWire, WirePlumber and Nixi. For Nixi, take the Hyprland
      signature from `/run/user/1000/hypr` first.
    - Check `server.log` and `wpctl status`.

    Verify:
    - `pactl list short sources` shows `nixi-call-echo-cancel-source`;
    - `wpctl status` is otherwise unchanged;
    - Nixi is running the new build;
    - no failed units.
12. **Live test with the owner** (Claude and the owner): the spec's 9
    checks on p620, after pairing the Pixel ("Media audio" off).
    - Record `wpctl inspect` of the phone's card and the call streams in the
      PR.
    - Any failure means a fix through steps 5-11 and a plan update in the same
      commit.
    - The fallbacks in the spec's Risks apply: match by address, or drop
      `a2dp_sink`.
13. **razer** (Claude, after step 12 passes and the owner agrees).
    - Set `calls.enable = true` for razer, then `just deploy-via-p620 razer`
      (`nh --target-host` can't read sudo).
    - Pair the Pixel with razer, and run checks 2-5 and 8 again, plus the
      two-host check: only the linked host offers keys.

## Tests

| Repo | Command | Expected |
|---|---|---|
| nixarchy-flux | `go test -race ./cmd/... ./internal/... ./scripts/...`; `go vet ./...`; `gofmt -l .` | pass, no files listed |
| nixarchy-flux | `./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug` | pass |
| nixoarchy-snowflake | `nix develop .#ci -c python3 -B .github/ci/run_tests.py --exclude test_character_fit.py --exclude test_accessories_fit.py` | pass, including `test_hfp`, `test_call` and `test_handset_fit` |
| nixoarchy-snowflake | plugin sandbox tests | not needed: no change to `app/plugins.py` or the wrapper PATH |
| nixos_config | `nix build` p620 (razer at step 13), `nix store diff-closures` | only the intended changes |
| live | the spec's 9 checks on p620, then razer | all pass |

## Rollback

- **Software:** set `calls.enable = false` on the host and redeploy. The
  echo canceller and the WirePlumber rules go away. Nixi's handset still
  shows Flux calls.
- **Whole feature:** revert the nixos_config bump PR, so the inputs go back
  to the previous `nixi-companion` and `nixarchy-flux`, then redeploy.
- **Fast:** `nixos-rebuild switch --rollback` on p620.
- **Bluetooth:** unpair the Pixel from the host (`bluetoothctl remove <addr>`).
- **Phone:** the old Flux APK can be reinstalled. The new packet fields are
  extra, so the old fluxd ignores them.
