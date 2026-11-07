<p align="center"><img src="app/static/icon.png" width="180" alt="Nixi"></p>

<h1 align="center">Nixi</h1>

<p align="center"><b>A snowflake desktop companion for nixarchy.</b><br>
Say “Hey Nixi” and the agent does the work, under nixi's rules.</p>

<p align="center">
  <a href="#set-up-step-by-step"><b>Set up</b></a> &nbsp;·&nbsp;
  <a href="#what-stays-on-your-machine-and-what-doesnt"><b>Privacy</b></a> &nbsp;·&nbsp;
  <a href="docs/GETTING-STARTED.md"><b>Getting started</b></a> &nbsp;·&nbsp;
  <a href="docs/GUIDE.md"><b>Full guide</b></a> &nbsp;·&nbsp;
  <a href="#need-help"><b>Help</b></a>
</p>

## What it is

Nixi is a small snowflake with a face that floats on your desktop. You talk or type, and he hands your words to the [nixi](https://github.com/olafkfreund/nixi-nixarchy) bridge, which runs the agent.
Nixi's trust levels decide what the agent may do, not the companion. In **Guide** (the default) the agent explains and changes nothing. In **Mechanic** it may edit, and asks you first.

## Before you start

Each line has a command that tells you if it is ready.

- [ ] **NixOS with Home Manager and flakes.** `nix config show experimental-features` lists `flakes`.
- [ ] **nixi, with an agent signed in.** `command -v nixi` prints a path. Ask the nixi card something: it must answer.
- [ ] **A microphone.** `wpctl status` lists your microphone under Audio → Sources.
- [ ] **Speakers or headphones.** `wpctl status` lists your speakers or headphones under Audio → Sinks.

Just want to look at him? `nix run github:olafkfreund/nixoarchy-snowflake` starts him without the bridge, so the agent is not connected.

## Set up, step by step

### 0. Get nixi working first

The companion has no agent of its own. Without nixi he cannot answer. On nixarchy, nixi is already on. Anywhere else, install it from [its README](https://github.com/olafkfreund/nixi-nixarchy#install).

**Do**

```bash
nixi --tui
```

**You should see** a terminal chat. Ask it a question and it answers.

**If not**, the agent is not signed in. Sign in to the agent first (Claude Code, for example), then try again. Nothing below works until this does.

### 1. Add the flake input

**Do** — in your flake:

```nix
{
  inputs.nixoarchy-snowflake.url = "github:olafkfreund/nixoarchy-snowflake";
}
```

**You should see** nothing yet. This only names where the companion comes from.

**If not**, and Nix says it cannot fetch the input, check your network and that the URL is spelled as above.

### 2. Turn it on

**Do** — in your Home Manager config:

```nix
{
  services.nixi.companion = {
    enable = true;
    package = inputs.nixoarchy-snowflake.packages.${pkgs.system}.default;
  };
}
```

**You should see** no error when you evaluate the config. `package` is needed: without it the module has no companion to install.

**If not**, and Nix says `services.nixi.companion` does not exist, nixi's Home Manager module is not imported. Add `imports = [ inputs.nixi.homeModules.default ];` (see nixi's README).

### 3. Switch

**Do** — rebuild the way you always do. If Home Manager is part of your NixOS config:

```bash
sudo nixos-rebuild switch --flake .#<your-host>
```

If you run Home Manager on its own:

```bash
home-manager switch --flake .#<your-user>
```

Then check:

```bash
command -v nixi-companion
```

**You should see** a path from `command -v`.

**If not**, the switch failed before it finished. Read its last error. The most common one is `package` unset in step 2.

### 4. Start him, and keep him starting

The module installs the companion. It does not start him at login and does not bind a key. You do both.

**Do** — the first start:

```bash
nixi-companion
```

**You should see** the snowflake in the bottom-right corner. Drag it anywhere: it remembers the spot. Running `nixi-companion` again shows or hides it.

Now add start at login and a key. On nixarchy, in a file your `bindings.lua` loads:

```lua
o.exec_on_start("nixi-companion show")
o.bind("SUPER + ALT + S", "Nixi companion: show or hide", "nixi-companion")
o.bind("SUPER + ALT + SHIFT + S", "Nixi companion: listen", "nixi-companion listen")
```

On plain Hyprland, in `hyprland.conf`:

```ini
exec-once = nixi-companion show
bind = SUPER ALT, S, exec, nixi-companion
bind = SUPER ALT SHIFT, S, exec, nixi-companion listen
```

Optional: push-to-talk, which needs a press bind and a release bind. On plain Hyprland:

```ini
bind = CTRL ALT, SPACE, exec, nixi-companion ptt-down
bindr = CTRL ALT, SPACE, exec, nixi-companion ptt-up
```

Other desktops are in the Guide, under [Talking to it](docs/GUIDE.md#talking-to-it).

**You should see** him again after you log out and in, and the key shows or hides him.

**If not**, and nothing appears, run `nixi-companion doctor`: its "window" part says if the window can start. Then read the log with `nixi-companion log`.

### 5. Type to him

**Do** — click him, or just start typing, then press Enter:

```text
What can you do?
```

**You should see** your words, then the agent's answer. The little terminal shows each step.

**If not**, and he never answers, the bridge cannot reach the agent, most often because the agent is not signed in. Go back to step 0. `nixi-companion log` shows the bridge's last lines, such as “the nixi bridge did not start”.

### 6. Let him hear you

**Do** — right-click him, choose settings, open the **Voice** tab and pick your mic under **Microphone**. Then:

```bash
nixi-companion doctor
```

**You should see** a bar for the loudest sound in 3 seconds, then `-> looks good`, then `heard:` with the words it understood.

**If not**, and it says `NO VOICE` or `very quiet`, it is the wrong mic, or a muted one. Pick another under **Microphone** and run it again.

> [!NOTE]
> Speakers on your desk can make him hear his own voice. An echo-cancelled source, if you have one, helps. Headphones always do. [Getting started](docs/GETTING-STARTED.md) has the details.

### 7. Say “Hey Nixi”

**Do** — in the **Voice** tab, check that **“Hey Nixi” wake word** is on (the setting is `wake_word`, on by default). Then say:

```text
Hey Nixi
```

**You should see** the ring light up and move with your voice. Then ask. Say “stop” to interrupt. The first time, the speech model downloads under `~/.cache`.

**If not**, he does not wake. Check step 6 first. Then click him, or use the listen key from step 4. Push-to-talk (**Ctrl+Alt+Space**) works once its two binds are in.

### 8. Give him a voice

**Do** — in the **Voice** tab, tap a voice under **His voice**. The `tts` setting is `auto` by default: Kokoro if installed, then piper, then espeak. Local voices need no account. ElevenLabs is optional, and is in the same tab.

**You should see** that voice speak when you tap it, and speak his replies while **Speak replies out loud** is on.

**If not**, and he is silent, check **Speak replies out loud** and that your speakers are the system output. A robotic voice means only espeak is available. A piper voice downloads the first time you use it.

### 9. Messages through him (optional)

**Do** — right-click him, choose settings, open the **Look** tab, and turn on **Desktop companion** and **Show notifications through him**.

**You should see** your notifications appear on him instead of in the shell's popups. A click opens them.

**If not**, and the shell's popups still show, your shell lacks nixarchy's notification patch (903). Without it, the popups stay as they are.

### 10. Choose how much he may do

**Do** — type this to him (or say it):

```text
/mechanic
```

`/guide` goes back. If you change the level in the nixi card instead, restart him so he reads it:

```bash
nixi-companion restart
```

**You should see** the new level in his settings, on the **Brain** tab ("set by nixi: type /mechanic or /guide"). Typing is instant. A change made in the card shows only after the restart.

**If not**, and the level is still the old one after a card change, run the restart again and check that nixi works on its own.

## What stays on your machine, and what doesn't

**Stays on your machine**

- Speech-to-text: the words you say are turned into text here.
- The local voices (Kokoro, piper, espeak).
- Notification text. He never logs it, writes it to disk, or gives it to the agent.

**Leaves your machine**

- What you ask goes to the agent's provider, through nixi.
- The text he speaks goes to ElevenLabs when you switch ElevenLabs on. It is off by default.

## Next

- [Getting started](docs/GETTING-STARTED.md): the first day, one choice at a time.
- [Guide](docs/GUIDE.md): every setting and command.
- Tips, and what is off in nixi mode: [Getting started](docs/GETTING-STARTED.md#handy-to-know).

## Working on it

The plugin sandbox tests skip without `pasta`, and the run still says `OK`. This command runs them all, and fails if it can't:

```bash
nix develop -c python3 -B tests/test_plugin_sandbox.py
```

A PR that touches `app/plugins.py`, `tests/test_plugin_sandbox.py` or the wrapper's PATH (`nix/package.nix`) needs a passing run, and the PR says so. If it touches the wrapper's PATH, it also needs `nix build .#checks.x86_64-linux.wrapper-has-sandbox-tools`.

## Need help?

Run **`nixi-companion doctor`** first. It checks your window, mic and voice in a few seconds.

| Problem | Fix |
|---|---|
| nixi will not answer (step 0) | Sign the agent in, and test with `nixi --tui`. |
| The flake input cannot be fetched (step 1) | Check the network and the URL. |
| `services.nixi.companion` does not exist (step 2) | Import nixi's Home Manager module. |
| `nixi-companion` is not found (step 3) | The switch failed. Read its last error, and check `package` is set. |
| No snowflake, or none after login (step 4) | Run `nixi-companion doctor`, then `nixi-companion log`. Add the start-at-login line. |
| The agent doesn't answer (step 5) | Check that nixi works on its own and that its agent is signed in. `nixi-companion log` shows the bridge's errors. |
| It can't hear me (step 6) | Check the level in `nixi-companion doctor`, then pick the right mic in Settings → Voice. |
| “Hey Nixi” does nothing (step 7) | Check the wake word switch, then click him or use the listen key. Push-to-talk needs its binds from step 4. |
| No sound, or a robot voice (step 8) | Switch on **Speak replies out loud**. A robot voice means only espeak is available. |
| Notifications still pop up in the shell (step 9) | Check the first two switches in settings → **Look**. If they are on, the shell needs nixarchy's notification patch (903). |
| The trust level looks old (step 10) | Run `nixi-companion restart`. |
| Something else | See [Troubleshooting](docs/GUIDE.md#troubleshooting). |

<br>

Nixi is a fork of [Void](https://github.com/PLAYER99-void/void) by PLAYER99 (MIT).

<p align="center">
  <sub>Speech-to-text by <a href="https://github.com/SYSTRAN/faster-whisper">faster-whisper</a> · voice by Kokoro, piper and espeak-ng ·
  <a href="LICENSE">MIT license</a></sub>
</p>
