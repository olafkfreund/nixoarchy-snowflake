# My plugin

A starter stage plugin for Nixi. Say `"my plugin card"` and he shows a two-point
facts card.

## Check

```bash
nix build --no-link
```

## Install in Home Manager

```nix
{
  services.nixi.companion.plugins = [
    inputs.my-plugin.packages.${pkgs.stdenv.hostPlatform.system}.default
  ];
}
```
