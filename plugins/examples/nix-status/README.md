# Nix status
A Nixi stage plugin: say "nixi status" or "system status" and a dark board shows this computer's CPU, memory, `/` and the Nix store, network rates, the running NixOS generation, uptime and failed services (user and system). It refreshes while it is open, and he says a short line ("All fine.").
It runs in a sandbox with no network; it may read the system status (`reads: ["system-status"]`) and nothing else.

Needs a Nixi with `gauges` support (the board). On an older Nixi, the store meter still works but the board does not draw.

Updating: a copy in your plugins folder shows "Changed — check it again" once after you update it, until you allow it again; one installed with Nix shows "Updated".
