# Getting started

You finished the [README](../README.md) steps and he answers. This page is the first day: what to choose, and why.
Every setting is in the companion's settings. Right-click him and choose settings. The tabs are **Look**, **Voice**,
**Brain**, **Plugins** and **More**. The full list is in the [Guide](GUIDE.md).

## Speakers or headphones

He listens all the time for “Hey Nixi”. Speakers on your desk can carry his own voice back into the mic, and he may
answer himself.

- **Headphones** fix it. This is the easy choice.
- **Speakers:** an echo-cancelled source, if you have one, helps. Pick it under **Microphone** in the **Voice** tab.
- **Without either:** keep **Interrupt him by voice** off, or use push-to-talk. Hold **Ctrl+Alt+Space**, talk, let go.

Check any change with `nixi-companion doctor`.

## Character and voice

In the **Look** tab, **Character** shows a grid. Tap one to change how he looks. Each character can have its own voice.
Under the grid, a menu picks that character's voice. **My voice** uses the voice you chose in the **Voice** tab.

The voice is a preset: `girl`, `cute`, `guy`, `deep`, `british`, `story` or `robot`. Set the default in the **Voice** tab
under **His voice**. The `tts` setting is `auto`: Kokoro if it is installed, then piper, then espeak. Local voices run
on your computer, and a piper voice downloads the first time you use it.

## ElevenLabs

ElevenLabs is a cloud voice. It is optional, and it is off by default.

> [!IMPORTANT]
> When it is on, the text he speaks goes to ElevenLabs. That can include anything in his answers.

**1. Keep the key in a secret file.** He only reads a key from a file that passes all of these:

- it is under `/run/agenix`, `/run/agenix.d` or `/run/secrets`;
- it is owned by root or by you, and you can read it;
- it holds 16 to 128 characters of `A-Z`, `a-z`, `0-9`, `_` or `-`.

The default path is `/run/agenix/api-elevenlabs`. The `eleven_key_file` setting changes it.

With agenix, name the secret and make yourself the owner:

```nix
{
  age.secrets.api-elevenlabs = {
    file = ../secrets/elevenlabs.age;
    owner = "<your-user>";
  };
}
```

With sops-nix, the file lands in `/run/secrets`:

```nix
{
  sops.secrets.api-elevenlabs = {
    sopsFile = ../secrets/elevenlabs.yaml;
    owner = "<your-user>";
  };
}
```

To keep root as the owner, use `mode = "0440"` and set `group` to a group you are in. For sops-nix, the file is
`/run/secrets/api-elevenlabs`, so set `eleven_key_file` to that. Do not put the key in your Nix config as text: it
would end up in the store, which everyone can read.

**2. Switch it on.** In the **Voice** tab, find **ElevenLabs**. It says if the key was found. Tick **I understand —
send spoken replies to ElevenLabs**, then **Use ElevenLabs**. Pick a voice from the list.

**3. Watch the cost.** **Daily usage** shows what you spent. **Daily character cap** stops him at the limit (20000
characters by default). Over the cap, or if ElevenLabs cannot be reached, **Fallback voice** speaks instead.

Turn it off in the same place. Text already sent may still count on your ElevenLabs account.

## Messages and notifications

He can show your notifications himself, in place of the shell's popups. A click on one opens the app that sent it.

Right-click him, choose settings and open the **Look** tab. The same switches are in the Nixi card's Settings → Desktop,
which is where nixi's README names them. Nothing happens until you turn on the first two:

1. **Desktop companion** is the master switch.
2. **Show notifications through him** makes him show them.

The rest are optional:

- **Show the notification text.** Without it he shows only the kind and the app, such as “New message in Teams”.
- **Notification sounds** gives each kind a short sound.
- **Say out loud** picks which kinds he speaks. Meetings only, by default.

Notification text stays on your machine. He never logs it, never writes it to disk and never gives it to the agent.
Critical alerts, and anything with a code in it (2FA, one-time passwords), keep the shell's own popup, and he never
reads a code aloud.

> [!NOTE]
> This needs nixarchy's notification patch (903). Without it, the popups stay as they are. Hide him, switch it off or
> let him crash, and the normal popups come back within seconds.

## Agents and approvals

In **Mechanic**, the agent may edit your files, and asks first. The question appears as a card next to him. Say “yes”,
“no” or “always”, or click.

Agents running in a terminal (Claude Code, Codex, agy) can also tell him when they need you or when they are done. He
shows a small mark for the agent and takes you to its window when you click. The hook lines to put in each agent's
settings are in the Guide, under [Agent alerts](GUIDE.md#agent-alerts). In the **Voice** tab, **Agents** can mute each
agent's spoken summary.

Switch the level any time by typing `/mechanic` or `/guide` to him.

## The fleet board

If you run more than one machine, he can show how the others are doing: load, memory, disks and failed services. List
them in your Home Manager config. Use their tailnet address (`100.x.y.z`), not a host name.

```nix
{
  services.nixi.companion = {
    peers = [
      { name = "<other-host>"; address = "100.x.y.z"; }
    ];
    peerTokenFile = "/run/agenix/nixi-status-token";
  };
}
```

`port` defaults to `9188`, the port of `nixi-status` on the other machine. The token file holds the token those
machines expect. Give it a runtime path like the one above, never a store path: a store path is readable by everyone.
`peerTokenFile` is required once `peers` is not empty.

Then, in the **Plugins** tab, switch on **Other machines**. It only shows when peers are set. The “Nix status” plugin
shows the board: say “system status”, or “nixi status”.

## Plugins

Plugins are folders with a `plugin.json`: quip packs, notification maps, SVG props, and programs that fill a stage.
You choose them in Nix, so what he can load is fixed when you build.

```nix
{
  services.nixi.companion.plugins = [
    inputs.nixi-companion.legacyPackages.${pkgs.system}.examples.party-hat-plus
  ];
}
```

Every plugin starts off. Turn it on in the **Plugins** tab. A plugin that runs a program asks for your permission
there, and runs in a sandbox. He never downloads a plugin.

> [!WARNING]
> A plugin you copy by hand into `~/.local/share/nixi-companion/plugins/` is found too, but a deploy does not update
> it. When a plugin changes, copy the new folder over the old one yourself.

## A long command finished

He can tell you when a long command ends in a terminal you are not looking at.

```nix
{
  services.nixi.companion.commandDone = {
    enable = true;
    seconds = 30;
  };
}
```

`seconds` is the shortest command that counts. 30 is the default. It needs `programs.bash.enable` or
`programs.zsh.enable`. You get “Done in 42s”, or “Failed after 42s (exit 1)”, with only the command's first word and
never the command line. Inside herdr, tmux or zellij he cannot tell which pane you watch, so he tells you even when
you are looking at it.

## Your day

A way to start:

1. Log in. He is there, from the start-at-login line you added in the README.
2. Ask by voice or typing: “Hey Nixi, what changed in this repo?” In **Guide** he explains and changes nothing.
3. Switch to **Mechanic** when you want edits. Answer his cards.
4. Start a long job in the terminal. When it ends, he tells you.
5. Hide him with **Esc** when you need quiet. Hidden means the mic is off.

## Handy to know

| You do | What happens |
|---|---|
| Say **“stop”** while he talks | He stops. “Hey Nixi, …” mid-sentence cuts in with something new. |
| Hold **Space** | Push-to-talk. |
| Press **Esc** | Closes menus, cancels listening, stops the agent, then hides him. |
| **Ctrl+N**, or say “new chat” | A fresh conversation. |
| Just **type** | A box opens under him. **Enter** sends. |
| **Right-click** him | The menu: talk, folder, hover, settings, hide. |
| **Drag** him into a screen edge | He becomes a notch with just his eyes. Drag him out to get the snowflake back. |
| **Hover mode** (menu, or `nixi-companion hover`) | He becomes your mouse cursor. Call him to bring him back. |

After he answers, keep talking for a few seconds and he still hears you, with no “Hey Nixi”.

## What is off in nixi mode

Because the agent runs under nixi's rules, the companion hides these and its server refuses them:

- trust and root modes, and the sudo password card;
- the model picker, thinking effort, cost meter and compact. Set `agent`, `model` and `reasoningEffort` in nixi's
  config;
- the update checks and the “start at login” toggle. Your Nix config owns those, so you start him at login yourself
  (README, step 4). Plugins you choose in Nix, with `services.nixi.companion.plugins`;
- history, memory and projects;
- screenshots, live view and `see`.

Everything else works the same: voice in and out, the face and its moods, skins and colours, hover mode and the edge
notch.

## Next

The [Guide](GUIDE.md) lists every setting and command. If something breaks, start with `nixi-companion doctor`.
