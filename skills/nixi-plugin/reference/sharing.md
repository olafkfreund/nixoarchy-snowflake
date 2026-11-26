# Installing and sharing a plugin

## 1. Local installation

You can install a plugin either declaratively with Nix or as a mutable folder
plugin (`docs/GUIDE.md:462–475`, `:507–510`):

### Declarative (Home Manager)

Pass `mkCompanionPlugin` (from `nixoarchy-snowflake.lib.<system>`, exported for
`x86_64-linux` and `aarch64-linux`) to `services.nixi.companion.plugins`:

```nix
{
  services.nixi.companion.plugins = [
    (inputs.nixoarchy-snowflake.lib.${pkgs.stdenv.hostPlatform.system}.mkCompanionPlugin {
      pname = "my-plugin";
      src = ./my-plugin;
    })
  ];
}
```

`mkCompanionPlugin` runs `python3 plugins.py --check .` during `checkPhase`
(`nix/plugin.nix:19`), so a bad manifest or SVG fails the build before it ever
reaches Settings.

### Folder plugin

Copy the folder (with real files, never symlinks) to
`$XDG_DATA_HOME/nixi-companion/plugins/<id>` (default
`~/.local/share/nixi-companion/plugins/<id>`).

### Consent and updates

Every plugin starts off until you turn it on in Settings → **Plugins**:

- **Nix plugins:** linked into the companion package at build time. Once you
  switch a Nix stage plugin on in Settings → **Plugins**, it counts as allowed
  without a separate consent card (`app/server.py:2730–2731`,
  `docs/GUIDE.md:507–510`). If a previously recorded Nix stage hash changes
  after a rebuild, Nixi keeps it on and marks it `"Updated"`
  (`app/plugins.py:1012–1017`).
- **Folder plugins:** turning on a folder stage plugin opens a consent card
  showing its command, `reads` feeds and network access. On Allow, the card
  sends its hash back for comparison (`app/server.py:2696–2698`, `:2732–2739`).
  Nixi hashes every file before each run; if any
  file changes, the plugin is switched off immediately and shows
  `"Changed — check it again"` until you allow it again
  (`app/plugins.py:842–857`, `:994–1026`).

When both a Nix plugin and a folder plugin have the same `id`, the Nix plugin
wins and the folder copy is marked `"duplicate id"` (`app/plugins.py:360–364`).

## 2. Sharing a plugin in its own repository

To publish a plugin so other Nixi users can install it:

1. **Create a standalone git repository** containing the files from `template/`:
   - `plugin.json`
   - `run` (mode `0755`, if it is a stage plugin) or your SVG / quips JSON files
   - `README.md`
   - `LICENSE`
   - `flake.nix`

2. **Use the template's `flake.nix`:**

   ```nix
   {
     description = "My Nixi companion plugin";

     inputs.nixi.url = "github:olafkfreund/nixoarchy-snowflake";

     outputs =
       { self, nixi }:
       {
         packages = builtins.mapAttrs (
           _: l: {
             default = l.mkCompanionPlugin {
               pname = "my-plugin";
               src = self;
             };
           }
         ) nixi.lib;
       };
   }
   ```

   Because it maps over `nixi.lib`, it automatically exports
   `packages.x86_64-linux.default` and `packages.aarch64-linux.default`.

3. **Check the flake before pushing:**

   ```bash
   nix build --no-link
   ```

   In a git repository, run `git add` on all plugin files first: Nix only sees
   tracked files from a git source.

4. **Tag the repository on GitHub** with the topic `nixi-plugin` so others can
   discover it.

## 3. Using a shared plugin

Users add your repository to their flake `inputs` and include its default
package in `services.nixi.companion.plugins`:

```nix
{
  inputs.my-plugin.url = "github:<owner>/<repo>";
}
```

```nix
{
  services.nixi.companion.plugins = [
    inputs.my-plugin.packages.${pkgs.stdenv.hostPlatform.system}.default
  ];
}
```
