# Manifest reference (`plugin.json`)

Every plugin folder has a plain file `plugin.json` of at most 64 KiB
(`app/plugins.py:287–296`). Strings in `name`, `version`, `description` and
`character.label` must not contain control characters or Unicode line/direction
format marks (`app/plugins.py:94–100`).

### Table: manifest keys

| Key | Required | Type and limits |
| --- | --- | --- |
| `api` | yes | Integer `1` (`app/plugins.py:121`). |
| `id` | yes | Lowercase string matching `^[a-z0-9][a-z0-9._-]{2,63}$` (`app/plugins.py:27`, `:127`). |
| `name` | yes | Non-empty string of at most 60 characters (`app/plugins.py:129–131`). |
| `version` | yes | Non-empty string of at most 1000 characters (`app/plugins.py:129–131`). |
| `description` | no | Non-empty string of at most 200 characters (`app/plugins.py:129–131`). |
| `quips` | no | Relative path inside the folder to a JSON object mapping event names (`break`, `welcome`, `ram`, `cpu`, `rain`, `snow`, `night`, `party`, `coding`, `done`, etc.) to lists of strings (`app/plugins.py:132–133`, `app/server.py:2528–2539`). |
| `prop` | no | Object configuring an SVG accessory (`app/plugins.py:134–141`). Appears in Settings → Look → Skin as `plug:<id>`. |
| `character` | no | Object configuring a full character body (`app/plugins.py:142–163`). Appears in Settings → Look → Character as `plug:<id>`. |
| `notifications` | no | List of `{"app": "<id>", "category": "<category>"}` or `{"host": "<host>", "category": "<category>"}` objects (`app/plugins.py:164–175`). |
| `reactions` | no | List of `{"app": "<id>", "reaction": "<reaction>"}` or `{"host": "<host>", "reaction": "<reaction>"}` objects (`app/plugins.py:176–187`). |
| `stage` | no | Object configuring a sandboxed stage program (`app/plugins.py:188–231`); see [stage.md](stage.md). |

## Props

A `prop` draws one sanitised SVG on Nixi (`app/plugins.py:134–141`).

### Table: prop keys

| Key | Required | Type and allowed values |
| --- | --- | --- |
| `file` | yes | Relative path inside the plugin folder to an SVG file that passes `sanitize_svg` (`app/plugins.py:140–141`, `:1042–1046`). |
| `anchor` | yes | One of `"head"`, `"left"`, `"right"` or `"base"` (`app/plugins.py:138`). |
| `layer` | no | `"front"` (default) or `"back"` (`app/plugins.py:138`). |

## Characters

A `character` replaces the body art while keeping the face and eyes
(`app/plugins.py:142–163`, `docs/GUIDE.md:484–495`). Every key in the table
below is required except `private`. Each SVG file's `viewBox` is fitted to the
body box; draw with `viewBox="-96 -120 192 220"` (the face sits near `0,0`).

### Table: character keys

| Key | Required | Type and limits |
| --- | --- | --- |
| `label` | yes | Non-empty string of at most 20 characters shown in Settings → Look (`app/plugins.py:146–147`). |
| `template` | yes | Must be `"round"` (`app/plugins.py:148–149`). |
| `fill` | yes | Hex colour matching `#[0-9a-fA-F]{6}` (`app/plugins.py:150–151`). |
| `back` | yes | Relative path inside the folder ending in `.svg`, drawn behind the face (`app/plugins.py:156–163`). |
| `front` | yes | Relative path inside the folder ending in `.svg`, drawn in front of the face (`app/plugins.py:156–163`). |
| `fits` | yes | List of skins from the round template's allowed fits below (`app/plugins.py:152–153`). |
| `private` | no | Boolean (`false` by default). When `true`, the plugin is local-only; see [private.md](private.md) (`app/plugins.py:154–155`). |

### Table: round fits

| Fit | What it is |
| --- | --- |
| `none` | Bare character with no skin |
| `halo` | Halo above the head |
| `crown` | Crown on the head |
| `sprout` | Leaf sprout on the head |
| `bow` | Bow accessory |
| `nightcap` | Nightcap (also worn automatically late at night) |
| `beanie` | Cold-weather beanie |
| `party` | Party hat |
| `scarf` | Cold-weather scarf |
| `tie` | Meeting tie |
| `headphones` | Music headphones |
| `shades` | Fullscreen sunglasses |
| `glasses` | Coding glasses |
| `chat` | Chat notification badge/accessory |
| `feed` | Feed/video notification accessory |
| `plug` | Custom plugin prop (`plug:<id>`) |

## Notifications and reactions

Each entry in `notifications` has either `"app"` or `"host"` (never both) plus
`"category"`. Each entry in `reactions` has either `"app"` or `"host"` (never
both) plus `"reaction"` (`app/plugins.py:164–187`):

- `"app"` must match `^[a-z0-9._-]+$`.
- `"host"` must match `^(\*\.)?[a-z0-9]([a-z0-9.-]*[a-z0-9])?$`.

### Table: categories

| Category | What it does |
| --- | --- |
| `mail` | Counts matching notifications as mail |
| `chat` | Counts matching notifications as chat |
| `feed` | Counts matching notifications as feed / video |

### Table: reactions

| Reaction | What it does |
| --- | --- |
| `notice` | Triggers a notice reaction when a matching notification arrives |
| `music` | Triggers a music reaction for a matching app or host |

## SVG sanitiser rules (`sanitize_svg`)

Both `prop.file` and `character.back` / `character.front` are parsed by
`sanitize_svg` (`app/plugins.py:462–578`), which is default-deny:

- **Size and structure:** UTF-8, at most 16 KiB (`16384` bytes), at most 200
  elements, nested at most 8 levels deep.
- **Forbidden constructs:** `<!DOCTYPE`, `<!ENTITY`, `<?` processing
  instructions, XML namespaces other than `http://www.w3.org/2000/svg`, and any
  non-whitespace element text or tail text.
- **Allowed elements and geometry attributes:**
  - `svg` (root only): `viewBox` (four numbers, width ≥ 1 and height ≥ 1;
    defaults to `0 0 100 100`)
  - `g`: no geometry attributes
  - `path`: `d` (at most 4000 characters; commands `MmLlHhVvCcSsQqTtAaZz` and
    numbers)
  - `circle`: `cx`, `cy`, `r`
  - `ellipse`: `cx`, `cy`, `rx`, `ry`
  - `rect`: `x`, `y`, `width`, `height`, `rx`, `ry`
  - `line`: `x1`, `y1`, `x2`, `y2`
  - `polyline`: `points` (at most 4000 characters)
  - `polygon`: `points` (at most 4000 characters)
- **Allowed style attributes (non-root elements only, at most 64 characters):**
  - `fill`, `stroke`: `none`, `acc`, `text`, `dim`, `#rgb` or `#rrggbb`
  - `stroke-width`: `0` to `1000`
  - `stroke-linecap`: `butt`, `round` or `square`
  - `stroke-linejoin`: `miter`, `round` or `bevel`
  - `fill-opacity`, `stroke-opacity`, `opacity`: `0` to `1`
  - `fill-rule`: `nonzero` or `evenodd`
  - `transform`: `translate(x[, y])`, `scale(sx[, sy])`, `rotate(a[, cx, cy])`.
    Every `scale()` factor must lie between `0.01` and `10`, and cumulative
    scales along any ancestor chain must not multiply to more than `10`.
- **Number range:** every numeric value anywhere in the SVG must lie within
  `±1000`.
