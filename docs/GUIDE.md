<p align="center"><a href="../README.md"><img src="../app/static/icon.png" width="96" alt="Nixi"></a></p>

<h1 align="center">The Nixi guide</h1>

<p align="center">What the snowflake companion can do, and how to set it up.<br>
New here? Start with the <a href="../README.md">README</a>.</p>

---

> **Nixi mode.** This build talks to the agent only through nixi's bridge. Features that would bypass nixi's rules are
> off: trust/root modes, model picker, updates, history, memory, projects, screenshots and live view. They are left out
> of this guide. Plugins still work, but you add them in Nix with `services.nixi.companion.plugins` (see
> [Plugins](#plugins)).

## Talking to it

| | |
|---|---|
| say **"Hey Nixi"** | wakes it up (on by default; Settings → Voice). "Hey Nixi, run the tests" works in one go |
| **left-click** it | talk; it stops listening when you stop talking |
| **right-click** it | the menu: talk · folder · hover · settings · hide. Click it (or right-click again) to close |
| **Ctrl+N** or say "new chat" | starts a fresh conversation (a new bridge process) |
| hold **Space** | push-to-talk |
| **click** it or tap **Space** while it works or talks | cuts it off and cancels the agent's turn |
| just **type** | a box pops up under it; **Enter** sends |
| **drag** it | park it anywhere; it remembers the spot. Drop it at a screen edge and it becomes the [top bar](#top-bar-notch) |
| **Esc** | close menus → cancel listening → stop the agent → shush → hide |
| `/mechanic` · `/guide` | switch nixi's trust level for this session |

**Hidden means off.** Once it is hidden (Esc, *hide* in the menu) the mic is closed. Bring it back with your hotkey or
`nixi-companion`. `nixi-companion stop` quits it completely.

**Push-to-talk hotkey.** Bind the press and release in your desktop:

| desktop | in your config |
|---|---|
| Hyprland | `bind = CTRL ALT, SPACE, exec, nixi-companion ptt-down` and `bindr = CTRL ALT, SPACE, exec, nixi-companion ptt-up` |
| sway / i3 | `bindsym Ctrl+Mod1+space exec nixi-companion ptt-down` and `bindsym --release Ctrl+Mod1+space exec nixi-companion ptt-up` |
| GNOME / KDE / others | shortcuts only fire on press there: bind `nixi-companion listen` instead (it stops when you stop talking) |

After it answers, keep talking for a few seconds and it still hears you, no "Hey Nixi" needed (`follow_up` in the
config).

**Interrupting.** Say **"stop"** (or "wait", "shh", "be quiet") while it talks. Say **"Hey Nixi, …"** mid-sentence to cut
in with something new. Settings → Voice → "Interrupt by voice".

Settings → Look → "Click through around it" lets clicks on the see-through space go to the window behind (off by default).

## Things it does instantly

These never wait for the agent:

| say | |
|---|---|
| "volume up" · "set volume to 40" · "mute" | sound |
| "pause" · "next song" · "what's playing" | music (via playerctl) |
| "brightness down" | screen brightness |
| "timer 10 minutes" · "remind me in 20 minutes to stretch" · "remind me at 5 to call mom" | a spoken ping and a notification |
| "how long is left" · "cancel my timers" | |
| "what time is it" · "what's the date" | |
| "open firefox" | any installed app |
| "lock my screen" | |

Everything else goes to the agent through the bridge.

## While it works

**The status pill.** A bright spark circles it and a pill up top says what it is doing and for how long, for as long as
the agent is busy. When it answers, the words appear as it says them.

**The terminal.** While the agent works the snowflake holds a small terminal like a piece of paper under its eyes. In
nixi mode it shows the tool titles only, not their output. It goes away when the answer starts. Settings → Look →
Terminal turns it off.

**Approvals.** In Mechanic mode, a card asks before a risky step. Say "yes", "no" or "always", or click / press Y / N.
No answer within 10 minutes counts as "no".

**Long answers.** When an answer is long or has code, a **↗ full answer** button appears under it, with a copy button on
every code block.

**When a long task finishes** while it is hidden, you get a desktop notification. You can also have it pop back up
(Settings → More).

## Messages and notifications

He can show your notifications himself, in place of the shell's popups. A click on a message, or on his bubble for it,
opens the app it came from.

Every switch in the table is in the companion's own **Settings → Look** tab, and **Say out loud** is there too. That tab
also has **Read mail subjects aloud** and **Pulse to the beat**, which the table below leaves out. nixi's README says
the same switches are in the **Nixi card's** Settings → Desktop; I did not check the card itself. Nothing happens until
you turn on the first two.

| Switch | What it does |
|---|---|
| Desktop companion | The master switch for everything below |
| Show notifications through him | While he is visible, he shows your notifications instead of the shell's popups, each with its own little reaction, and a click opens them. While a window is fullscreen, the shell shows them. One he cannot show within a few seconds (he is busy answering you, say) pops up as usual. Hide him, turn this off, or let him crash, and the normal popups are back within seconds |
| Show the notification text | Without it he shows only the kind and the app (“New message in Teams”) |
| Notification sounds | A short sound per kind (on by default once the takeover is on) |
| Say out loud | Which kinds he speaks: meetings only by default |
| Tie in meetings | He wears a tie while Meeting Mode is on, or when a calendar item is a minute away |
| Headphones for music | He wears headphones while a player is playing |
| Shades in fullscreen | He wears shades while a window is fullscreen |
| Notice a busy machine | A sweat drop when the CPU works hard for a while; a word when memory runs low |
| Remind me to move | After an hour unlocked he suggests a stretch. A lock of five minutes or more counts as a break |
| Welcome me back | After half an hour away: how many notifications came in, and your next meeting if the calendar is on |
| Glasses while coding | After a minute in a terminal or editor. Only the kind of window is checked, never its title |
| Nightcap at night | Between 23:00 and 05:00 |
| Dress for the weather | An umbrella in the rain, and he loves snow (needs the weather look) |
| Party hat on special days | New Year, Christmas, and birthdays in your calendar (needs the calendar) |
| Little jokes | Now and then a short line about the weather, the hour or a long session; never spoken. Edit them in the companion's `app/quips.json` |

Nothing watches your keyboard: “active” means unlocked, and the idle lock counts as a break. Nudges wait for a pause (an
unlock, a workspace switch, or a quiet moment), and he speaks at most one of them every ten minutes.

**A long command finished.** A long command can tell you it finished, when you are looking elsewhere:

```nix
{ services.nixi.companion.commandDone.enable = true; }   # bash and/or zsh via Home Manager
```

It sends “Done in 42s” (or “Failed after 42s (exit 1)”) with only the command's first word, as an ordinary
notification, so he shows it with a proud face. `commandDone.seconds` sets the threshold (default `30`). Inside herdr,
tmux or zellij it cannot tell whether you are watching that pane, so it notifies there even when you are.

**Privacy.** Notification text stays on your machine. He never logs it, never writes it to disk, and never gives it to
the agent. Critical alerts and anything carrying a code (2FA, one-time passwords) keep the shell's own popup, and he
never reads a code aloud. Nothing he says on his own opens the microphone. In a meeting he says nothing unasked; he
still answers when you ask him something, and “hey Nixi” is paused.

> [!NOTE]
> The takeover needs nixarchy's notification patch (903). On a shell without it, the popups stay as they are.

## Agent alerts

Coding agents in your terminal (Claude Code, Codex, agy) can tell the snowflake when they need you or when they are
done. A small mark above its head shows which agent it is: an orange sunburst for Claude, a dark `>_` square for Codex,
a blue ring with a dot for agy.

- **Needs you** (a permission prompt or a question): it looks pleading, flashes orange and says the agent and the
  project, and the reason if there is one. The mark pulses for up to a minute. Click the line under it, or the notch, to
  jump to that agent's pane or window. Hidden, you get a desktop notification instead.
- **Finished:** a happy face, a soft chime and a line like "✓ Claude finished · myproject". The mark shows a check for a
  moment. It does not talk, and when it is hidden it stays quiet.

Each kind has its own 30-second limit, so a finish never hides a question. Nothing the agents say is saved or logged,
and anything that looks like a password or key is dropped from the reason.

**Spoken summaries.** If your system runs `agent-say` with `speaker = "nixi"`, long turns also get a short spoken summary in his own voice, with his face and captions, and no second alert. Click, Space or Esc stops only the speech: it doesn't stop any work and doesn't open the mic. Settings → Voice → Agents mutes each agent and replays the last 5 summaries, which are held in memory only and are gone when he restarts. He stays quiet when hidden, in a meeting, or under Do Not Disturb, and if his voice is unavailable the summary stays as text.

Put these in the agents' own settings. Nixi must be running; if it is not, the lines do nothing and the agent carries on.

```sh
# ~/.claude/settings.json  Notification hook
sh -c 'command -v nixi-companion >/dev/null || exit 0; exec nixi-companion attention --from claude --hook'
# ~/.codex/config.toml  (Codex appends the JSON event as the last argument)
notify = ["sh", "-c", "command -v nixi-companion >/dev/null && nixi-companion attention --from codex --hook \"$1\"; exit 0", "codex-notify"]
# ~/.gemini/config/hooks.json  Stop (and Notification, if agy fires one)
sh -c 'command -v nixi-companion >/dev/null && nixi-companion attention --from agy --hook; echo "{}"'
```

Old hook lines (`nixi-companion attention --from claude is waiting for you`) still work; they count as "needs you".

Two limits: Codex has no approval hook, so it only ever says "finished". agy does not send its reply text, so its
"finished" has no reason line.

## Hover mode

Turn it on in the menu, in Settings → Look, or with `nixi-companion hover`. **It becomes your mouse cursor**: a small
plain dot that covers the real pointer. Clicks go straight through. On Hyprland the normal pointer is hidden underneath.

**Call it** (`nixi-companion`, `nixi-companion listen`, "Hey Nixi", or `nixi-companion hover` again) and it glides back
to its spot, ready to listen. `nixi-companion stop` always brings the normal cursor back. Works on Hyprland and X11
desktops. Other Wayland desktops do not tell apps where the mouse is, so it is not available on sway or KDE, and on GNOME
it only keeps up while the mouse is over older (X11) apps.

## Top bar (notch)

Instead of floating, it can **merge into an edge of your screen** as a black notch with just its eyes showing.

- **Turn it on:** drag it into a screen edge (top, bottom, left or right) and let go.
- **Get the snowflake back:** drag the notch away from the edge.
- **Talking:** the notch glows while you talk and pulses while it speaks.
- **Words and commands** drop out of the notch, then it tucks back in.
- **Click the notch** to open the menu around it; click again to close it.
- **Clicks go through** everything except a small area around the eyes.
- **Where it works:** Linux with layer-shell (Hyprland, sway, KDE Plasma, river, niri…) and X11 or GNOME (through
  XWayland). On sway there is no global mouse position, so push it past the edge to dock it.

## When idle

After a while with nothing going on, it **shrinks into the corner of its spot** nearest the screen edge. Set it in
Settings → Look → *When idle*:

- **Stay:** never shrinks.
- **Shrink** (the default): shrinks after about 20 seconds.
- **Shrink, then hide:** shrinks, then after about a minute hides. It is still awake: the wake word, notifications
  and agent alerts keep working.

It pops back up when something happens: you speak or call it, an agent needs you or finishes, a reminder or a
notification comes in, or you click it or rest the mouse on it. It stays up for a while after. It never shrinks while it
is busy, talking, listening, or has a menu, panel, question or approval open, or when it is a notch or hover cursor.
Sending it away on purpose still turns it fully off. When it pops up from hiding on its own, it does not take your
keyboard; only your own actions and approval or password prompts do.

---

## Its face and personality

- **Pupils:** slits, circles, dots, big circles, hearts and spinning stars. They follow its mood and what the agent is doing.
- **Moods while working:** reading (eyes sweep along lines), editing (concentrated squint), running a command (eyes on
  the terminal, a sweat drop), searching the web (darting around), asking permission (puppy eyes).
- **Other moods:** happy, beaming "^ ^", excited (stars), love (hearts, when you say thanks), shy, wink, curious,
  confused, surprised, scared, sad (droopy eyes and a tear when something fails), bored, annoyed, sleepy.
- **Motion:** it does not bob or bounce; all the life is in the eyes.
- **Talking:** in time with the words: mostly looking at you with small eye movements, glancing aside while it finds
  the words, a little nod at the end of a sentence, a head tilt on a question.
- **Personality:** it does not chatter: no greetings, no comments about your computer, no pop-ups you did not ask for.
  It gets sleepier late at night. Rub the mouse back and forth over it and it purrs. Click it too many times and it dodges.
- **Hanging out:** every few seconds of quiet it does a little routine: looks around, yawns, chases a spark with its
  eyes, hums and sways, peeks, stretches, whistles, or blinks a few times.
- **Sound effects:** soft little blips when it wakes up, opens its menu, finishes a task or reminds you. Settings →
  Voice → Sound effects.

## Characters and their voices

Settings → Look → **Character** picks who sits on your desk (`look.character` in `~/.config/nixi-companion/config.json`):

| Character | Value |
|---|---|
| **Snowflake** | `snowflake` (the default) |
| **Terminal** | `terminal` |
| **Robot** | `robot` |
| **Devil** | `devil` |

**Voices.** In Settings → Voice → **His voice**, pick the default preset (`voice`):

| Preset | Value | Kokoro voice | piper voice |
|---|---|---|---|
| **Girl** | `girl` (the default) | `af_heart` | `en_US-amy-medium` |
| **Cute** | `cute` | `af_bella` | `en_US-amy-medium` |
| **Guy** | `guy` | `am_michael` | `en_US-ryan-medium` |
| **Deep** | `deep` | `am_onyx` | `en_US-ryan-medium` |
| **British** | `british` | `bm_george` | `en_GB-alan-medium` |
| **Storyteller** | `story` | `bm_fable` | `en_GB-alan-medium` |
| **Robot** | `robot` | none: espeak | none |

Kokoro is used when it is installed, otherwise piper. Norwegian and Polish have piper voices only.

Under the character grid in Settings → Look, **Voice for the …** sets a preset for that character alone
(`voice_by_character`). Choose **My voice** to use the preset from the Voice tab.

**Language.** Settings → Voice → **Language** (`language`) supports `en` (English, default), `nb` (Norsk)
and `pl` (Polski). `voice_by_lang` remembers the preset you picked in each language.

**Skins and colours.** In Settings → Look:

- **Colours:** tap any part in the preview (body, either pupil, either eye white, or the skin) and pick a colour with
  the colour square, the hue slider, a hex code, the swatches or your recent colours. **Follow desktop theme** is on by
  default (`look.follow_theme`) and tracks your Omarchy theme until you pick a colour by hand. Turn off **Matching
  eyes** (`look.link`) to give it two different eyes. **🎲 all** rolls a whole new look; **Surprise me** (`look.random`) does it
  every time it appears.
- **Skins:** `none`, `halo`, `crown`, `sprout` or `bow` (plus any prop from an enabled [plugin](#plugins) as
  `plug:<id>`). The Robot character fits `none`, `halo`, `bow` and plugin props.
- **Typing:** `/skin halo`, `/body #c9a8f0`, `/eyes pink`, `/whites mint`, `/pupils circle`.

## ElevenLabs

Local voices (`kokoro` → `piper` → `espeak`) run on your machine by default. ElevenLabs is an optional cloud voice in
Settings → Voice → **ElevenLabs**.

> [!IMPORTANT]
> When ElevenLabs is on, the text he speaks leaves your machine and goes to ElevenLabs.

**Key file rules** (`app/eleven.py`):

- The file path comes from `eleven_key_file` in `~/.config/nixi-companion/config.json`, which defaults to
  `/run/agenix/api-elevenlabs`.
- Its real path (after resolving symlinks) must live under `/run/agenix`, `/run/agenix.d` or `/run/secrets`.
- It must be a regular file (`1` to `256` bytes), owned by `root` or by your user, and readable by you.
- Its contents (trimmed) must be `16` to `128` characters of `A-Z`, `a-z`, `0-9`, `_` or `-`.

Never put the key inline in a `.nix` file: anything in `/nix/store` is world-readable. With agenix or sops-nix:

```nix
{
  # agenix -> /run/agenix/api-elevenlabs (the default eleven_key_file)
  age.secrets.api-elevenlabs = {
    file = ../secrets/elevenlabs.age;
    owner = "<your-user>";
  };
}
```

If you use sops-nix (`/run/secrets/api-elevenlabs`), set `"eleven_key_file": "/run/secrets/api-elevenlabs"` in
`~/.config/nixi-companion/config.json`.

**Turning it on:**

1. Open Settings → Voice → **ElevenLabs**. The key line says “API key ready.” when the key file passes the rules above, and “No API key found.” when it does not.
2. Tick **I understand — send spoken replies to ElevenLabs**, then turn on **Use ElevenLabs** (`eleven_on`).
3. Pick a voice under **Voices** and press **Choose** (`eleven_voice`).
4. Set **Daily character cap** (`eleven_daily_chars`, default `20000`, from `1000` to `500000`) and **Fallback voice**
   (`tts_fallback`, default `"auto"`). When you hit the daily cap or ElevenLabs is unreachable, he falls back to the
   local voice automatically.

## The fleet board

He can show a board with your other machines on your tailnet (load, memory, disks, network rates, NixOS generation and
failed services) when you say "system status" or "nixi status", or through a stage plugin with `reads: ["peer-status"]`.

1. On each other machine, enable the status service from this flake (`nixosModules.status`):

   ```nix
   {
     services.tailscale.enable = true;          # required by the module
     services.nixi-status = {
       enable = true;
       address = "100.x.y.z";                   # this host's own tailnet address
       allowedCallers = [ "100.x.y.z" ];        # the desktops allowed to ask; a non-empty list of tailnet addresses
       tokenFile = "/run/agenix/nixi-status-token";
       port = 9188;                             # the default
     };
   }
   ```

2. On your desktop, list those machines in Home Manager under `services.nixi.companion.peers` and point `peerTokenFile`
   at the same secret:

   ```nix
   {
     services.nixi.companion = {
       peers = [
         { name = "<other-host>"; address = "100.x.y.z"; port = 9188; }
       ];
       peerTokenFile = "/run/agenix/nixi-status-token";
     };
   }
   ```

   Every `address` must be a Tailscale IPv4 address in `100.64.0.0/10`, not a host name. `services.nixi-status` also refuses `100.100.100.100` (the MagicDNS address), and the companion refuses it too.
   `peerTokenFile` must be a runtime path such as `/run/agenix/...` or `/run/secrets/...`, never a `/nix/store` path,
   and is required whenever `peers` is non-empty. Home Manager writes `~/.config/nixi-companion/peers.json`.

3. Open Settings → **Plugins** and turn on **Other machines** (`peers_on`). The switch only shows when `peers` is set.

## Plugins

Companion plugins live in Nix via `services.nixi.companion.plugins` or in `~/.local/share/nixi-companion/plugins/`. He
never downloads plugins from the network.

```nix
{
  services.nixi.companion.plugins = [
    inputs.nixoarchy-snowflake.legacyPackages.${pkgs.system}.examples.party-hat-plus
    (inputs.nixoarchy-snowflake.lib.${pkgs.system}.mkCompanionPlugin {
      src = ./my-plugin;
      pname = "my-plugin";
    })
  ];
}
```

A plugin folder has a `plugin.json` (`"api": 1`, `"id"`, `"name"`, `"version"`, and an optional `"description"`) and any of
four parts. `mkCompanionPlugin` checks the manifest when it builds, so a bad one fails the build.

- **`quips`:** the path of a JSON file with extra lines for the little jokes, keyed `break`, `welcome`, `ram`, `cpu`,
  `rain`, `snow`, `night`, `party`, `coding` and `done`. Each key holds a list of strings.
- **`prop`:** an SVG `file`, an `anchor` of `head`, `left`, `right` or `base`, and an optional `layer` of `front` or
  `back`. It appears in Settings → Look → Skin as `plug:<id>`.
- **`notifications`:** a list of `{ "app": …, "category": … }` or `{ "host": …, "category": … }`. The category is `mail`,
  `chat` or `feed`.
- **`stage`:** a program that fills the board under him. It has `phrases` (what you say to open it) and `argv` (the
  program and its words, run without a shell), and optionally `hint`, `network`, `cache_seconds`, `reads`
  (`system-status` and/or `peer-status`) and `config`. With `config`, the plugin's `defaults.json` becomes a settings
  file in `~/.config/nixi-companion/plugin-config/<id>.json`. A stage program runs in a `bwrap` sandbox, and a plugin
  that uses the network also needs `pasta`.

Every plugin starts off. Turn it on in Settings → **Plugins** (its own tab). A plugin that runs a program asks for your
permission there. One you declared in Nix counts as allowed once you switch it on. A folder plugin in
`~/.local/share/nixi-companion/plugins/` is checked by a hash of its files: if the files change, it turns off and says
“Changed — check it again” until you allow it again. A deploy does not update copies in that folder.

## Nix options

All Home Manager options under `services.nixi.companion` (defined in nixi's `nix/hm-module.nix`):

| Option | Default | What it does |
|---|---|---|
| `services.nixi.companion.enable` | `false` | Install the `nixi-companion` launcher and point it at nixi's bridge |
| `services.nixi.companion.package` | `null` | The companion package from the `nixoarchy-snowflake` flake (`inputs.nixoarchy-snowflake.packages.${pkgs.system}.default`). Required when `enable = true` |
| `services.nixi.companion.peers` | `[ ]` | Other machines running `nixi-status` for the fleet board (written to `~/.config/nixi-companion/peers.json`, only when non-empty) |
| `services.nixi.companion.peers.*.name` | *(required)* | Short label shown on the board |
| `services.nixi.companion.peers.*.address` | *(required)* | Tailnet IPv4 address in `100.64.0.0/10`, not a host name (the companion refuses any address outside the tailnet) |
| `services.nixi.companion.peers.*.port` | `9188` | TCP port of `nixi-status` on that host (`1`–`65535`) |
| `services.nixi.companion.peerTokenFile` | `null` | Runtime path to the shared token file (e.g. `"/run/agenix/nixi-status-token"`). Required when `peers` is non-empty; must not be in `/nix/store` |
| `services.nixi.companion.plugins` | `[ ]` | Plugins (a package, or a path to a plugin folder), linked into the companion package at build time, so what he can load is fixed when you build. Every plugin starts off until you turn it on in Settings → Plugins |
| `services.nixi.companion.commandDone.enable` | `false` | A “done” notification when a long shell command finishes in a terminal you are not looking at. Needs `programs.bash.enable` and/or `programs.zsh.enable` |
| `services.nixi.companion.commandDone.seconds` | `30` | The shortest command, in seconds, that earns a notification (any positive integer) |

## Settings reference

The companion stores its settings in `~/.config/nixi-companion/config.json`. The agent, model, reasoning effort and
trust level come from nixi's own config (`agent`, `model`, `reasoningEffort`). User-facing keys and their defaults from
`DEFAULTS` in `app/server.py`:

| key | default | what it does |
|---|---|---|
| `port` | `47777` | Local port for the companion HTTP server on `127.0.0.1` |
| `language` | `"en"` | Spoken and UI language (`"en"`, `"nb"`, `"pl"`) |
| `wake_word` | `true` | Listen for "Hey Nixi" |
| `listen_on_show` | `false` | Start listening as soon as the window pops up |
| `barge_in` | `true` | Stop speaking when you say "stop" or "Hey Nixi" |
| `follow_up` | `4` | Seconds after he finishes speaking that he still listens without "Hey Nixi" (`0` = off) |
| `ptt_hotkey` | `"Ctrl+Alt+Space"` | Hold this anywhere to talk, let go to send. Bind `nixi-companion ptt-down` and `ptt-up` to it |
| `mic_auto` | `true` | Keep your voice at a level he hears well: boost it when it comes in quiet, undo that when it clips |
| `mic_device` | `""` | The input to record from. Empty means the system default; `nixi-companion doctor` lists them |
| `mic_cmd` | `""` | An optional recorder of your own. It must write raw s16le, 16 kHz, mono to stdout |
| `whisper_model` | `"auto"` | Speech-to-text model: `"auto"` (`small.en` on an NVIDIA GPU, `base.en` on CPU), or pin `tiny.en`, `base.en`, `small.en` or `medium.en` |
| `whisper_device` | `"auto"` | `"cpu"` keeps speech-to-text on the CPU. Anything else uses an NVIDIA GPU when there is one |
| `whisper_beam` | `5` | Beam size for speech-to-text decoding |
| `stt_prewarm` | `true` | Load the speech model when he starts, not at your first word (with the wake word on, it loads at start anyway) |
| `stt_hint` | `"Hey Nixi, Claude, ..."` | Vocabulary hint passed to Whisper (add your project or host names) |
| `tts` | `"auto"` | Voice engine: `"auto"` (`kokoro` → `piper` → `espeak`), `"kokoro"`, `"piper"`, `"espeak"`, `"elevenlabs"`, `"off"` |
| `tts_fallback` | `"auto"` | Local fallback engine when ElevenLabs fails or hits the daily cap (`"auto"`, `"kokoro"`, `"piper"`, `"espeak"`, `"off"`) |
| `voice` | `"girl"` | Voice preset (`"girl"`, `"cute"`, `"guy"`, `"deep"`, `"british"`, `"story"`, `"robot"`) |
| `voice_by_lang` | `{}` | Remembered voice preset per language (`{"en": "girl", ...}`) |
| `voice_by_character` | `{}` | Voice preset override per character (`{"robot": "robot", ...}`) |
| `piper_voice` | `""` | Explicit piper `.onnx` voice path or name (overrides preset) |
| `espeak_voice` | `"en-us"` | Voice name passed to `espeak-ng` |
| `eleven_on` | `false` | Send spoken replies to ElevenLabs |
| `eleven_voice` | `""` | Selected ElevenLabs voice ID |
| `eleven_daily_chars` | `20000` | Daily character limit for ElevenLabs (`1000`–`500000`) |
| `speak_max_chars` | `600` | How many characters of a reply he speaks at most |
| `full_text` | `true` | Show everything you said in the caption (the end of it, wrapped) instead of one cut-off line |
| `sfx` | `true` | Play UI sound effects |
| `cpu_split` | `true` | Run his face (the window) and his voice and brain (the server) on separate CPU cores (4 or more cores only) |
| `agent_voice_mute` | `[]` | Terminal agents whose `agent-say` spoken summaries are muted (`"claude"`, `"codex"`, `"agy"`) |
| `presence` | `"orb"` | Window mode: `"orb"` (floating character) or `"bar"` (screen-edge notch) |
| `bar_edge` | `"top"` | Screen edge for the notch (`"top"`, `"bottom"`, `"left"`, `"right"`) |
| `hover` | `false` | Hover mode: become the mouse cursor until called |
| `click_through` | `false` | Let clicks on the transparent space around him pass through to the window behind |
| `follow_focus` | `false` | Move to whichever monitor has the focused window |
| `step_aside` | `true` | Slide out of the way while nixi's card is open |
| `idle_mode` | `"shrink"` | What he does when idle: `"off"` (stay), `"shrink"` (peek at the edge) or `"doze"` |
| `look` | `{}` | Look settings object (`character`, `body`, `pupL`, `pupR`, `whiteL`, `whiteR`, `skin`, `skinColor`, `link`, `random`, `follow_theme`; set in Settings → Look) |
| `eye_color` | `"#3e5993"` | Default pupil colour |
| `eye_white` | `"#ffffff"` | Default eye-white colour |
| `pupil_style` | `"slit"` | Pupil shape (`"slit"`, `"circle"`, `"dot"`) |
| `code_panel` | `true` | Show the mini terminal while the agent works |
| `code_face` | `"you"` | Which way the terminal faces: `"you"` (readable) or `"him"` (you see the back, mirrored) |
| `answer_stages` | `true` | A board or notebook beside him for commands and facts; off means captions only |
| `peers_on` | `false` | Let plugins show your other machines' status (the **Other machines** switch in the Plugins tab) |
| `notify_done` | `true` | A desktop notification when a long task finishes while he is hidden |
| `popup_done` | `false` | Pop back up when a long task finishes while he is hidden |
| `proactive` | `false` | The **Desktop companion** master switch |
| `notifications_takeover` | `false` | Show desktop notifications through him instead of the shell's popups |
| `notify_details` | `false` | Show the notification sender and body text (when off, only kind and app) |
| `notify_sound` | `true` | Play a short sound for notifications shown through him |
| `notify_speak` | `["meeting"]` | The kinds of notification he reads out loud (Settings → Look → **Say out loud**) |
| `notify_speak_subject` | `false` | Include the mail subject when speaking mail notifications |
| `ambient_system` | `true` | A mark on his tip when a user service fails, and a glint after each new NixOS generation (local) |
| `ambient_calendar` | `false` | Next calendar item (uses `gog`): ten minutes before, a calendar mark and the title |
| `ambient_weather` | `false` | Weather look (uses omarchy weather): frost on his tips below 0 °C, a slight thaw above 28 °C |
| `look_meeting` | `false` | A tie while Meeting Mode is on, or when a calendar item is a minute away |
| `look_music` | `false` | Headphones while a player is playing |
| `look_beat` | `false` | Pulse to the beat: he listens to what is playing (not your mic) while music plays |
| `look_fullscreen` | `false` | Shades while a window is fullscreen |
| `look_coding` | `false` | Glasses after a minute in a terminal or editor. Only the kind of window is checked, never its title |
| `look_night` | `false` | Wear a nightcap between 23:00 and 05:00 |
| `look_weather` | `false` | Weather above his head: a rain or snow cloud, sun, moon and clouds, and (with a place set) a scarf and beanie when it is cold |
| `look_party` | `false` | A party hat on New Year, Christmas, and birthdays in your calendar (needs the calendar on) |
| `react_load` | `false` | A sweat drop when the CPU works hard for a while; a word when memory runs low |
| `react_break` | `false` | After an hour unlocked he suggests a stretch. A lock of five minutes or more counts as a break |
| `react_welcome` | `false` | After half an hour away: how many notifications came in, and your next meeting if the calendar is on |
| `react_quips` | `false` | Now and then a short line about the weather, the hour or a long session. Never spoken |

## Commands

All subcommands handled by `bin/nixi-companion`:

| command | what it does |
|---|---|
| `nixi-companion` · `nixi-companion toggle` | show or hide the window |
| `nixi-companion show` · `nixi-companion hide` · `nixi-companion quit` | show, hide, or close the window |
| `nixi-companion listen` | pop up and start listening (bind this to a hotkey) |
| `nixi-companion ptt-down` · `nixi-companion ptt-up` | push-to-talk key press and release |
| `nixi-companion hover` · `nixi-companion hover-on` · `nixi-companion hover-off` | toggle, turn on, or turn off hover mode |
| `nixi-companion monitor` | move to another screen (`next`, `prev`, `focused`, or an output name like `DP-1`) |
| `nixi-companion attention` | receive a terminal agent alert (`--from claude\|codex\|agy --hook`) |
| `nixi-companion doctor` | check the window, list your mics, record 3 seconds with a level meter and test the voice |
| `nixi-companion diagnostics` | print a setup report to paste when asking for help |
| `nixi-companion restart` | restart the background server and show him |
| `nixi-companion stop` | stop the background server and close the window |
| `nixi-companion log` | follow the server log (`~/.local/share/nixi-companion/server.log`) |
| `nixi-companion look` · `nixi-companion see` · `nixi-companion live` | screenshot and live-view commands (disabled in nixi mode) |
| `nixi-companion setup` | first-run setup for non-Nix installs (prints a note and exits under Nix) |
| `nixi-companion server` | *(internal)* run the background Python HTTP server |
| `nixi-companion render` | *(internal / troubleshooting)* set WebKit render mode (`default`, `nodmabuf`, `nocomp`) |
| `nixi-companion stress` | *(internal / troubleshooting)* run the voice stutter benchmark |
| `nixi-companion theme-changed` | *(internal)* reload the Omarchy desktop theme colours |

In the typing box: `/new` `/mechanic` `/guide` `/hover` `/voice` `/skin <name>` `/body <colour>` `/eyes <colour|random>`
`/whites <colour|random>` `/pupils <slit|circle|dot>` `/mute` `/stop` `/hide` `/settings` `/status`

## Linux desktops

| desktop | what it is |
|---|---|
| **Wayland with layer-shell**: Hyprland, sway, KDE Plasma, river, niri, Wayfire, labwc, COSMIC… | a true overlay, like a bar or a notification: above every app on every workspace, never tiled, no taskbar entry |
| **GNOME (Wayland)** | no layer-shell, so it runs through XWayland as an always-on-top window on every workspace |
| **X11**: i3, bspwm, Openbox, XFCE, Cinnamon, MATE, KDE on X11… | an always-on-top borderless window on every workspace |

It starts in the bottom-right corner; drag it anywhere and it remembers the spot. To be see-through on a bare X11
window manager you need a compositor running, e.g. `picom`.

**Bind a hotkey** to `nixi-companion listen`:

| desktop | how |
|---|---|
| Hyprland | `bind = SUPER, A, exec, nixi-companion listen` in `~/.config/hypr/hyprland.conf` |
| sway / i3 | `bindsym $mod+a exec nixi-companion listen` in your config |
| GNOME / KDE / XFCE / Cinnamon | Settings → Keyboard → Shortcuts → add a custom shortcut that runs `nixi-companion listen` |

`NIXI_COMPANION_NO_LAYER=1 nixi-companion` skips the overlay and uses a normal always-on-top window.
`NIXI_COMPANION_BROWSER=1 nixi-companion` opens it in a plain browser app window instead (handy if WebKitGTK misbehaves).

## Starting at login

Start it from your session config, for example `exec-once = nixi-companion show` on Hyprland, or `exec nixi-companion show`
on sway / i3. The Nix module does not add a systemd unit or a bind for you.

## Troubleshooting

**Start with `nixi-companion doctor`.** It checks the window, lists your mics, records 3 seconds with a level meter, and
tests the voice. To share a report when asking for help, run `nixi-companion diagnostics`. Logs:
`nixi-companion log`.

- **It can't hear you:** run `nixi-companion doctor` and keep talking for the 3 seconds. **"NO VOICE … only background
  noise"** means the mic sends no voice: it is muted on the headset, or it is not the mic you are talking into. Pick
  the right one in Settings → Voice.
- **Can't click something under it:** turn on Settings → Look → "Click through around him". In the top bar only the
  area around the eyes takes clicks anyway.
- **The agent doesn't answer:** check that nixi works on its own (`nixi --tui`). A fatal bridge error closes the bridge;
  the next message starts a new one.
- **Speech stutters:** run `nixi-companion stress`. If it says the voice is too slow for the computer, pick a lighter one.
- **It doesn't stay on top / looks like a normal window:** run `nixi-companion doctor`; the first lines say whether it
  is an overlay here and why not. If it can't be an overlay it uses XWayland instead, so XWayland needs to be available.
- **It flashes and disappears:** WebKit is crashing on your GPU driver (common on NVIDIA + Wayland). The launcher
  retries with safer render modes. Pick one yourself with `nixi-companion render nocomp`, or reset with
  `nixi-companion render default`.
- **Black box around it:** nothing is doing transparency. On a bare X11 window manager start a compositor (`picom`).
- The voice is played by the server straight to PipeWire/Pulse (`paplay` or `aplay`). `"voice_out": "page"` in the
  config plays it in the window instead.

## How it works

```
 your mic ──► speech-to-text ──► nixi bridge ──► the agent ──► its voice ──────► your speakers
              (faster-whisper)   (trust rules)                  (kokoro/piper/
                                                                 espeak/ElevenLabs)
```

The server records the mic itself (PipeWire / Pulse / ALSA), speech-to-text is
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), the local voice is Kokoro, piper or espeak-ng (or
ElevenLabs when enabled), and every request goes to the agent through nixi's bridge on your machine. The bridge's events
(text, tool, permission, notice, done, error, fatal) drive the face. The server only listens on `127.0.0.1` behind a
per-launch token, so nothing else on your network can talk to it.

### The app icon

`app/static/icon.png` is used three times: in desktop notifications (`notify-send -i` in `app/server.py`), as the
launcher icon (`nix/package.nix` installs it as `hicolor/512x512/apps/nixi-companion.png`), and as the page's favicon.
It is a picture of the face drawn by `miniNixi()` in `index.html` with the default look. Nothing updates it
automatically, so if the face changes, render it again: load the page headless, hide everything else, and draw one
face into a 512×512 transparent SVG. The viewBox `-150 -150 300 300` fits the lambdas.

```bash
S=$(mktemp -d); R=$PWD/app/static
sed "s|<head>|<head><base href=\"file://$R/\">|" $R/index.html > $S/icon.html
cat >> $S/icon.html <<'EOF'
<script>setTimeout(()=>{ for(const e of document.body.children) e.style.visibility='hidden';
  document.documentElement.style.background=document.body.style.background='transparent';
  const s=document.createElementNS('http://www.w3.org/2000/svg','svg');
  s.setAttribute('viewBox','-150 -150 300 300'); s.setAttribute('width',512); s.setAttribute('height',512);
  s.style.cssText='position:fixed;left:0;top:0;visibility:visible;z-index:99999';
  document.body.appendChild(s); miniNixi(s,curLook(),false); },500);</script>
EOF
chromium --headless=new --disable-gpu --hide-scrollbars --allow-file-access-from-files \
  --default-background-color=00000000 --window-size=512,512 --virtual-time-budget=3000 \
  --screenshot=$R/icon.png "file://$S/icon.html"
```

---

<p align="center"><a href="../README.md">← Back to the README</a></p>
