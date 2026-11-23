---
status: draft
issue: 115
intent: intent/2026-11-23-115-phone-call-handset.md
---

# Spec: take phone calls on the host with a ringing retro handset

## Design

Two paths carry a call, and one handset shows both:

- **Host path (Bluetooth):** the phone is paired with the host as a
  hands-free unit. PipeWire's telephony service gives the call, its number
  and its state, and answers and hangs it up. Nixi bridges the call's audio
  to the desk speakers and an echo-cancelled mic.
- **Phone path (Flux):** no hands-free link. Flux gives the call and the
  contact name, and a new Flux action asks the phone to answer, reject or
  hang up. The audio stays on the phone.

```
phone ──HFP──► PipeWire bluez5 ──D-Bus org.pipewire.Telephony──► app/hfp.py ─┐
  │                       └─ bluez source/sink ◄─pw-loopback─► speakers / EC mic
  └──Flux LAN──► fluxd ──socket──► app/phone.py ─────────────────────────────┤
                                                       app/server.py: Call ──► BUS t:"call" ──► page #handset
                                              page buttons ──POST /api/call (click key)──► Call.act()
```

### 1. Bluetooth on the hosts (`nixos_config`)

Facts checked on p620 and razer: both controllers already advertise
**Handsfree** (UUID 0x111e, the `hfp_hf` role), and PipeWire 1.6.11 already
runs `org.pipewire.Telephony` on the user bus. No role change is needed.

- **Phone audio stays call-only.** `~/.config/wireplumber/wireplumber.conf.d/bluetooth-a2dp-autoconnect.conf`
  (a hand-made file, not from `nixos_config`) auto-connects `a2dp_sink a2dp_source`
  on every `bluez_card.*`. On a phone that sends its music to the desk
  speakers. A new home-manager file, `wireplumber.conf.d/phone-hfp-only.conf`,
  matches `device.form-factor = "phone"` and sets
  `bluez5.auto-connect = [ hfp_ag ]`. Files load in name order, and the later
  rule wins: `phone-…` sorts after `bluetooth-…`, so do not give it a number
  prefix.
- **Echo cancellation for calls**, both hosts: a home-manager
  `pipewire.conf.d/61-nixi-call-echo-cancel.conf` copying meetingai's working
  setup (`60-meetingai-echo-cancel.conf` on p620: `aec/libspa-aec-webrtc`,
  `monitor.mode = true`, `ifexists nofail`), with nodes
  `nixi-call-echo-cancel-source` / `-sink`. In monitor mode the reference is
  the default sink's monitor, so the source is the mic without whatever the
  speakers play. Its own nodes keep calls independent of meetingai, which is
  on p620 only. The source sleeps with no reader, so it costs nothing between
  calls.
- **Pairing** is a one-time owner step per host (`bluetoothctl` pair, trust,
  connect), written in the companion's docs. Nothing pairs automatically.
- The module goes in `hosts/common/nixos/omarchy-nixi-companion.nix`, behind a
  new option `calls.enable`, set on p620 first and on razer after the p620
  live test (owner decision 1).

### 2. Host path in Nixi (`app/hfp.py`, new)

A narrow client for `org.pipewire.Telephony`, built like the notification
watch (`app/server.py:3320-3440`: Gio from PyGObject on the session bus, no
new dependency):

- Watch `org.freedesktop.DBus.ObjectManager` on `/org/pipewire/Telephony`
  (`InterfacesAdded` / `InterfacesRemoved`) and `PropertiesChanged` on each
  `org.pipewire.Telephony.Call1`. Keep one record per call:
  `{path, ag, state, number, name}`, with `state` from `State` and
  `number` from `LineIdentification` ("withheld" maps to no number).
- `answer(path)` calls `Call1.Answer()`. `hangup(path)` calls `Call1.Hangup()`,
  which also rejects an incoming call. An `InvalidState` error is reported
  back, not raised.
- **Audio bridge**, only while one call is `active` and the host answered or
  carries it: two `pw-loopback` processes, started with
  `pdeathsig_preexec` (as other children, `app/floor.py`), so they die with
  the server:
  - down: the AG's bluez source → default sink, `node.name=nixi-call-down`;
  - up: `nixi-call-echo-cancel-source` (or the default source when it is
    missing, logged once) → the AG's bluez sink, `node.name=nixi-call-up`.
  The bluez nodes are found with `pw-dump` by `api.bluez5.address` matching
  the AG. Both loopbacks stop on `disconnected`, on `InterfacesRemoved`, and
  when the server stops.
- **Volume and mute** act on the bridge, because the telephony API has
  neither: `wpctl set-volume <nixi-call-down> 5%+/-` (clamped 0–150%), and
  `wpctl set-mute <nixi-call-up> toggle`. When the call is answered on the
  phone instead (no bridge), the volume and mute buttons are hidden.
- One call at a time. A second call object (`waiting`, `held`) disables the
  handset's buttons and shows "Second call: use your phone". The call
  waiting feature is out of scope.

### 3. Phone path in Flux (`nixarchy-flux`)

- **Daemon** (`internal/core/api.go`): a new device method `call.action` with
  params `action` (`answer` | `reject` | `hangup`) and `since`. It refuses
  unless the device is paired and online, `dev.callOK` is set, `since`
  equals `dev.call.Since` (the only call key Flux has), and the state fits:
  `ringing` for `answer`/`reject`, `talking` for `hangup`. It checks
  `accepts(TypeTelephonyAction)` like `dnd.set` does (`api.go:496-509`) and
  sends `flux.telephony.action {action, since}`. Add the name to
  `deviceMethods` and to `docs/ipc.md`.
- **Android:** `ANSWER_PHONE_CALLS` in the manifest, asked for with the
  existing "Call alerts" permissions (`ui/SyncScreen.kt:186-193`). A new
  `CallControl.kt`, routed from `Plugins.handle` (`core/Plugins.kt:90`). The
  type is added to `INCOMING` (`protocol/Identity.kt:125-138`), so the
  desktop sees the capability. Before acting it re-checks: the permission
  is held, `TelephonyManager.callState` is `RINGING` for answer/reject and
  `OFFHOOK` for hangup, and `CallTracker`'s ringing start matches `since`.
  Then `TelecomManager.acceptRingingCall()` or `endCall()`. Any refusal is
  silent on the phone, and the desktop sees no state change.
- These Android calls are deprecated but still work for a managed cellular
  call with the permission (targetSdk 36). Flux does not become the dialer.
  Call waiting never shows as `ringing` in Flux (the line stays `OFFHOOK`),
  so a reject can't hit a waiting call.
- **Nixi** adds `call.action` to `Phone.METHODS` (`app/phone.py:20`).

### 4. One call state in Nixi (`app/server.py`, `class Call`)

- Inputs: `Hfp` records and `Phone.devices()[].call` / `missedCall`. A call
  is **host** when an `Hfp` call exists, otherwise **phone** when Flux has
  one. The name comes from Flux's contact first, then HFP `Name`; the number
  from HFP, then Flux.
- `Ambient.phone_call` becomes `Phone.call_active or Hfp.any()`, so the wake
  word, follow-ups, nudges and unasked speech stay paused (the existing
  gates at `:1678`, `:3006`, `:4968`, `:7645`, `:9718`). `Speaker.stop()` and
  the listen cancel in `phone_call_sync` (`:7974`) also run on the edge to
  answered, so an announcement still playing is cut off.
- Published on the bus as `t:"call"`, only while `phone_on` is set and the
  desk is unlocked:
  `{id, phase: ringing|active|ended, path: host|phone, who, number,
  answered_at, muted, can:{answer,reject,hangup,volume,mute}, note}`.
  `number` is sent only when there is no contact name (owner decision 3).
  The Phone tab and status line keep their "never numbers" rule. `id` is a
  random token per call, and the page sends it back.
- `answered_at` is our clock at the first `active` (host) or `talking`
  (phone) we see, never Flux's `since`, which counts from the first ring.
- Ended: `phase: "ended"` for 2 s when we saw the call end (`disconnected`,
  or Flux cancel after `talking`). A ringing call that ends unanswered goes
  to the existing missed-call path (`phone_on_missed`, `:7903`). When the
  link drops mid-call, the handset leaves without "Call ended".
- **Buttons:** `POST /api/call {id, act}` with `act` in `answer`,
  `reject`, `hangup`, `mute`, `vol_up`, `vol_down`. It needs the click key
  (`click_ok`, `:83`) as well as the token, like phone send
  (`:10085`), so no agent or script can answer a call and open the mic. A
  stale `id` gets `{ok:false}`. Host path → `Hfp`. Phone path → `call.action`
  with the call's `since`. If nothing changes within 6 s, the handset says
  "Didn't work. Use your phone".
- **Ringtone:** a short two-tone trill, synthesised in Python with `wave`
  (no asset, our own sound), played through the existing player
  (`:6035`, `paplay`) every 3 s while ringing, at a quarter volume. Off when
  `phone_may_announce()` (`:7989`) is false (locked, meeting, do not
  disturb, asleep) or `muted`. It stops on any change of phase.
- Flux's own desktop "Call from" notification stays. Hiding it needs a Flux
  setting or a notification rule, and Flux closes it itself on answer
  (`telephony.go:191`). A follow-up if it feels doubled.

### 5. The handset on the page (`app/static/index.html`)

- `#handset`: an inline SVG candybar phone, about 92×190 px at page zoom 1,
  beside Nixi on the side with room (as `stgSide`, `:3096`). Our own
  design: rounded body, a stub antenna, a green-lit LCD with a pixel-style
  font (drawn with the existing fonts and a CSS `image-rendering` look; no
  brand font or logo), a soft-key bar, a big green key and a big red key, a
  mute key, and a side volume rocker. Colours come from the theme tokens,
  with the LCD tinted from `--acc`.
- States:
  - ringing: shake (CSS keyframes) and a blinking backlight. The LCD shows
    a bell glyph, the name, the number on a second line when there is no
    name, and "Host" or "Phone" in the soft-key bar.
  - active: still, with the name, an `mm:ss` timer from `answered_at` and a
    mute glyph when muted.
  - phone path: "Answer on phone" stays on the LCD, and mute and volume are
    hidden.
  - ended: "Call ended" for 2 s, then slides away.
- Each key is a real `<button>` with an `aria-label` and a visible focus
  ring. Enter and Space work, and the window's shortcuts stay off while a key
  has focus (as `stgTab`, `:3468`). The handset is added to the input region
  (`sendRegion`, `:4757`).
- Reduced motion: no shake and no blink, a steady lit LCD with "Ringing".
- Shown in the normal view and in hover mode. In bar mode a compact pill
  ("📞 Anna · Answer · Reject") instead of the handset.
- Text in `app/lang/{en,nb,pl}.json` (`call.*` keys).

## Alternatives rejected

- **Carry the audio over Flux.** Android gives call audio only to privileged
  system apps (`CAPTURE_AUDIO_OUTPUT`).
- **Flux as the phone's default dialer (`InCallService`).** It would be a
  supported way to control calls, but it replaces the phone's dialer app,
  far too much for a companion.
- **oFono.** PipeWire's own telephony service already speaks HFP here, and
  oFono would be one more daemon fighting it for the link.
- **Reusing meetingai's echo canceller.** It is p620 only and belongs to
  another app. Its config is copied instead.
- **Letting WirePlumber link the call audio.** It doesn't route a hands-free
  source to the speakers by itself. Loopbacks give Nixi the start, stop,
  volume and mute it needs.
- **A recorded ringtone file.** It is an asset to license and ship.
  Synthesis is about 15 lines.

## Risks

- **Pixel Buds and two hosts** (p620, then razer): the phone has one active
  call-audio device. Linking to a host may pull calls off the buds. This is
  checked live on p620 before razer is turned on. Fallback: leave the host
  unlinked (handset still works on the phone path).
- **Bluez node names and loopback targets** differ by PipeWire version.
  Plan step 1 is a spike on p620 that records the real node properties.
- **The `phone` form-factor match** may not be set for every phone. If the
  Pixel lacks it, match by the device's address instead (the owner's phone
  only).
- **Deprecated Android call APIs** may fail on a future Android. The phone
  path then degrades to "Didn't work. Use your phone". Nothing else breaks.
- **Echo:** monitor-mode AEC needs the default sink to be the speakers the
  call plays on. A call while the default sink is something else is louder
  for the caller. Checked in the live test.
- **Privacy:** the bridge only runs during an answered call, and no audio is
  written anywhere. The number reaches the page only for non-contacts and
  only while unlocked.
- **p620 audio regression**: a WirePlumber or PipeWire config change restarts
  audio. It is deployed through the normal `nixos_config` flow, with an
  announcement on the bus.

## Verification

- **nixoarchy-snowflake** (`nix develop .#ci -c python3 -B .github/ci/run_tests.py`, as CI runs them):
  - `tests/test_call.py`: `Call` merge (host over phone, name and number
    rules, `answered_at` not from `since`), the ended and missed phases, a
    stale `id` refused, `/api/call` without the click key → 403, ringtone
    gated by `phone_may_announce`, and `Ambient.phone_call` true for an
    HFP-only call. `Hfp` is driven by a fake bus, and no real D-Bus is used.
  - `tests/test_hfp.py`: record parsing ("withheld"), the loopback command
    lines, and that stop kills both.
  - A page test in the style of `tests/stages_fit.mjs` (headless Chromium
    `--disable-gpu`): ringing, active, phone and ended states render, buttons
    post the right `act`, reduced motion has no animation, and the handset
    fits at page zoom 1 and 1.5.
- **nixarchy-flux:** `go test -race ./internal/...`, with new cases in
  `telephony_test.go` for `call.action` (refuses on a wrong `since`, on the
  wrong state, offline, or not accepted). Android
  `./gradlew :app:testDebugUnitTest` with a pure guard function in
  `CallControl` tested like `BridgesTest.kt`.
- **nixos_config:** `nix build` of p620 (and razer later), and
  `nix store diff-closures` showing only the home-manager files and the
  companion.
- **Live on p620**, needing the owner and a second phone to call from:
  1. pair the Pixel;
  2. a call rings the handset with the name and the ring;
  3. answer on the handset: two-way audio, no echo heard by the caller;
  4. mute and volume work, hang up from the handset;
  5. hang up from the far side;
  6. unpaired, Flux path: answer on the handset answers on the phone;
  7. phone music stays on the phone;
  8. with the Pixel Buds connected, a call answered on the buds stays there.
  Then razer.
