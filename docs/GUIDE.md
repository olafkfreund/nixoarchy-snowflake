<p align="center"><a href="../README.md"><img src="../app/static/icon.png" width="96" alt="Nixi"></a></p>

<h1 align="center">The Nixi guide</h1>

<p align="center">What the snowflake companion can do, and how to set it up.<br>
New here? Start with the <a href="../README.md">README</a>.</p>

---

> **Nixi mode.** This build talks to the agent only through nixi's bridge. Features that would bypass nixi's rules are
> off: trust/root modes, model picker, plug-ins, updates, history, memory, projects, screenshots and live view. They are
> left out of this guide.

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

## Commands

| command | what it does |
|---|---|
| `nixi-companion` | show / hide it |
| `nixi-companion listen` | pop up and start listening (bind this to a hotkey) |
| `nixi-companion hover` | hover mode on / off |
| `nixi-companion doctor` | mic check: lists inputs, records 3 seconds, shows a level meter |
| `nixi-companion stress` | voice stutter test |
| `nixi-companion render default\|nodmabuf\|nocomp` | how it is drawn |
| `nixi-companion restart` · `nixi-companion stop` | restart · quit |
| `nixi-companion log` | the server log |

In the typing box: `/new` `/mechanic` `/guide` `/hover` `/voice` `/eyes <colour|random>` `/whites <colour|random>`
`/pupils <slit|circle|dot>` `/mute` `/stop`

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

## Skins and colours

Settings → Look:

- **Colours:** tap any part in the preview (body, either pupil, either eye white, or the skin) and pick a colour with
  the colour square, the hue slider, a hex code, the swatches or your recent colours. Turn off **Matching eyes** to give
  it two different eyes. **🎲 all** rolls a whole new look; **Surprise me** does it every time it appears. The default
  is icy blue.
- **Skins:** cat ears, bunny ears, bear ears, antenna, devil horns, halo, crown, sprout, party hat, headphones or a bow.
  On the snowflake, ear skins overlap the arms.
- **Typing:** `/skin cat`, `/body #c9a8f0`, `/eyes pink`, `/whites mint`.

## Config

The companion's own settings are in Settings, stored in `~/.config/nixi-companion/config.json`. The agent, model and
reasoning effort come from nixi's config (`agent`, `model`, `reasoningEffort`), and the trust level too.

| key | default | |
|---|---|---|
| `wake_word` | `true` | "Hey Nixi" |
| `listen_on_show` | `false` | start listening as soon as it pops up |
| `barge_in` | `true` | say "stop" while it talks |
| `follow_up` | `4` | seconds after it stops talking that it still hears you without "Hey Nixi" (`0` = off) |
| `sfx` | `true` | sound effects |
| `look` | | body / pupils / whites / skin (set in Settings → Look) |
| `hover` | `false` | float next to the cursor |
| `tts` | `auto` | voice engine: `auto` (piper, then espeak), `piper`, `espeak`, `off` |
| `whisper_model` | `auto` | `base.en` on CPU; or `tiny.en` / `small.en` |
| `stt_hint` | coding words | words it should expect (add your project names) |
| `mic_device` | `""` | input to record from (Settings → Voice lists them) |

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

Start it from your session config, for example `exec-once = nixi-companion` on Hyprland, or `exec nixi-companion` on
sway / i3. The Nix module does not add a systemd unit or a bind for you.

## Troubleshooting

**Start with `nixi-companion doctor`.** It lists your mics and records 3 seconds with a level meter. Logs:
`nixi-companion log`.

- **It can't hear you:** run `nixi-companion doctor` and keep talking for the 3 seconds. **"NO VOICE … only background
  noise"** means the mic sends no voice: it is muted on the headset, or it is not the mic you are talking into. Pick
  the right one in Settings → Voice.
- **Can't click something under it:** turn on Settings → Look → "Click through around it". In the top bar only the
  area around the eyes takes clicks anyway.
- **The agent doesn't answer:** check that nixi works on its own. A fatal bridge error closes the bridge; the next
  message starts a new one.
- **Speech stutters:** run `nixi-companion stress`. If it says the voice is too slow for the computer, pick a lighter one.
- **It doesn't stay on top / looks like a normal window:** run `nixi-companion doctor`; the first lines say whether it
  is an overlay here and why not. If it can't be an overlay it uses XWayland instead, so XWayland needs to be available.
- **It flashes and disappears:** WebKit is crashing on your GPU driver (common on NVIDIA + Wayland). The launcher
  retries with safer render modes. Pick one yourself with `nixi-companion render nocomp`, or reset with
  `nixi-companion render default`.
- **Black box around it:** nothing is doing transparency. On a bare X11 window manager start a compositor (`picom`).
- The voice is played by the server straight to PipeWire/Pulse, with almost a second of sound buffered.
  `"voice_out": "page"` in the config plays it in the window instead.

## How it works

```
 your mic ──► speech-to-text ──► nixi bridge ──► the agent ──► its voice ──► your speakers
              (faster-whisper)   (trust rules)                  (piper)
```

The server records the mic itself (PipeWire / Pulse / ALSA), speech-to-text is
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), the voice is piper (or espeak-ng as a fallback), and every
request goes to the agent through nixi's bridge on your machine. The bridge's events (text, tool, permission, notice,
done, error, fatal) drive the face. The server only listens on `127.0.0.1` behind a per-launch token, so nothing else on
your network can talk to it.

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
