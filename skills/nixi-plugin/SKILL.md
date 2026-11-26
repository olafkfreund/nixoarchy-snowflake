---
name: nixi-plugin
description: >-
  Make, check, install and share a Nixi companion plugin (quips, prop,
  character, notifications, reactions or stage). Triggers: "make a Nixi plugin",
  "Nixi companion plugin", "share a plugin".
---

# Making and sharing a Nixi companion plugin

Follow this walkthrough from idea to a checked, working plugin. Key lists and
field limits live in the reference pages so they stay in one place:

- [reference/manifest.md](reference/manifest.md) — `plugin.json` structure, SVG limits, props, characters, notifications and reactions
- [reference/stage.md](reference/stage.md) — stage programs, sandbox rules, stdin feeds and stdout card schemas
- [reference/sharing.md](reference/sharing.md) — Home Manager installation, standalone flake repositories and the `nixi-plugin` topic
- [reference/private.md](reference/private.md) — private characters (local-only folder workflow)

## Walkthrough

### 1. Choose the kind

A single plugin can combine several parts in its `plugin.json`, or ship just
one. Pick what you are building and inspect the matching example under
`plugins/examples/` in the companion repository. None of the examples in
`plugins/examples/` shows a `character` or `reactions`.

| Kind | Use it for | Example to copy from |
| --- | --- | --- |
| quips | Extra lines Nixi says on ambient cues | `plugins/examples/pirate-quips/` |
| prop | One SVG accessory he wears (`plug:<id>` under Skin) | `plugins/examples/party-hat-plus/` |
| character | A whole body he wears (`plug:<id>` under Character) | *(none — see [reference/manifest.md](reference/manifest.md) and [reference/private.md](reference/private.md))* |
| notifications | Routing an app's or host's notifications into a category | `plugins/examples/element-chat/` |
| reactions | Triggering an ambient reaction for an app or host | *(none — see [reference/manifest.md](reference/manifest.md))* |
| stage | Running a sandboxed program that returns a card | `plugins/examples/nix-status/`, `plugins/examples/rss-headlines/` |

The built-in `news` plugin is useful to read, but its `videos: true` setting is
reserved for the `news` ID, so do not copy it for another plugin.

### 2. Private characters branch off before copying or editing any art

If your plugin defines a character with `"private": true`, follow
[reference/private.md](reference/private.md) now. Create the owner-only local
destination before writing or copying any character art. Keep it out of Nix
and repositories (`app/plugins.py:1036–1037`, `docs/GUIDE.md:493–496`).

### 2b. Copy the template for other plugins

Copy the `template/` folder next to this `SKILL.md` into a fresh directory with
`-rL --no-preserve=mode`:

```bash
SKILL_DIR="$(dirname /path/to/skills/nixi-plugin/SKILL.md)"
mkdir -p ./my-plugin
cp -rL --no-preserve=mode "$SKILL_DIR/template/." ./my-plugin/
```

Why `-L --no-preserve=mode` matters: when this skill is installed through Home
Manager, files inside `template/` may be symlinks into `/nix/store` with
read-only modes. The plugin checker and runtime scanner reject any folder that
contains a symlink (`app/plugins.py:327`, `:1039`).

Open `./my-plugin/plugin.json`, change `id` (and `pname` in
`./my-plugin/flake.nix`) to your plugin's lowercase ID, and replace the sample
phrase. The template is a stage plugin: keep `stage` and run `chmod +x
./my-plugin/run` only for stage plugins. For any other kind, delete the `stage`
block and `run`; it then needs neither stage consent nor bubblewrap. Edit the
remaining files for the kind you chose.

### 3. Check

1. **Build-time check.** From the directory containing `my-plugin`, run:

   ```bash
   (cd ./my-plugin && nix build --no-link)
   ```

   If `my-plugin` is in a git repository, run `git add` on its files before
   this build: Nix only sees tracked files from a git source.

   The template's `flake.nix` calls `mkCompanionPlugin`, which runs
   `plugins.py --check` during `checkPhase` (`nix/plugin.nix:19`). Always pass
   `--no-link`: a `result` symlink inside the plugin folder will make both
   `--check` and the runtime scanner reject the folder (`app/plugins.py:327`,
   `:1039`).

2. **Live run as a folder plugin.** Copy the folder into
   `$XDG_DATA_HOME/nixi-companion/plugins/` (default
   `~/.local/share/nixi-companion/plugins/`):

   ```bash
   mkdir -p "${XDG_DATA_HOME:-$HOME/.local/share}/nixi-companion/plugins"
   dest="${XDG_DATA_HOME:-$HOME/.local/share}/nixi-companion/plugins/my-plugin"
   mkdir -p "$dest"
   cp -rL --no-preserve=mode ./my-plugin/. "$dest/"
   ```

   For a stage plugin, also run `chmod +x "$dest/run"`.

   Open Settings → **Plugins** and turn it on. Only a **folder** stage plugin
   shows the consent card (`app/server.py:2724–2739`); a Nix-installed stage
   plugin counts as allowed once you switch it on (`docs/GUIDE.md:507–510`).

3. **Verify the behaviour:**
   - **Stage plugins:** say the phrase (or type it) and confirm the card
     appears.
   - **Props and characters:** choose `plug:<id>` in Settings → **Look** (under
     Skin or Character).
   - **Quips, notifications and reactions:** trigger the cue or notification
     and confirm the line, category or reaction appears.

4. **Sandbox tool errors to expect.** Stage programs run inside bubblewrap
   (`bwrap`), and network stage plugins also need `pasta` (from `passt`) and
   `ip` (from `iproute2`). When one of these tools is missing or cannot create
   its namespace, Nixi reports:
   - Turning on a stage plugin without `bwrap` (`app/server.py:2725`):
     `plugins that run programs need bubblewrap (bwrap), and it doesn't work here`
   - Running a stage plugin without `bwrap` (`app/plugins.py:905`):
     `bubblewrap isn't working here`
   - Running a network stage plugin without `pasta` (`app/plugins.py:907`):
     `plugins that use the internet need pasta (passt), and it doesn't work here`
   - Running a network stage plugin when `ip` cannot read local routes
     (`app/plugins.py:639`):
     `can't tell which addresses this computer has, so a plugin that uses the internet can't run safely`

*(Private characters take the branch at step 2, before any build.)*

### 4. Install

Install the plugin declaratively through `services.nixi.companion.plugins`
(from nixi's Home Manager module) using
`nixi.lib.<system>.mkCompanionPlugin { pname; src; }` (`x86_64-linux` and
`aarch64-linux`), or keep it in `~/.local/share/nixi-companion/plugins/` as a
folder plugin. See [reference/sharing.md](reference/sharing.md) for the exact
Home Manager snippet.

### 5. Share

Put the plugin in its own git repository with the template's `flake.nix`, and
add the GitHub topic `nixi-plugin`. Users add your repository to their flake
`inputs` and list `inputs.<name>.packages.<system>.default` in
`services.nixi.companion.plugins`. See [reference/sharing.md](reference/sharing.md).

## Never do this

- **Never combine `network: true` with `reads`** (`app/plugins.py:219–224`). A
  network stage cannot use any status feed; see [reference/stage.md](reference/stage.md).
- **Never point `argv[0]` outside the plugin folder**
  (`app/plugins.py:225–226`). `argv[0]` must be a regular file inside the
  folder.
- **Never use absolute paths or `..` in `argv` arguments**
  (`app/plugins.py:227–228`). Any word starting with `/`, containing `=/`, or
  containing `..` as a `/` or `=` segment is rejected.
- **Never put symlinks or hard links inside a folder plugin.** The checker and
  scanner reject symlinks (`app/plugins.py:327`, `:1039`); the stage snapshot
  rejects hard links outside the Nix store (`app/plugins.py:370–391`).
- **Never set `videos: true` for an ID other than `news`**
  (`app/plugins.py:200–204`). `videos: false` is accepted.
- **Never skip the SVG sanitiser limits** (`app/plugins.py:462–578`). Any
  disallowed element, attribute, text node, transform scale or file size over
  16 KiB drops the prop or character and fails `--check`.
- **Never commit or name a private character in a Nix expression.** Follow
  this rule before Nix takes the source. The build check rejects a private
  manifest only afterward (`docs/GUIDE.md:493–496`, `app/plugins.py:1036–1037`).

Update skills/nixi-plugin/reference when the plugin API changes.
