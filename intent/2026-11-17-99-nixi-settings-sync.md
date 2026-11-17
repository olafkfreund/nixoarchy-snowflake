---
status: draft
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
| Companion settings | `~/.config/nixi-companion/config.json` | Nixi's settings panel (`save_config`, `app/server.py:5892`) |
| Bridge settings | `~/.config/omarchy/nixi.json` | the bridge (trust, permission mode, agent, model) |
| Folder plugins | `~/.local/share/nixi-companion/plugins/<id>` | copied by hand |
| Plugin consent | `~/.local/share/nixi-companion/plugins-state.json` | Nixi, when you allow a plugin |
| Backup voices | `~/.local/share/nixi-companion/voices` | downloaded by Nixi |

Nothing keeps them identical:

- A setting you change on one machine stays on that machine.
- None of these files come from nixos_config, so a deploy doesn't line them
  up. The companion's Nix side has no settings options (`nix/` holds only the
  package and the status server).
- Folder plugins already go stale silently after a bump, because the package
  doesn't ship them.

## Proposed outcome

- p620 and razer (and any later machine running Nixi) have the same Nixi:
  - the same settings, except the host-only ones;
  - the same bridge trust and mode;
  - the same folder plugins, at the same version, allowed;
  - the same backup voices.
- **Host-only settings stay per machine**: `mic_device`, `peers.json`, and
  anything else tied to that machine's hardware, which the spec lists.
- A new machine gets the same Nixi on its first deploy, with no copying.
- When they differ, you can see it: `nixi-companion doctor` says which shared
  settings differ from the shared source.

## Affected users and systems

- nixoarchy-snowflake: how the companion loads settings, and possibly a Home
  Manager module.
- nixi-nixarchy: the bridge's `nixi.json` (trust and permission mode).
- nixos_config: where the shared values live, if they are declared there.
- p620 and razer.

## Constraints

- **No new remote way to change a machine's settings.** Trust and permission
  mode are security settings. Another machine must never be able to switch a
  bridge to YOLO over the network. So the sync is not a push between peers.
- **Secrets stay in agenix.** Nothing in the shared settings is a secret
  today: the ElevenLabs key is read from `/run/agenix/api-elevenlabs`, and
  mail uses gog's own login. It must stay that way.
- **A plugin's consent is still yours.** Shipping a folder plugin must not
  silently allow a changed plugin. Today a changed plugin's hash asks again.
  The spec has to keep that, or say plainly why a Nix-pinned plugin counts as
  allowed.
- **The settings panel keeps working.** Changing a shared setting in Nixi
  must do something you can predict, and never fail silently or be quietly
  reverted on the next start without telling you.
- Nothing changes for someone who doesn't use this: Nixi without shared
  settings works as today.

## Open questions

1. **Where does the shared truth live?**
   - **a. In nixos_config (recommended).** Shared settings and plugins are
     declared there, through a Home Manager option, and every deploy applies
     them. Nixi reads them as a layer under its own `config.json`. That makes
     a new machine identical on first deploy, and it's the only route that
     also fixes stale plugins. The cost is the settings panel (question 2).
   - **b. A `nixi-companion sync <host>` command** that copies the shared part
     from one machine to another over ssh when you run it. It's simple, but
     only stays in sync if you remember to run it.
   - **c. A live push between peers.** Rejected by the constraint above: it
     would be a network path to another machine's trust and mode.
2. **With (a), what happens when you change a shared setting in the panel?**
   Recommendation: the change works as today, on that machine only, and is
   kept there as a local override.
   - The panel marks the setting "differs from your NixOS config", with a
     "use the shared value" button that drops the override.
   - `doctor` lists every override.
   - A deploy never overwrites your override; the shared value applies
     again only once you drop it.
   - To share a change, you put it in nixos_config.
3. **Which settings are host-only?** Recommendation: `mic_device`,
   `whisper_device`, `peers.json`, `cwd`, window position and size state, and
   anything with a device or path in it. Everything else is shared.
