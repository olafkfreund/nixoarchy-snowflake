# Private characters (`character.private: true`)

A character plugin with `"private": true` is for character art that must remain
yours alone on the local machine (`docs/GUIDE.md:493–496`,
`app/plugins.py:34–36`, `:299–313`, `:336–350`, `:1036–1037`).

## Private character rules

1. **Local folder only.** A private character loads only from
   `$XDG_DATA_HOME/nixi-companion/plugins/<id>` (default
   `~/.local/share/nixi-companion/plugins/<id>`). If it appears in the Nix
   package plugin directory or `/nix/store`, Nixi refuses it with:
   `a private character can't come from the Nix store`
   (`app/plugins.py:36`, `:337–338`).
2. **Never run `--check` or build with Nix.** `plugins.py --check` (and
   therefore `mkCompanionPlugin`) deliberately rejects every manifest where
   `character.private` is `true` (`app/plugins.py:1036–1037`). Never name a
   private folder in any Nix expression (`docs/GUIDE.md:495–496`), and keep it
   out of every git repository.
3. **Owner-only permissions.** The folder and every item inside it must be
   owned by your user ID and have no group or other permission bits (`0700`
   directories and `0600` files are examples; `app/plugins.py:299–313`). Otherwise
   Nixi refuses it with:
   `the folder is readable by other users: run chmod -R go= <folder>`
4. **Redacted error messages.** A malformed or unreadable manifest reports
   `plugin.json unreadable`. After the scanner reads `character.private: true`,
   it reports `the character art was refused` for most validation failures;
   store and permission failures have their own fixed messages
   (`app/plugins.py:327–350`). SVG load failures also use the art message
   (`app/server.py:2569`).

## Step-by-step setup

1. Create the owner-only folder directly in your local plugins directory
   **before writing or copying any art**. Keep `umask 077` in effect while
   writing the files:

   ```bash
   umask 077
   DIR="${XDG_DATA_HOME:-$HOME/.local/share}/nixi-companion/plugins/my-character"
   install -d -m 700 "$DIR"
   chmod -R go= "$DIR"
   ```

2. Write `plugin.json`, `back.svg` and `front.svg` inside that folder with
   `umask 077` still in effect, following the
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

3. Open Settings → **Plugins**, turn `my-character` on, then select
   `plug:my-character` in Settings → **Look** → **Character**.
