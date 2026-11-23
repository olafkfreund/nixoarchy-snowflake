---
status: approved
issue: 115
spec: spec/2026-11-23-115-phone-call-handset.md
coders:
  1: codex   # Android tracker id/waiting/hands-free + shared tracker: lifecycle and threading, small and subtle
  2: codex   # Android action guard: same files as step 1, safety-critical (wrong call = dropped call)
  3: codex   # fluxd fields, end reason, call.action: state checks under the lock, -race tests
  5: coder   # phone.py: three small edits, same agent as steps 8 and 9 keeps the cache warm
  6: codex   # hfp.py: D-Bus discovery at two levels and reseeding, small and subtle
  7: codex   # Call state machine, /api/call locking and privacy gates: the trickiest logic
  8: coder   # ringtone, wiring into existing hooks, en strings: follows house patterns
  9: coder   # page handset (SVG, CSS, JS) + page test: big, needs judgement
  10: agy    # nb/pl strings and pairing docs: mechanical text edits
reviewers:
  - codex    # reads each PR diff natively (codex review --base)
  - agy      # independent second read of each repo's diff
---

# Plan: take phone calls on the host with a ringing retro handset

## Summary of the approved decisions

This plan is self-contained. Implement from it, not from the spec.

### The paths

- **Host:** this host holds the phone's Bluetooth hands-free (HFP) link.
  PipeWire's telephony service reports the call and answers, rejects and
  hangs it up. WirePlumber links the call audio itself. The keys are answer,
  reject, hang-up, mute and volume.
- **Phone:** no HFP call on this host, and the phone's `handsFree` list names
  no other fleet host. Flux answers or rejects a ringing call on the phone,
  and the audio stays there. There is no hang-up through Flux. After answer
  the handset shows "On phone" with no keys.
- **Watch:** another fleet host (from the companion's `nixi-fleet` peers) is
  in the phone's `handsFree` list. Show the caller, no keys, and the note
  "Ringing on <host>".
- **On phone (host path):** the HFP call is `active`, but this gateway's
  transport is not `active` (answered on the phone or the buds). Show "On
  phone", no keys.
- **Second call:** more than one HFP call on a gateway, or a Flux `ringing`
  that arrives during a call (`waiting: true`). Show the first call, disable
  every key, and note "Second call: use your phone".

### PipeWire 1.6.11 / WirePlumber 0.5.19 facts (from source, used as-is)

- Service `org.pipewire.Telephony`, user bus.
- Gateways are announced on the root ObjectManager `/org/pipewire/Telephony`
  as `…/agN` (`org.pipewire.Telephony.AudioGateway1`). Calls are announced on
  each gateway's own ObjectManager as `…/agN/callM`
  (`org.pipewire.Telephony.Call1`).
- `Call1`: `Answer()` is valid only while `State == "incoming"`. `Hangup()`
  rejects an incoming call or ends any call. Errors are
  `org.pipewire.Telephony.Error.InvalidState` and
  `org.freedesktop.DBus.Error.Failed`. Properties: `State` (`active`, `held`,
  `dialing`, `alerting`, `incoming`, `waiting`, `disconnected`),
  `LineIdentification` (where `"withheld"` means no number), and `Name`.
- `AudioGatewayTransport1.State == "active"` means the call audio is on this
  host.
- The call audio nodes carry `api.bluez5.profile = "headset-audio-gateway"`,
  and they exist only while the transport is up: `Stream/Output/Audio` (the
  caller's voice → default sink) and `Stream/Input/Audio` (our mic → the
  phone). WirePlumber sets `node.autoconnect = true` (`name-node.lua:64-68`).
- `wpctl` takes numeric ids only.
- `AudioGateway1.SpeakerVolume` is the phone's own volume. It stays
  untouched.

### Flux

- **Android.**
  - `CallTracker` makes a random 64-bit hex `callId` on every transition
    into ringing or off-hook from idle. On `OffHook → Ringing` (call waiting)
    it makes a second id for the waiting call and marks the events
    `waiting: true`.
  - Each event carries the id it belongs to, captured before any clearing.
  - The phone sends `handsFree`, the names of its connected hands-free
    devices. The hosts' adapter names are their host names.
- **fluxd.**
  - It stores `id`, `handsFree` and `waiting` on the call view.
  - When a call ends it keeps `lastCall {id, end, at}` in the snapshot for
    30 s, where `end` is:
    - `hangup`: cancel after talking;
    - `missed`: cancel while ringing;
    - `lost`: the link dropped.
  - `missedCall` gets the `id`.
  - `call.action {action: answer|reject, id}` acts only on a ringing,
    non-waiting call whose id matches.
- **Android guard.** Act only when `ANSWER_PHONE_CALLS` is held, the shared
  tracker's state is ringing, the call is not waiting, and the id matches.
  The check and the action run under the tracker's lock. Then
  `acceptRingingCall()` or `endCall()`. The tracker is the guard. Right before
  acting, two live checks are added on top: Telecom has a managed call, and the
  line is ringing now (`getCallStateForSubscription()`, or `callState` before
  API 31). This closes the gap where the tracker lags an answer on the phone
  (Codex on #81). The hidden `TelecomManager.isRinging()` isn't available.

### Nixi `Call` (`app/server.py`)

- **Correlation.** An HFP call and a Flux call are one call when both appear
  within 15 s, and their numbers match on the last 8 digits, or one side has
  no number.
- **Identity.** One random `id` per call. `gen` goes up on every change of
  path or keys.
- **Name and number.**
  - The name is Flux's contact (not the placeholder `"Unknown caller"`), then
    HFP `Name`, then none.
  - The number is HFP's, then Flux's. It is published only when there is no
    name, and only while the desk is positively unlocked
    (`Desk.locked() is False`).
- **Phases.**
  - `ringing`, then `active` when answered. `answered_at` is our clock at the
    first HFP `active` or Flux `talking`, never Flux's `since`.
  - `ended` shows "Call ended" for 2 s. It is used only when the call had
    been answered and we saw it end: HFP `disconnected` after `active`, or
    Flux `lastCall.end == "hangup"` for this id.
  - `gone` means the handset leaves at once. That covers a link drop
    (`lost`), no end seen, the desk locking, Phone turned off, or a lost Flux
    socket while HFP has no call.
- **Missed card.** A call that ends unanswered gives exactly one
  `phone_missed` card, keyed by the call id. It comes from Flux's
  `missedCall` or from an HFP `incoming → disconnected`, whichever comes
  first.
- **Bus.** `t:"call"` carries
  `{id, gen, phase, path: host|phone|watch, who, number, answered_at,
  audio_here, muted, volume, keys: [...], note}`, or `{phase:"gone"}`.
  `/api/events` sends the current call (or nothing) on connect, under the
  same privacy gate.
- **`POST /api/call {id, gen, act}`.**
  - `act` is one of `answer`, `reject`, `hangup`, `mute`, `vol_up`,
    `vol_down`.
  - It needs the window token and the click key (`click_ok`), and is not in
    `TOOL_PATHS`.
  - Under the call's lock it re-checks: `phone_on`, positively unlocked, the
    current `id` and `gen`, and `act` in `keys`. A mismatch returns
    `{ok:false, stale:true}`.
  - One action at a time: a second POST while one is in flight returns
    `{ok:false, busy:true}`.
  - Host → `Hfp`; phone → `Phone.call("call.action", ...)` (its IPC waits up
    to 10 s).
  - The 6 s "Didn't work. Use your phone" watchdog starts when the action has
    been sent, and is cancelled by any phase change.
- **Quiet.** `Ambient.phone_call` is `Phone.call_active or Hfp.any_call()`.
  It pauses the wake word, push-to-talk, follow-ups, nudges and unasked
  speech for as long as either side reports a call. On the edge to answered,
  `Speaker.stop()` runs and a listen is cancelled.
- **Ringtone.**
  - A synthesised two-tone trill as raw s16le mono PCM, at the rate the
    player expects, about 0.8 s, played every 3 s while ringing and quietly
    (amplitude about 0.2).
  - Its own gate: `phone_on`, positively unlocked, not in a meeting, no DND,
    not asleep. Proactive mode and the voice engine don't matter. (Deviation,
    step 8: Nixi's mute lives only in the page's `localStorage`, so the
    server-side ring cannot follow it.)
  - It waits until `Speaker` is idle (nothing queued or playing), so Nixi's
    "X is calling" announcement comes first.
  - It stops on any phase change, on lock and on Phone off.
- **Privacy.**
  - `phone_on_screen()` is true while the handset is shown, so
    `/api/capture` refuses.
  - The lock edge in `Ambient.sense` and `phone_reset()` both call
    `Call.clear()` → `gone`, and the ring stops without waiting for a
    telephony event. (Deviation, step 8: `Ambient.sense` reads the lock only
    with proactive on, so it also re-checks `Desk.locked()` on every tick while
    a handset is shown. `Hfp.on_change` runs `phone_call_sync` as well, so an
    HFP-only call quiets him.)
  - The Phone tab and status line never show numbers.

### Handset (`app/static/index.html`)

- **The drawing.** Our own SVG candybar phone, about 92×190 px at zoom 1:
  - a rounded body and a stub antenna;
  - a green LCD tinted from `--acc`, with a pixel-look text style and no
    brand font or logo;
  - a soft-key bar ("Host" or "Phone");
  - a green key, a red key, a mute key and a side volume rocker.
- **States.**
  - ringing: shake and a blinking backlight, with a bell glyph, the name or
    the number;
  - active: an `mm:ss` timer, a mute glyph and a volume bar when
    `audio_here`;
  - on phone, watch, second call: the note, no keys;
  - ended: "Call ended" for 2 s, then it slides away.
  Reduced motion gives a steady lit LCD reading "Ringing", with no shake and
  no blink.
- Only the keys in `keys` are enabled. The others are `disabled`.
- Every key is a real `<button>` with an `aria-label` and a visible focus
  ring. Enter and Space work, with no pointer-type check. Key events don't
  reach the window's shortcuts.
- **Where it shows.**
  - normal view, beside Nixi on the side with room;
  - hover mode: shown and clickable. The hover input region, normally empty,
    includes the handset;
  - bar mode: a compact pill with the same keys, inside the bar's region;
  - calm mode: hidden.
- **Window.** The window grows for the handset through `sizeWindow()`, and
  Nixi doesn't idle-shrink or doze while it shows.

### nixos_config

`calls.enable` (default false) in
`hosts/common/nixos/omarchy-nixi-companion.nix` writes two files through
home-manager:

- `pipewire.conf.d/61-nixi-call-echo-cancel.conf`:
  `libpipewire-module-echo-cancel` with `library.name = aec/libspa-aec-webrtc`,
  `monitor.mode = true` (the reference is the default sink's monitor),
  `flags = [ ifexists nofail ]`, and nodes `nixi-call-echo-cancel-capture` /
  `nixi-call-echo-cancel-source`. It is independent of meetingai's.
- `wireplumber.conf.d/z-nixi-phone.conf`, with two `monitor.bluez.rules`
  entries:
  - `device.form-factor = "phone"` → `bluez5.auto-connect = [ hfp_ag ]`. The
    file is named `z-…` so it loads after the hand-made
    `bluetooth-a2dp-autoconnect.conf`, and the later match wins;
  - nodes with `api.bluez5.profile = "headset-audio-gateway"` and
    `media.class = "Stream/Input/Audio"` → `target.object =
    "nixi-call-echo-cancel-source"`. The downlink keeps the default sink.

p620 first; razer only after the p620 live test passes and the owner agrees.

**Pairing** (owner, once per host): `bluetoothctl` pair, trust, connect. Then
on the Pixel the host's entry has "Phone calls" on and "Media audio" off.

### Other decisions

Flux's own desktop call notification stays.

## Steps

Branches and the issue each one belongs to:

| Repo | Branch | Issue |
|---|---|---|
| `nixarchy-flux` | `feat/80-call-action` | olafkfreund/nixarchy-flux#80 |
| `nixoarchy-snowflake` | `feat/115-phone-call-handset` (this branch) | #115 |
| `nixos_config` | `feat/115-nixi-calls` | worktree from `origin/main` |

### Flux (`/mnt/code/Source-home/GitHub/nixarchy-flux`)

Run every `gh` command in this repo with `-R olafkfreund/nixarchy-flux`. A
bare `gh` targets the upstream `bjarneo/flux`.

1. **Android: call id, waiting flag, hands-free list, shared tracker**
   (codex).
   - `android/app/src/main/java/org/omarchy/flux/core/Calls.kt:28-98`:
     - `CallTracker` makes and holds `callId` (and a separate waiting id on
       `OffHook → Ringing`);
     - `CallEvent` carries `id` and `waiting`;
     - the end and missed events of a call carry that call's id, captured
       before clearing;
     - `CallPackets.body` adds `callId`, `waiting` and `handsFree`.
   - Make the tracker reachable from `Plugins`. Today it is
     `private val tracker` in `service/CallMonitor.kt:43`, and `CallMonitor` is
     private in `service/FluxService.kt:56`. Move it to one synchronized
     holder on `FluxCore`, which `CallMonitor` updates, with a
     `snapshot(): (state, id, waiting)` read under the same lock.
   - `CallMonitor.kt:~102-115` sends the hands-free names. `handsFreeNames()`
     in `Android.kt:~381-391` keeps one `BluetoothHeadset` proxy:
     - it is bound asynchronously through `getProfileProxy` on start, read
       from its cache, and closed with `closeProfileProxy` in `stop()`;
     - it returns an empty list without `BLUETOOTH_CONNECT`.
   - `AndroidManifest.xml:23-26`: add `ANSWER_PHONE_CALLS` and
     `BLUETOOTH_CONNECT`.
   - `ui/SyncScreen.kt:186-193`: ask for both. Today the launcher runs only
     when `!state.callAccess`, so an existing user is never asked. Add a check
     for the two new permissions that launches the request even when
     `callAccess` is true. `BLUETOOTH_CONNECT` goes in the array only on
     API 31+.

   Verify, from `android/`: `./gradlew :app:testDebugUnitTest :app:lintDebug`,
   with new cases in `src/test/.../core/BridgesTest.kt`:
   - one id per call, a new id for the next call, none when idle;
   - `OffHook → Ringing` gives a new id with `waiting: true`;
   - the end and missed packets carry the ended call's id;
   - the packet body has the three fields.
2. **Android: answer or reject on request** (codex).
   - New `core/CallControl.kt`:
     - `fun allowed(snap, packetId, action, hasPermission): Boolean`, pure:
       ringing, not waiting, ids equal, action in {answer, reject}, permission
       held;
     - `fun act(...)` holds the tracker's lock across the `allowed` check and
       `TelecomManager.acceptRingingCall()` / `endCall()`;
     - a refusal or a `false` from `endCall()` is logged and nothing else.
   - Route `flux.telephony.action` in `core/Plugins.kt:90-140`.
   - Add the constant in `protocol/Identity.kt:9-122` and put it in `INCOMING`
     (`:125-138`).

   Verify, from `android/`: `./gradlew :app:testDebugUnitTest :app:lintDebug`.
   `CallControlTest.kt` covers:
   - every refusal (wrong id, waiting, off-hook, idle, no permission, unknown
     action, missing id);
   - both actions allowed.

   Traps:
   - The live line state is only an extra condition and never replaces the
     tracker check (deviation recorded during step 4, review of #81).
   - Never act on a waiting call.
3. **fluxd: fields, end reason, `call.action`** (codex).
   - `internal/proto/identity.go`: `TypeFluxTelephonyAction =
     "flux.telephony.action"` next to `TypeFluxDndSet` (`:60`), and in
     `Outgoing` (`:155-167`).
   - `internal/core/telephony.go`:
     - `callBody` (`:74-80`) gets `CallID`, `Waiting` and `HandsFree`;
     - the view writes inside the locked section at `:137-166` store them;
     - on cancel, set `lastCall{id, end: "hangup" | "missed", at}`;
     - `dropCall` (`:222-236`) sets `end: "lost"`;
     - `missedCall` gets the id;
     - an old app's packet without `callId` still works, with an empty id.
   - `internal/core/device.go`: the `CallView` / `MissedView` fields
     (`:133-144`) with JSON `id`, `waiting`, `handsFree`, and `lastCall`
     (`:~299`).
     - `HandsFree` is cloned with `slices.Clone` in `view()` (`:348-355`), as
       `api.go:156-157` does.
     - `lastCall` stays in the snapshot for 30 s.
     - `plugins()` (`:256-283`) lists `telephony.action` when
       `accepts(TypeFluxTelephonyAction)`.
   - `internal/core/api.go`: the params `ID` (`:239`) and `Action` (`:245`)
     already exist. Add a `call.action` case modelled on `dnd.set`
     (`:496-509`), and the name in `deviceMethods` (`:515-525`). It refuses
     unless the device is paired, online, `callOK`, ringing, not waiting, the
     id is non-empty and equal, the action is answer or reject, and the type
     is accepted.
   - `docs/ipc.md:~165-216`: the new fields and the method.

   Verify:
   - `go test -race ./cmd/... ./internal/... ./scripts/...`, `go vet ./...`,
     `gofmt -l .` (empty).
   - New tests in `telephony_test.go` (template `dnd_test.go:210-249`):
     - the fields are stored, including from an old packet with no id;
     - `lastCall.end` is `hangup`, `missed` or `lost` for the three endings;
     - `call.action` is refused for each case above, and succeeds by sending
       exactly `flux.telephony.action {action, id}`.
4. **Flux PR and release** (Claude).
   - Open a PR from `feat/80-call-action` linking #80 and this plan, then
     comment `@codex review`. The `reviewers:` codex and agy review the diff.
   - `build.yml` doesn't run on PRs, so start it on the branch:
     `gh workflow run build.yml --ref feat/80-call-action -R olafkfreund/nixarchy-flux`.
     Merge only after it passes.
   - Release per `docs/releasing.md`. The owner installs the APK on the Pixel
     and grants the two new permissions (the prompt from step 1).
   - Record the previous release tag and APK version code in the PR, for
     rollback.

   Verify:
   - the workflow run on the branch passes;
   - the release exists;
   - the Pixel runs the new version (`flux-cli` device info).

   The `telephony.action` capability check happens at step 13.

### Nixi (`/mnt/code/Source-home/GitHub/nixoarchy-snowflake`)

5. **`app/phone.py`** (coder).
   - `:20`: add `call.action` to `METHODS`.
   - `:128-130`: map the plugin `telephony.action` to the `can` entry
     `answer`.
   - Check that `devices()` passes `call.id`, `call.waiting`,
     `call.handsFree`, `lastCall` and `missedCall.id` through. Add `lastCall`
     to the copied keys (`:134`).

   Verify: `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_phone.py`,
   with new cases for the allowlist, the `can` mapping and the passthrough.
6. **`app/hfp.py`, new** (codex), plus `tests/test_hfp.py` and
   `tests/fixtures/pw-dump-hfp.json`.
   - `class Hfp`: Gio on the session bus, loaded lazily, with a failure
     logged once (the pattern of the notification watch,
     `app/server.py:3300-3440`).
   - Discovery:
     - subscribe to `InterfacesAdded`, `InterfacesRemoved` and
       `PropertiesChanged` from the service name, on all paths;
     - `GetManagedObjects` on the root, then on each `agN`;
     - on `NameOwnerChanged`, clear every record and reseed.
   - Records:
     - gateway `{path, address, transport}`;
     - call `{path, ag, state, number, name}`.
   - `answer(path)`, only while incoming, and `hangup(path)`. Both return
     `{ok, error}`, with `InvalidState` and `Failed` mapped and never raised.
   - `audio_here(call)`: the call is `active` and its gateway's transport is
     `active`.
   - `calls_on(ag)`, to detect a second call.
   - `streams(address)`, from `pw-dump` JSON: the numeric ids of the
     `Stream/Output/Audio` and `Stream/Input/Audio` nodes with that
     `api.bluez5.address` and the profile. Resolved fresh on every press.
   - `volume(+1|-1)`: `wpctl set-volume -l 1.5 <down id> 5%+|5%-`.
     `mute()`: `wpctl set-mute <up id> toggle`. Both then read back with
     `wpctl get-volume <id>` and return the volume and mute state read back.
   - `any_call()` and the `on_change` callback.
   - Subprocesses use `pdeathsig_preexec` (`app/floor.py:10`).

   Verify: `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_hfp.py`,
   with a fake connection object and no real D-Bus or PipeWire. It covers:
   - discovery at both levels;
   - a reseed on an owner change;
   - `"withheld"`;
   - `audio_here` following the transport;
   - a second call seen;
   - the error mapping;
   - stream-id lookup from the fixture;
   - the exact `wpctl` argv;
   - `SpeakerVolume` never written.

   Traps:
   - Tests never import `server` under the real HOME. Test servers use the
     `nixi_env` helper (#176).
7. **`app/server.py`: `class Call` and `/api/call`** (codex), plus
   `tests/test_call.py`.
   - `class Call` next to the phone code (about `:7900-8070`):
     - correlation, path, `id`/`gen`, phases, keys, note, privacy and missed
       dedupe, exactly as in the summary above;
     - `publish()` → `BUS.pub(t="call", ...)`;
     - `clear()` → `gone`;
     - `visible()`;
     - `current_event()` for a new SSE connection.
   - SSE: in `Handler.events()` (`:10325-10333`), after the `situation` and
     `mirror` events, send `Call.current_event()` when it isn't `None`.
   - `/api/call` POST, beside `/api/phone/send` (`:10083`), with the token,
     `click_ok` (`:83`), the lock, the re-checks, the busy flag, the dispatch
     and the watchdog as in the summary. Not in `TOOL_PATHS` (`:88`).
   - Language keys `call.*` in `app/lang/en.json`: the notes, the labels and
     the key names.

   Verify: `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_call.py`,
   with fake `Phone` and `Hfp` objects. It covers:
   - correlation in both arrival orders, with the same `id`;
   - every path, including the on-phone and second-call notes;
   - a `gen` bump on a path change;
   - names, including "Unknown caller", and numbers only with no name and
     only while unlocked (`None` counts as locked);
   - `answered_at` not taken from `since`;
   - `ended` only after answer and only on `hangup` or `disconnected`;
   - `gone` for `lost`, lock and Phone off;
   - one missed card in the Flux-first, HFP-first and HFP-only cases;
   - `/api/call` without the click key → 403, a stale `gen` → `stale`, while
     locked → refused, a double POST → `busy`;
   - the watchdog timing;
   - `phone_on_screen()` true while visible;
   - the SSE first event gated.

   `test_lang` will fail until step 10, so don't run the full suite yet.
8. **`app/server.py`: wiring and the ringtone** (coder).
   - `phone_state` (`:8039`) and `Hfp.on_change` → `Call.sync()`.
   - `Hfp` starts where `Phone` starts and stops in `phone_reset()`
     (`:8622`), which also calls `Call.clear()`.
   - `Ambient.sense` (`:2340`): when `cls.locked` changes at `:2373`, call
     `Call.sync()`, which clears on lock.
   - `phone_call_sync` (`:7974`): `now = phone_on and (Phone.call_active or
     Hfp.any_call())`. Also run `Speaker.stop()` and cancel a listen when
     `Call` reports the edge to answered.
   - `phone_on_screen` (`:7796`): `or Call.visible()`.
   - Missed: a helper shared with `phone_on_missed` (`:7903`), keyed by the
     call id, which `Call` uses for HFP-only misses.
   - Ringtone:
     - `ring_pcm()` builds the trill once as raw s16le mono at the player's
       rate (`:6033-6044`) and caches it;
     - a ring thread plays it every 3 s while `Call` is ringing and the gate
       holds;
     - it waits while `Speaker` is speaking or has anything queued;
     - it stops on any phase change, lock or Phone off.

   Verify:
   - `nix develop .#ci -c python3 -B .github/ci/run_tests.py test_call.py test_phone.py test_phone_flux_more.py`;
   - new cases for the lock edge (clear and ring stop without a telephony
     event), `phone_reset` stopping `Hfp`, `Ambient.phone_call` for an
     HFP-only call, the ring gate with proactive and TTS off, the ring
     waiting for speech, and the exact PCM bytes (a length and sample-format
     check).
9. **`app/static/index.html`: the handset** (coder), plus
   `tests/handset_fit.mjs` and `tests/test_handset_fit.py`.
   - CSS: next to `#mailPop` (`:165-181`) and `#stgTab` (`:377-381`):
     - the shake and blink keyframes, plus the reduced-motion entries in the
       `@media` block at `:398`;
     - hide `#handset` for `body.calm` only. Do not add it to the
       `body.hover` / `body.bar` hidden list at `:397`;
     - the bar pill styles.
   - HTML: SVG `#handset` and `#callPill` next to `#stgTab` (`:870`).
   - JS:
     - a `HANDSET` module handling `t:"call"` in the event switch (by
       `ev.t==='phone'`, `:2826`);
     - the side from `stgSide` (`:3096`);
     - the timer from `answered_at`;
     - keys `POST /api/call` with
       `hdr(Object.assign({'Content-Type':'application/json'},CLICKKEY.hdr()))`
       as at `:3196`, without the `isTrusted` / `pointerType` guard at `:3193`,
       so Enter and Space work;
     - `stale` and `busy` replies re-render;
     - key events stop propagation as at `:3469`.
   - Window and input:
     - `callWant` joins the `max` in `sizeWindow()` (`:4722`), so the window
       grows for the handset;
     - `sendRegion` (`:4733`) adds the handset in normal mode, and in hover
       mode returns the handset's rect instead of `[]` while it shows. Bar
       mode adds the pill;
     - `idleActive()` (`:4789`) is true while the handset shows.

   Verify: the page test, modelled on `tests/stages_fit.mjs` and
   `tests/test_stages_fit.py`, on headless Chromium with `--disable-gpu`
   only. It covers:
   - each phase and path rendering, with only the `keys` enabled;
   - the POST body `{id, gen, act}`, from a click and from Enter and Space;
   - focus rings and `aria-label`s;
   - reduced motion with no running animations;
   - zoom 1 and 1.5 without clipping, after the simulated `size:` message;
   - hover mode showing the handset and the `region:` message holding its
     rect;
   - the bar pill;
   - calm mode hidden.

   Then screenshots for the owner's look-over, from headless Chromium.

   Traps:
   - Never use a desktop or GPU Chrome (it hung the AMD GPU twice).
   - Our own drawing only.
10. **Text and docs** (agy).
    - `app/lang/nb.json` and `pl.json`: every `call.*` key with the same
      slots. Do not edit the `_review` lists (`tests/test_lang.py:348-349`).
    - `docs/GUIDE.md`: a "Take calls on Nixi" section with the pairing steps
      ("Phone calls" on, "Media audio" off) and the three paths.
    - A README feature line.

    Verify, the full suite now:
    `nix develop .#ci -c python3 -B .github/ci/run_tests.py --exclude test_character_fit.py --exclude test_accessories_fit.py`.
11. **Nixi PR** (Claude).
    - Open a PR from this branch linking the intent, spec and plan, and say
      which steps the coder, Codex and agy did. Comment `@codex review`. The
      `reviewers:` codex and agy review the diff.
    - CI must pass: the `test` and `fit-slow` jobs, plus the flake and package
      checks.
    - Squash-merge. Record the previous `main` commit for rollback.

    Verify: the PR is merged, and the CI on the merge commit is green.

Step 9 deviations, as built:
- The handset places itself with its own `HS.place()`, using the room test from `stagePlace()`, and takes the side away from an open stage board.
- `callWant` asks for 230 px.
- `sendRegion` builds its rects before the hover branch, so hover can return the handset.
- The red key is `reject` while ringing and `hangup` in a call.
- The reduced-motion rules sit in their own `@media` block.
- SSE sends `{t:"call", phase:"gone"}` on connect when there is no call, so a reconnect drops a stale handset.

### nixos_config (`~/.config/nixos`)

12. **`calls.enable` and the bump** (Claude).
    - Create a worktree on `feat/115-nixi-calls` from `origin/main`.
    - Add the option in `hosts/common/nixos/omarchy-nixi-companion.nix`
      writing the two files exactly as in the summary.
    - Set `calls.enable = true` in `hosts/p620/nixos/nixarchy.nix`.
    - Run `nix flake update nixi-companion nixarchy-flux` and nothing else.
    - Open a PR and comment `@codex review`. Wait for CI, then merge.

    Verify:
    - `nix build .#nixosConfigurations.p620.config.system.build.toplevel`;
    - `nix store diff-closures /run/current-system ./result` shows only the
      two packages and the home-manager files;
    - record the p620 generation (`readlink /nix/var/nix/profiles/system`) and
      the two old input revisions in the PR.

    Traps:
    - `~/.config/nixos` may be dirty with someone else's work. Never touch it.
    - If `nixarchy-theme.nix` differs from main there, copy it into the
      deploy worktree.
    - Never touch p510.
13. **Deploy p620** (Claude).
    - Make a fresh worktree detached at `origin/main` (after the merge),
      announce on the agent bus, then `AGENT_BUS_ANNOUNCED=1 nh os switch .`.
    - Restart `pipewire` and `wireplumber` (user units), then Nixi with the
      Hyprland signature taken from `/run/user/1000/hypr`.

    Verify:
    - `pactl list short sources` shows `nixi-call-echo-cancel-source`;
    - `wpctl status` otherwise looks as before;
    - Nixi and `fluxd` run the new store paths;
    - `flux-cli` lists `telephony.action` for the Pixel;
    - `server.log` has no Hyprland socket errors;
    - no failed units.
14. **Live test with the owner on p620** (Claude and the owner). This needs a
    second phone to call from.
    1. The owner pairs the Pixel and sets "Media audio" off. Record
       `wpctl inspect` of the phone's card (check `device.form-factor` and
       `bluez5.auto-connect`) in the PR.
    2. A call rings the handset: the name, Nixi's announcement, then the ring.
    3. Answer on the handset: two-way audio, and the caller hears no echo.
       Record the stream nodes and their links (`wpctl status`, `pw-link -l`)
       to confirm that the uplink comes from `nixi-call-echo-cancel-source`.
    4. Mute and volume work, and the readback matches. Hang up from the
       handset.
    5. The far side hangs up: "Call ended".
    6. Unlink Bluetooth (`bluetoothctl disconnect`). The handset shows
       "Phone". Answer on it, and the phone answers and shows "On phone".
       Another call: reject works.
    7. Play music on the Pixel: it stays on the phone.
    8. With the Pixel Buds connected, a call answered on the buds stays there,
       and the handset shows "On phone".
    9. An unanswered call gives one missed card.

    Any failure: fix through steps 5-13, and update this plan in the same
    commit. Fallbacks:
    - match the Pixel by Bluetooth address when `device.form-factor` isn't
      `phone`;
    - drop `a2dp_sink` from this host's roles if check 7 fails;
    - leave the host unlinked if check 8 fails.
15. **razer** (Claude, after step 14 passes and the owner agrees).
    - Set `calls.enable = true` for razer, open a PR, merge, then deploy from a
      worktree detached at `origin/main` with `just deploy-via-p620 razer`
      (`nh --target-host` can't read sudo).
    - The owner pairs the Pixel with razer, with "Media audio" off.
    - Run checks 2-5, 7 and 8 on razer.
    - The two-host check: with both awake and the Pixel linked to p620, razer
      shows "Ringing on p620" with no keys.

    Verify: the checks pass, and the razer generation is recorded in the PR.

## Tests

| Repo | Command | Expected |
|---|---|---|
| nixarchy-flux | `go test -race ./cmd/... ./internal/... ./scripts/...`; `go vet ./...`; `gofmt -l .` | pass, nothing listed |
| nixarchy-flux | from `android/`: `./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug` | pass |
| nixarchy-flux | `gh workflow run build.yml --ref feat/80-call-action -R olafkfreund/nixarchy-flux` | the run passes |
| nixoarchy-snowflake | per step: the focused `run_tests.py <files>` | pass |
| nixoarchy-snowflake | after step 10: `nix develop .#ci -c python3 -B .github/ci/run_tests.py --exclude test_character_fit.py --exclude test_accessories_fit.py`, then PR CI (`test`, `fit-slow`) | pass |
| nixoarchy-snowflake | plugin sandbox tests | not needed: no change to `app/plugins.py` or the wrapper PATH |
| nixos_config | `nix build` p620 (razer at step 15), `nix store diff-closures` | only the intended changes |
| live | steps 14 and 15 | all pass |

## Rollback

- **Calls off on a host:**
  1. set `calls.enable = false`, merge, and deploy;
  2. restart `pipewire` and `wireplumber`, which unloads the echo canceller
     and the rules;
  3. on the Pixel, turn "Phone calls" off for that host, or unpair it
     (`bluetoothctl remove <addr>`). Otherwise the HFP link stays and calls
     can still route there.
  The handset keeps working on the phone path.
- **Whole feature:**
  1. revert the nixos_config bump PR, so the inputs go back to the recorded
     revisions, and deploy;
  2. check that Nixi and `fluxd` run the old store paths and the recorded
     generation is active.
  A fast fallback per host is `nixos-rebuild switch --rollback` on p620
  (razer: `just deploy-via-p620 razer` from the reverted main), then the
  same checks.
- **Phone app:** Android refuses an older version code over a newer one. Going
  back means uninstalling Flux on the Pixel, which loses its pairing and
  settings, then installing the recorded older APK and pairing again. The new
  packet fields are extras that an old fluxd ignores, so a new app with an old
  fluxd also works. That is the preferred rollback.
