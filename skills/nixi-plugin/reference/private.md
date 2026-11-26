# Private characters (`character.private: true`)

A character plugin with `"private": true` is for character art that must remain
yours alone on the local machine (`docs/GUIDE.md:492–495`,
`app/plugins.py:34–36`, `:299–313`, `:336–350`, `:1036–1037`).

## Rules enforced by Nixi

1. **Local folder only.** A private character loads only from
   `$XDG_DATA_HOME/nixi-companion/plugins/<id>` (default
   `~/.local/share/nixi-companion/plugins/<id>`). If it appears in the Nix
   package plugin directory or `/nix/store`, Nixi refuses it with:
   `a private character can't come from the Nix store`
   (`app/plugins.py:36`, `:337–338`).
2. **Never run `--check` or build with Nix.** `plugins.py --check` (and
   therefore `mkCompanionPlugin`) deliberately rejects every manifest where
   `character.private` is `true` (`app/plugins.py:1036–1037`). Never name a
   private folder in any Nix expression (`docs/GUIDE.md:494–495`), and keep it
   out of every git repository.
3. **Owner-only permissions (`0700` / `0600`).** Every directory and file inside
   the plugin folder must be owned by your user ID and have zero group/other
   permission bits (`st_mode & 0o077 == 0`; `app/plugins.py:299–313`). Otherwise
   Nixi refuses it with:
   `the folder is readable by other users: run chmod -R go= <folder>`
4. **Redacted error messages.** If anything in the manifest or SVG art fails
   validation, Nixi replaces the detailed parser or sanitiser message with the
   fixed string `the character art was refused` so neither file names nor SVG
   contents are ever logged (`app/plugins.py:34`, `:349–350`,
   `app/server.py:2569`).

## Step-by-step setup

1. Create the folder directly in your local plugins directory:

   ```bash
   DIR="${XDG_DATA_HOME:-$HOME/.local/share}/nixi-companion/plugins/my-character"
   mkdir -p "$DIR"
   ```

2. Write `plugin.json`, `back.svg` and `front.svg` inside `$DIR` following the
   character and SVG rules in [manifest.md](manifest.md) (draw within
   `viewBox="-96 -120 192 220"`):

   ```json
   {
     "api": 1,
     "id": "my-character",
     "name": "My character",
     "version": "1.0.0",
     "character": {
       "label": "My look",
       "template": "round",
       "fill": "#3e5993",
       "back": "back.svg",
       "front": "front.svg",
       "fits": ["none", "headphones", "glasses"],
       "private": true
     }
   }
   ```

3. Lock down the permissions:

   ```bash
   chmod -R go= "$DIR"
   ```

4. Open Settings → **Plugins**, turn `my-character` on, then select
   `plug:my-character` in Settings → **Look** → **Character**.
