---
status: approved
issue: 99
author: olafkfreund
---

# Intent: keep Nixi's settings and plugins the same on every machine

## Problem

On 2026-11-17, razer's Nixi had drifted a long way from p620's: a different
voice, the voice off, the bridge in "ask" instead of YOLO, no mail, news,
phone or reactions, a different look, a missing plugin and no backup voices.
It was made identical by hand, by copying five things:

| What | Where | Written by |
|---|---|---|
| Companion settings | `~/.config/nixi-companion/config.json` | Nixi: every default on first start (`load_config`, `app/server.py:296-302`), then the settings panel (`save_config`, `:5892`) |
| Bridge settings | `~/.config/omarchy/nixi.json` | the bridge: read, merged and replaced (`bridge.js:98`, `mergeSettings` `:207`), and watched for outside changes (`:165`) |
| Folder plugins | `~/.local/share/nixi-companion/plugins/<id>` | copied by hand |
| Plugin consent | `~/.local/share/nixi-companion/plugins-state.json` | Nixi, when you allow a plugin |
| Backup voices | `~/.local/share/nixi-companion/voices` | downloaded by Nixi from a moving `main` URL (`fetch_voice`, `:5094`) |

Nothing keeps them identical:

- **A setting changed on one machine stays there.**
- **Deploys don't touch Nixi's settings.** nixos_config sets none of these
  files.
- **Plugins only half use what exists.** The package can already ship
  plugins: `package.nix` takes a `plugins` list of store paths, and
  `mkCompanionPlugin` builds them. Nix-shipped plugins count as allowed once
  enabled (`plugins_act`, `:2595`). nixos_config uses none of it, so the
  folder plugins are hand copies that go stale after a bump.
- **Every key looks like a choice.** Because the first start writes every
  default into `config.json`, Nixi can't tell your choices from defaults it
  wrote itself.

## Proposed outcome

- **Shared defaults with visible exceptions.** p620, razer, and any later
  machine running Nixi get the same shared settings, bridge trust and mode,
  shared plugins and backup voices from one declaration, on every deploy. A
  new machine is identical on its first deploy.
- **A change you make on one machine is kept there as a local override**,
  and it's visible. The settings panel marks it ("differs from your NixOS
  config") and offers "use the shared value", which removes the override and
  applies the shared value at once. `nixi-companion doctor` lists every
  override, including one that happens to equal the shared value, since it
  would still hide a later shared change.
- **Only an explicit allowlist of settings is shared.** The rest stays local:
  - devices and hardware tuning (`mic_device`, `whisper_device`, CPU
    choices);
  - recorder and other commands;
  - local paths, executables and projects;
  - window and session state;
  - remembered consent (`peers_asked`);
  - `peers.json`.

  Hardware tuning can be set per host in nixos_config instead.
- **Existing machines move over once, on purpose.** The current
  `config.json` is backed up. A migration then keeps, as local overrides,
  only the keys that differ from the shared values, and only after you
  confirm which to keep. Nixi stops writing defaults it didn't need into
  `config.json`.

## Affected users and systems

- nixoarchy-snowflake: how settings load, save and reset; the settings
  panel; `doctor`; a Home Manager option for shared settings and plugins.
- nixi-nixarchy: the bridge reads trust, permission mode, agent and model
  from the same shared-defaults-and-overrides scheme.
- nixos_config: the shared declaration, used by p620 and razer.

## Constraints

- **No network way to change another machine's settings.** Trust and
  permission mode are security settings, so another machine must never be
  able to switch a bridge to YOLO. The sync comes from the deploy, not from a
  peer push.
- **One contract for every reader and writer.** The companion, the bridge and
  the deploy agree on where shared values and overrides live, how a reset
  works, and when a change takes effect. If a change needs a new
  conversation, say so.
- **A deploy never writes Nixi's own files.** Shared values arrive as a
  read-only file of their own, never by editing `config.json`, `nixi.json` or
  `plugins-state.json`. So a deploy can't lose a change that Nixi or the
  bridge is writing at the same time, and Nixi's own saves never replace the
  deployed file.
- **Consent stays yours.**
  - Installed, enabled and consented stay three separate things.
  - A deploy never overwrites `plugins-state.json`, and never re-enables a
    plugin you turned off.
  - A changed folder plugin still asks again.
- **Private stays private.** Anything in the Nix store is readable by every
  user on the machine. Plugins marked private, like your "You" character
  (Nixi says: "keep this folder out of Nix and out of any repo",
  `app/server.py:2518`), are never shared through Nix. They need another
  route, or stay copied by hand.
- **Secrets stay in agenix.** No shared setting may hold one. Today none
  does: the ElevenLabs key is read from `/run/agenix/api-elevenlabs`, and
  mail uses gog's own login.
- **Voices are pinned.** Backup voices are shared by name with pinned
  content, so every machine has the same bytes. The voices folder stays
  writable, so Nixi can still download one.
- **Opt-in.** Without a shared declaration, Nixi works exactly as today.

## Open questions

Decided at approval (2026-11-17): the recommendations below (1a, 2, 3, 4).


1. **Where does the shared truth live?**
   - **a. Shared defaults declared in nixos_config (recommended).** The
     order is built-in defaults, then the shared declaration, then explicit
     local overrides. This needs the migration and the bridge contract
     above.
   - **b. A `nixi-companion sync <host>` command** that copies the shared
     part over ssh when you run it. It's simpler, but only in sync when you
     remember to run it.
   - **c. A live push between peers.** Rejected by the first constraint.
2. **A changed shared setting in the panel:** kept as a local override, marked
   in the panel, listed by `doctor`, and removed by "use the shared value".
   To share it, you change nixos_config. Recommendation: as written.
3. **Nested settings such as `look`:** one key, overridden as a whole, or
   field by field? Recommendation: as a whole, so the panel can explain it in
   one line.
4. **The private "You" character:** keep copying it by hand, or ship it some
   other way? Recommendation: keep it by hand. A sentence in `doctor` notes
   when it's missing on a machine.
