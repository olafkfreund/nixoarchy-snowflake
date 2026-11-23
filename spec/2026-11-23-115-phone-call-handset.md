---
status: approved
issue: 115
intent: intent/2026-11-23-115-phone-call-handset.md
---

# Spec: take phone calls on the host with a ringing retro handset

## Design

Two paths carry a call, and one handset shows both:

- **Host path (Bluetooth):** the phone is paired with the host as a
  hands-free unit. PipeWire's telephony service reports the call, its number
  and its state, and answers and hangs it up. WirePlumber links the call's
  audio to the desk speakers and an echo-cancelled mic.
- **Phone path (Flux):** no hands-free link. Flux reports the call and the
  contact name, and a new Flux action asks the phone to answer or reject a
  ringing call. The audio stays on the phone.

```
phone ──HFP──► PipeWire bluez5 ──D-Bus org.pipewire.Telephony──► app/hfp.py ─┐
  │        └─ SCO streams ◄─WirePlumber links─► default sink / EC mic        │
  └──Flux LAN──► fluxd ──socket──► app/phone.py ─────────────────────────────┤
                                                       app/server.py: Call ──► BUS t:"call" ──► page #handset
                                              page keys ──POST /api/call (token + click key)──► Call.act()
```

### 1. Bluetooth and audio on the hosts (`nixos_config`)

Checked on p620 and razer: both controllers already advertise **Handsfree**
(UUID 0x111e, the `hfp_hf` role), and PipeWire 1.6.11 runs
`org.pipewire.Telephony` on the user bus. No role change is needed.

How PipeWire 1.6.11 and WirePlumber 0.5.19 carry the call (from their
source, confirmed by both reviewers): while the phone sends call audio to
this host (SCO transport `pending`/`active`), the phone's card gets two
dynamic stream nodes with `api.bluez5.profile = "headset-audio-gateway"`:

- `Stream/Output/Audio`: the caller's voice;
- `Stream/Input/Audio`: what the caller hears from us.

WirePlumber sets `node.autoconnect = true` on both
(`scripts/monitors/bluez/name-node.lua:64-68`), linking them to the default
sink and the default source. Nixi does not bridge audio itself. Config only:

- **Echo-cancelled uplink.** A home-manager
  `pipewire.conf.d/61-nixi-call-echo-cancel.conf` copies meetingai's working
  module on p620 (`60-meetingai-echo-cancel.conf`: `aec/libspa-aec-webrtc`,
  `monitor.mode = true`, `ifexists nofail`), with its own nodes
  `nixi-call-echo-cancel-source` and `-capture`. In monitor mode the reference
  is the default sink's monitor, where the caller's voice plays. So the
  source is the mic without the caller. The source sleeps with no reader.
  meetingai is on p620 only, and calls must not depend on it.
- **Uplink target.** A WirePlumber rule matching
  `api.bluez5.profile = "headset-audio-gateway"` and
  `media.class = "Stream/Input/Audio"` sets
  `target.object = "nixi-call-echo-cancel-source"`. The downlink keeps going
  to the default sink.
- **Phone audio stays call-only.** The hand-made
  `~/.config/wireplumber/wireplumber.conf.d/bluetooth-a2dp-autoconnect.conf`
  auto-connects `a2dp_sink a2dp_source` on every card. A rule matching
  `device.form-factor = "phone"` sets `bluez5.auto-connect = [ hfp_ag ]`
  (`hfp_ag` names the phone's side, which both reviewers confirmed). Rules
  load in file-name order and the later match wins. The file is
  `z-nixi-phone.conf`, so it sorts after that unmanaged file and any
  numbered file. Auto-connect only governs what the host starts. A
  phone-initiated media link is stopped by the pairing step below and
  checked live.
- **Pairing** is a one-time owner step per host, in the companion's docs:
  `bluetoothctl` pair, trust, connect. Then, on the Pixel, the host's entry
  has "Media audio" off and "Phone calls" on. Nothing pairs automatically.
- All of it sits behind a new option in
  `hosts/common/nixos/omarchy-nixi-companion.nix`, `calls.enable`, set on p620
  first and on razer after the p620 live test (owner decision 1).

### 2. Host path in Nixi (`app/hfp.py`, new)

A narrow client for `org.pipewire.Telephony`, built like the notification
watch (`app/server.py:3320-3440`: Gio from PyGObject on the session bus, no
new dependency).

- **Discovery at both levels.** The root `/org/pipewire/Telephony`
  ObjectManager announces audio gateways (`/…/agN`). Each gateway's own
  ObjectManager announces its calls (`/…/agN/callM`). One signal
  subscription for `InterfacesAdded` / `InterfacesRemoved` /
  `PropertiesChanged` from the service's bus name covers every path. Start
  with `GetManagedObjects` on the root and on each gateway. On
  `NameOwnerChanged` (PipeWire restarted), drop everything and start again.
- Records:
  - gateway `{path, address, transport}`: `transport` is the
    `AudioGatewayTransport1` `State`;
  - call `{path, ag, state, number, name}`: `number` from
    `LineIdentification`, where `"withheld"` means no number.
- **Audio here** means the call is `active` and its gateway's transport is
  `active`. Only then does the handset offer volume and mute. A call
  answered on the phone or on the buds has no transport here, and the
  handset shows "On phone" without audio controls.
- `answer(path)`: `Call1.Answer()`, only valid while `incoming`.
  `hangup(path)`: `Call1.Hangup()`, which also rejects an incoming call. An
  `InvalidState` or `Failed` error comes back as `{ok:false}` and is never
  raised.
- **Volume and mute** act on the live stream nodes, found with `pw-dump` by
  `api.bluez5.address` = the gateway's address, the profile and the
  `media.class`. Their numeric ids are re-resolved on each press, because
  `wpctl` takes ids, not names:
  - volume: `wpctl set-volume -l 1.5 <downlink id> 5%+` / `5%-`;
  - mute: `wpctl set-mute <uplink id> toggle`.
  The indicator shows the state read back with `wpctl get-volume`, not the
  state we asked for. The gateway's HFP `SpeakerVolume` stays untouched: it
  is the phone's own volume.
- More than one call on a gateway (`waiting`, `held`): the handset shows the
  first call, disables every key, and says "Second call: use your phone".

### 3. Phone path in Flux (`nixarchy-flux`)

Flux today has no call identity: `Since` is fluxd's own clock at receipt
(`internal/core/telephony.go:135`), and the phone's `CallTracker`
(`core/Calls.kt:28-77`) holds no id or time.

- **Android call id.** `CallTracker` makes a random 64-bit hex id when the
  line leaves idle, and keeps it until the line is idle again. `CallPackets.body`
  (`:88-98`) sends it as `callId` in every `flux.telephony` packet.
- **Who holds the audio.** Each `flux.telephony` packet also carries
  `handsFree`: the names of the Bluetooth hands-free devices connected to the
  phone (`BluetoothHeadset` profile proxy, needing `BLUETOOTH_CONNECT`, asked
  for with the call permissions). The hosts' adapter names are their host
  names (`bluetoothctl list` shows `p620` and `razer`).
- **Daemon.** It stores `callId` and `handsFree` in `dev.call` and the
  snapshot (`call.id`, `call.handsFree`). A new device method,
  `call.action`, takes `action` (`answer` | `reject`) and `id`. It refuses
  unless the device is paired and online, `callOK` is set, the state is
  `ringing`, `id` equals `dev.call.ID`, and the phone accepts
  `flux.telephony.action` (`accepts(...)`, as `dnd.set` at `api.go:496-509`).
  Then it sends `flux.telephony.action {action, id}`. The params struct gets
  an `ID string` field. Add the method to `deviceMethods` and to
  `docs/ipc.md`. When the phone accepts the type, fluxd lists
  `telephony.action` in the device's plugins, so Nixi can tell.
- **Android.** `ANSWER_PHONE_CALLS` and `BLUETOOTH_CONNECT` in the manifest,
  asked for with the existing "Call alerts" permissions
  (`ui/SyncScreen.kt:186-193`). The type goes into `INCOMING`
  (`protocol/Identity.kt:125-138`). A new `CallControl.kt` is routed from
  `Plugins.handle` (`core/Plugins.kt:90`). A pure guard function, unit-tested,
  acts only when:
  - the permission is held;
  - `CallTracker`'s state (fed by `TelephonyCallback`; the deprecated
    `getCallState()` is not used) is ringing;
  - its id equals the packet's `id`.
  Then it calls `TelecomManager.acceptRingingCall()` or `endCall()`. While the
  line is ringing from idle there is exactly one call, so `endCall()` can only
  reject that one.
- **No hang-up through Flux.** The intent asks the phone path for answer and
  reject only. With a call in progress, `endCall()` takes no id and could hit
  a waiting call. So after a phone-path answer, the handset shows "On phone"
  with no keys.
- **Nixi** adds `call.action` to `Phone.METHODS` (`app/phone.py:20`) and
  `telephony.action` to the `can` set in `Phone.devices()` (`:128-130`).

### 4. One call state in Nixi (`app/server.py`, `class Call`)

- **Correlation.** An HFP call and a Flux call are the same call when both
  appear within 15 s, and their numbers match on the last 8 digits, or one
  side has no number. There is one phone, so one live call at a time. The
  merged call has one random `id` for its whole life.
- **Path.**
  - **host** while this host has the HFP call;
  - **phone** while only Flux has it, and the phone's `handsFree` list names
    no other host in the companion's fleet peers (the `nixi-fleet` list).
  - When another fleet host holds the hands-free link, this host is
    **watch**: it shows the caller, with no keys and a note naming that host
    ("Ringing on p620"). That is the intent's two-host rule.
  Every change of path bumps `gen`.
- **Name and number.** Flux's contact name first, then HFP `Name`. Flux's
  `"Unknown caller"` placeholder counts as no name. The number comes from
  HFP, then Flux. It is published only when there is no name (owner
  decision 3).
- `Ambient.phone_call` becomes `Phone.call_active or Hfp.any_call()`, so the
  wake word, push-to-talk, follow-ups, nudges and unasked speech stay paused
  (the existing gates at `:1678`, `:3006`, `:4968`, `:7645`, `:9718`) for as
  long as either side still reports the call. `Speaker.stop()` and the
  listen cancel in `phone_call_sync` (`:7974`) also run on the edge to
  answered, so an announcement still playing is cut off.
- **Bus.** `t:"call"` with
  `{id, gen, phase: ringing|active|ended|gone, path: host|phone|watch, who,
  number, answered_at, audio_here, muted, volume, keys:[…], note}`.
  `answered_at` is our clock at the first `active` (host) or `talking`
  (phone) we see, never Flux's `since`.
  - `ended` is used only when the call had been answered and we saw it end
    (`disconnected` after `active`, or a Flux cancel after `talking`). It
    shows "Call ended" for 2 s.
  - `gone` means the handset leaves at once. That covers a link drop with no
    end seen, the desk locking, Phone turned off, or a lost Flux socket with
    no HFP call. A page that connects or reloads gets the current `t:"call"`,
    or `gone`.
  - A ringing call that ends unanswered gives one missed card. Flux's
    `missedCall` uses the existing `phone_on_missed` (`:7903`). An HFP-only
    call makes the same `phone_missed` card through a shared helper, and a
    call key keeps it from appearing twice.
- **Keys.** `POST /api/call {id, gen, act}`, with `act` in `answer`,
  `reject`, `hangup`, `mute`, `vol_up`, `vol_down`.
  - It needs the window token and the click key (`click_ok`, `:83`), as
    phone send does (`:10085`), and is not in `TOOL_PATHS`. An agent, a hook
    or the CLI, which hold only the token, cannot answer a call. The Flux
    socket is a same-user Unix socket, and its trust boundary is the user
    account, as for `sms.send` today.
  - At dispatch, under the call's lock, it re-checks: `phone_on`, desk
    unlocked, the `id` and `gen` are current, and `act` is in the call's
    `keys`. A mismatch returns `{ok:false, stale:true}`, and the page
    re-renders. One action runs at a time per call, so a double click sends
    one.
  - host → `Hfp`; phone → `call.action` with the call's Flux `id`. If the
    phase doesn't change within 6 s, the note says "Didn't work. Use your
    phone".
- **Ringtone.** A short two-tone trill, synthesised in Python with `wave`
  (our own sound, no asset), played every 3 s while ringing, quietly, through
  the existing player (`:6035`). It has its own gate: `phone_on`, desk
  unlocked, not in a meeting, not do-not-disturb, not asleep, not muted. That
  does not depend on proactive mode or the voice engine. It waits while
  Nixi's "X is calling" announcement plays and starts after it. It stops on
  any phase change.
- **Screenshots.** `phone_on_screen()` (`:7796`) also returns true while the
  handset is shown, so `/api/capture` refuses as it does for phone cards.
- Flux's own desktop "Call from" notification stays. Flux closes it on
  answer (`telephony.go:191`). Hiding it needs a Flux setting. That is a
  follow-up if it feels doubled.

### 5. The handset on the page (`app/static/index.html`)

- `#handset`: an inline SVG candybar phone, about 92×190 px at page zoom 1,
  beside Nixi on the side with room (as `stgSide`, `:3096`). Our own
  design:
  - a rounded body and a stub antenna;
  - a green-lit LCD with a pixel-look text style (existing fonts plus
    `image-rendering`; no brand font or logo);
  - a soft-key bar, a big green key and a big red key, a mute key, and a
    side volume rocker.
  Colours come from the theme tokens, with the LCD tinted from `--acc`.
- States:
  - ringing: shake (CSS keyframes) and a blinking backlight. The LCD shows
    a bell, the name, or the number on a second line, and the soft-key bar
    reads "Host" or "Phone";
  - active: still, with the name, an `mm:ss` timer from `answered_at`, and a
    mute glyph and volume bar when the audio is here;
  - on phone or watch: the note on the LCD, no keys;
  - ended: "Call ended" for 2 s, then it slides away.
  Only the keys in `keys` are enabled. The others are dimmed and inert.
- Each key is a real `<button>` with an `aria-label` and a visible focus
  ring. Enter and Space work, and the window's shortcuts stay off while a key
  has focus (as `stgTab`, `:3468`). The handset joins the input region
  (`sendRegion`, `:4757`).
- Reduced motion: no shake and no blink, a steady lit LCD reading "Ringing".
- Shown in the normal view and in hover mode. In bar mode it is a compact
  pill ("📞 Anna · Answer · Reject") with the same keys.
- Text lives in `app/lang/{en,nb,pl}.json` under `call.*` keys.

## Alternatives rejected

- **Carry the audio over Flux.** Android gives call audio only to privileged
  system apps (`CAPTURE_AUDIO_OUTPUT`).
- **Flux as the phone's default dialer (`InCallService`)** would give
  per-call control, but it replaces the phone's dialer app.
- **Hang-up through Flux.** `endCall()` has no call id, and with a call in
  progress it can hit a waiting call. Not asked for in the intent.
- **Nixi bridging audio with `pw-loopback`** (the first draft). WirePlumber
  already links the call streams, and a second bridge would fight it. A
  `target.object` rule gives the echo-cancelled mic with no process to
  manage.
- **oFono.** PipeWire's own telephony service already speaks HFP here, and
  oFono would compete with it for the link.
- **Reusing meetingai's echo canceller.** It is p620 only and belongs to
  another app. Its config is copied instead.
- **Matching calls by Flux `since`.** It is the desktop's clock, and the
  phone has nothing to compare it with.
- **A recorded ringtone file.** It would be an asset to license and ship.
  Synthesis is about 15 lines.

## Risks

- **Pixel Buds and two hosts.** The phone has one active call-audio device,
  and linking a host may pull calls off the buds. Checked live on p620
  before razer is turned on. Fallback: leave the host unlinked, and the
  handset still works on the phone path.
- **The `phone` form factor** may not be set for the Pixel. Then match its
  Bluetooth address instead (the owner's phone only).
- **Phone-initiated media.** If the Pixel ignores "Media audio" off, its
  music reaches the speakers. Checked live. Fallback: drop `a2dp_sink` from
  this host's `bluez5.roles`, which costs using the host as a Bluetooth
  speaker.
- **Deprecated Android call APIs** may fail on a future Android. The phone
  path then says "Didn't work. Use your phone", and nothing else breaks.
- **Echo.** Monitor-mode echo cancellation needs the call to play on the
  default sink, which it does by WirePlumber's default. A user-moved stream
  plays elsewhere and the caller may hear an echo. Checked live.
- **Correlation.** Two separate calls inside 15 s with no number on one side
  merge wrongly. One phone with call waiting out of scope makes this rare,
  and the keys go to the path that owns the call.
- **Privacy.** No audio is written anywhere. The number reaches the page only
  for a non-contact, only while unlocked, and is cleared on lock.
  Screenshots are refused while the handset shows.
- **Audio regression on p620.** A WirePlumber or PipeWire config change
  restarts audio. It is deployed through the normal `nixos_config` flow, with
  an announcement on the bus.

## Verification

- **nixoarchy-snowflake** (`nix develop .#ci -c python3 -B .github/ci/run_tests.py`, as CI runs them):
  - `tests/test_call.py`:
    - correlation, both arrival orders, and the `id` staying the same;
    - path host / phone / watch, with a `gen` bump on change;
    - name and number rules, including "Unknown caller";
    - `answered_at` never taken from `since`;
    - ended only after answered, `gone` on link drop, lock or Phone off;
    - one missed card for Flux-only, HFP-only and merged calls;
    - `/api/call` without the click key → 403, with a stale `gen` →
      `stale`, while locked → refused;
    - a double click dispatches once;
    - the ringtone gate and its wait for the announcement;
    - `Ambient.phone_call` true for an HFP-only call;
    - `phone_on_screen()` true while the handset shows.
  - `tests/test_hfp.py`, with a fake bus and no real D-Bus:
    - discovery at both levels;
    - reseed on an owner change;
    - "withheld" numbers;
    - `audio_here` following the transport state;
    - stream-id lookup from a recorded `pw-dump` JSON, and the `wpctl` command
      lines.
  - A page test in the style of `tests/stages_fit.mjs` (headless Chromium,
    `--disable-gpu`):
    - every phase and path renders;
    - only the `keys` are enabled, and the keys post `{id, gen, act}`;
    - reduced motion has no animation;
    - the handset fits at page zoom 1 and 1.5;
    - the bar pill renders.
- **nixarchy-flux:**
  - `go test -race ./internal/...`. `telephony_test.go` checks that `callId`
    and `handsFree` are stored. `call.action` is refused for a wrong `id`,
    the wrong state, offline, not paired, or not accepted.
  - Android `./gradlew :app:testDebugUnitTest`: the guard function and the
    `CallTracker` id lifecycle, next to `BridgesTest.kt`.
- **nixos_config:** `nix build` of p620 (razer later), and
  `nix store diff-closures` showing only the home-manager files and the
  companion. Then the effective properties: `wpctl inspect` on the phone's
  card and streams.
- **Live on p620.** This needs the owner, and a second phone to call from:
  1. pair the Pixel and set "Media audio" off;
  2. a call rings the handset with the name, the announcement, then the ring;
  3. answer on the handset: two-way audio, and the caller hears no echo;
  4. mute and volume work, and the readback matches; hang up from the
     handset;
  5. hang up from the far side: "Call ended";
  6. with the host unlinked, on the Flux path: answer on the handset answers
     on the phone, and the handset shows "On phone"; reject works;
  7. phone music stays on the phone;
  8. with the Pixel Buds connected, a call answered on the buds stays there,
     and the handset shows "On phone";
  9. an unanswered call gives one missed card.

  Then razer, plus both hosts awake: only the linked host offers keys.
