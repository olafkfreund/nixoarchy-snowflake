# Nix status
A Nixi stage plugin: say "nixi status" and the notebook shows the running NixOS generation, failed user services and the store size.
It runs in a sandbox with no network; it may read the system status (`reads: ["system-status"]`) and nothing else.
