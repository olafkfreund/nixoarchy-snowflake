<p align="center"><img src="app/static/icon.png" width="180" alt="Nixi"></p>

<h1 align="center">Nixi</h1>

<p align="center"><b>A snowflake desktop companion for nixarchy.</b><br>
Say “Hey Nixi” and the agent does the work, under nixi's rules.</p>

<p align="center">
  <a href="#install"><b>Install</b></a> &nbsp;·&nbsp;
  <a href="#your-first-two-minutes"><b>First steps</b></a> &nbsp;·&nbsp;
  <a href="#what-is-off-in-nixi-mode"><b>What's off</b></a> &nbsp;·&nbsp;
  <a href="docs/GUIDE.md"><b>Full guide</b></a> &nbsp;·&nbsp;
  <a href="#need-help"><b>Help</b></a>
</p>

Nixi is a small snowflake with a face that floats on your desktop. You talk or type; it hands your words to the
[nixi](https://github.com/olafkfreund/nixi-nixarchy) bridge, which runs the agent. So everything the agent may do is
decided by nixi's trust levels, not by the companion:

- **Guide** (default): the agent explains and suggests, and does not change your files.
- **Mechanic**: the agent may edit, and asks you first. Approval cards appear next to the snowflake; say "yes", "no" or
  "always", or click.

Type `/mechanic` or `/guide` to switch. The current level is shown in Settings → Brain (it is set by nixi, not by the
companion).

## Install

You need [nixi](https://github.com/olafkfreund/nixi-nixarchy) set up with an agent. The companion is a Nix package and
talks to the agent only through nixi's bridge, so there is nothing else to sign in to.

**With the nixi Home Manager module** (recommended; this wires the bridge in for you):

```nix
inputs.nixi-companion.url = "github:olafkfreund/nixoarchy-snowflake";

# in your Home Manager config
services.nixi.companion = {
  enable = true;
  package = inputs.nixi-companion.packages.${pkgs.system}.default;
};
```

**Just try it** (without the bridge, so the agent part is not connected):

```bash
nix run github:olafkfreund/nixoarchy-snowflake
# or
nix profile install github:olafkfreund/nixoarchy-snowflake
```

Models for speech (faster-whisper, piper) download into `~/.cache/nixi-companion` the first time you use them.

## Your first two minutes

| | Do this | What happens |
|:-:|---|---|
| **1** | Run `nixi-companion` | The snowflake appears in the bottom-right corner. Drag it anywhere; it remembers the spot. |
| **2** | Say **"Hey Nixi"** | The ring lights up and moves with your voice. (Or just **click** it.) |
| **3** | Ask for something | It goes to the agent through the bridge. Watch the little terminal for each step. |
| **4** | **Right-click** it | Its menu: talk, folder, hover mode, settings, hide. |
| **5** | **Push it into a screen edge** | It merges into the edge as a notch with just its eyes. Drag it out to get the snowflake back. |

Bind a hotkey on your desktop, for example on Hyprland: `bind = SUPER, A, exec, nixi-companion listen`.

> [!TIP]
> Say **"stop"** to interrupt, hold **Space** for push-to-talk, or just start **typing**. **Esc** backs out of anything.
> **Ctrl+N** (or saying "new chat") starts a fresh conversation.

## What is off in nixi mode

Because the agent runs under nixi's rules, these are hidden and refused by the companion's server:

- trust and root modes, and the sudo password card
- the model picker, thinking effort, cost meter and compact (set `agent`, `model` and `reasoningEffort` in nixi's config)
- plug-ins, update checks and the "start at login" toggle (your Nix config owns those)
- history, memory and projects
- screenshots, live view and `see`

Everything else is unchanged: voice in and out, the face and its moods, skins and colours, hover mode and the edge notch.

## Need help?

Run **`nixi-companion doctor`** first. It checks your mic and voice in a few seconds.

| Problem | Fix |
|---|---|
| It can't hear me | Check the level meter in `nixi-companion doctor`, then pick the right mic in Settings → Voice. |
| The agent doesn't answer | Check that nixi works on its own, and that `services.nixi.companion.package` is set. |
| Something else | See [Troubleshooting](docs/GUIDE.md#troubleshooting). |

<br>

Nixi is a fork of [Void](https://github.com/PLAYER99-void/void) by PLAYER99 (MIT).

<p align="center">
  <sub>Speech-to-text by <a href="https://github.com/SYSTRAN/faster-whisper">faster-whisper</a> · voice by piper and espeak-ng ·
  everything runs on your computer · <a href="LICENSE">MIT license</a></sub>
</p>
