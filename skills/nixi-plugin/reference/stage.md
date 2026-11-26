# Stage reference (`stage`)

A stage plugin runs a program inside a bubblewrap sandbox when the user says
one of its phrases (or when the agent asks for the plugin by ID) and displays
the JSON stage card printed on stdout (`app/plugins.py:188–231`, `:860–991`).

### Table: stage keys

| Key | Required | Type and limits |
| --- | --- | --- |
| `phrases` | yes | Non-empty list of non-empty strings (`app/plugins.py:192`). None may clash with Nixi's reserved phrases (`app/plugins.py:49–60`, `:229–231`). |
| `argv` | yes | List of 1–8 non-empty strings, each at most 80 characters with no control or format marks (`app/plugins.py:192–195`). `argv[0]` must be a regular file inside the plugin folder; `argv[1:]` must not start with `/`, contain `=/`, or contain `..` as a `/` or `=` segment (`app/plugins.py:225–228`). |
| `hint` | no | String of at most 79 characters with no control or format marks, shown to the agent and on the consent card (`app/plugins.py:196–197`). |
| `network` | no | Boolean (`false` by default). When `true`, the sandbox gets an isolated network namespace via `pasta`; cannot be combined with any `reads` feed (`app/plugins.py:198–199`, `:219–224`). |
| `cache_seconds` | no | Integer from `0` to `600` (`60` by default; `app/plugins.py:214–216`). |
| `reads` | no | List of status feeds passed on stdin (`app/plugins.py:217–218`); see the table below. |
| `config` | no | Boolean (`false` by default). When `true`, the plugin folder must contain `defaults.json` (a JSON object of at most 16 KiB). Settings live at `$XDG_CONFIG_HOME/nixi-companion/plugin-config/<id>.json` (default `~/.config/...`) and the user file is seeded when they choose Edit (`app/plugins.py:205–213`, `:247–284`, `app/server.py:2704–2712`). |
| `videos` | no | Boolean. Reserved for the `"news"` plugin (`app/plugins.py:200–204`); other plugins must omit it or set `false`. |

## Status feeds (`reads`) and stdin

On every run, Nixi writes one JSON object to the program's stdin and closes it
(`app/plugins.py:929–954`). Base fields are always present:

```json
{
  "v": 1,
  "query": "what the user said",
  "locale": "en"
}
```

When `config: true`, `"config"` is added with the merged `defaults.json` and
user settings file at the XDG config path above. That file is created from
defaults when the user chooses Edit; until then defaults still reach stdin.
Each entry in
`reads` requests an extra key on stdin (`app/plugins.py:217`, `:930–938`):

### Table: reads

| Feed | Stdin key | Stdin fields and availability |
| --- | --- | --- |
| `system-status` | `system_status` | Object with `generation`, `rev`, `built`, `failed` (user units list or `null`), `failed_system` (system units list or `null`), `cpu_pct`, `mem` (`{total, available}` or `null`), `disks` (`[{path, total, used}]` or `null`), `net` (`{rx_bps, tx_bps}`), `uptime_s`, and `host` (`app/plugins.py:803–839`). |
| `peer-status` | `peers` | List of `{name, state, status, last_ok, note?}` objects for configured tailnet machines (`state` is `"up"`, `"down"` or `"asking"`; `status` is `null` while asking or down, otherwise holds `{host, generation, rev, built, cpu_pct, uptime_s, failed: null, mem, disks, net, failed_system}`; `app/peers.py:58–59`, `:98–103`, `:161–165`). `peers` is absent when no peers are configured or **Other machines** (`peers_on`) is off (`app/plugins.py:934–936`, `app/server.py:433`). |
| `phone-status` | `phone` | List of `{name, online, battery, charging}` objects for your phone devices — only name, online, battery and charging, with no device IDs, phone numbers or message texts (`app/plugins.py:937–938`, `docs/GUIDE.md:503`). Only supplied while Phone is on; `phone` may be absent when Phone is off. |

## Output stage schemas (stdout)

The program must exit with code `0` and print a single JSON object on stdout
(at most 64 KiB; `app/plugins.py:582`, `:976–991`). Only three `kind` values
are accepted from a stage plugin (`app/plugins.py:989`, `app/stages.py:138–245`):

### 1. `facts`

A card with a title and 1–5 bullet points (`app/stages.py:138–154`):

```json
{
  "v": 1,
  "kind": "facts",
  "title": "Card title (1–120 chars)",
  "points": [
    "First point (1–120 chars)",
    "Second point (1–120 chars)"
  ],
  "source": "Optional footer note (1–120 chars)",
  "say": "Optional spoken summary (1–200 chars)"
}
```

### 2. `gauges`

A live status board for 1–6 hosts (`app/stages.py:182–245`):

- Top-level keys: `v: 1`, `kind: "gauges"`, `title` (1–80 chars), `hosts` (list
  of 1–6 host objects), optional `source` (1–120 chars), optional `live`
  (boolean; adds a refresh token), optional `say` (1–200 chars).
- Each host object in `hosts`:
  - `name` (required): string matching `[A-Za-z0-9._-]{1,32}`. If you build a
    gauge host name from a phone or device name, sanitise it to match this
    pattern (`docs/GUIDE.md:503`).
  - `state` (optional): `"up"` (default), `"down"` or `"stale"`.
  - `badges` (optional, up to 6): `{"k": "<1–16 chars>", "v": "<1–60 chars>", "tone": "ok"|"warn"|"bad"}` (`tone` is optional on badges, meters and lists).
  - `meters` (optional, up to 8): `{"label": "<1–12 chars>", "pct": <0..100 or null>, "v": <number >= 0>, "text": "<1–40 chars>", "tone": "ok"|"warn"|"bad"}` (`v` and `text` are optional).
  - `lists` (optional, up to 2): `{"title": "<1–24 chars>", "items": ["<1–80 chars>", ...], "tone": "ok"|"warn"|"bad"}` (up to 5 items per list).

### 3. `headlines`

A card with 1–5 news or feed items (`app/stages.py:155–181`):

- Top-level keys: `v: 1`, `kind: "headlines"`, `title` (1–80 chars), `items`
  (list of 1–5 item objects), optional `source` (1–120 chars), optional `say`
  (1–200 chars), optional `video_query` (3–60 chars matching
  `[A-Za-z0-9 '-]{3,60}`, used only when `videos: true` on `news`).
- Each item in `items`:
  - `title` (required): 1–160 chars.
  - `source` (required): 1–40 chars.
  - `at` (required): positive integer Unix timestamp or `null` (timestamps more
    than 600 s in the future are clamped to `null`).
  - `url` (optional): public `https://` URL of at most 400 chars (invalid or
    private-domain URLs such as `localhost`, `.local`, `.lan`, `.ts.net` are
    stripped, not rejected; `app/stages.py:338–351`).

## Sandbox environment

Stage programs run without a shell (`app/plugins.py:581–675`, `:896–991`):

- **Filesystem:** `/nix/store` is bound read-only; `/usr/bin/env` is also
  bound read-only if present. A
  hash-verified snapshot of the plugin folder is bound read-only at `/plugin`
  (current working directory); `/tmp` (64 MiB tmpfs, `HOME=/tmp`) and
  `/dev/shm` (16 MiB tmpfs) are writable. There is **no `/bin/sh`** inside the
  sandbox (`app/plugins.py:664`) — start Python scripts with
  `#!/usr/bin/env python3`.
- **Limits:** 3 s default timeout (capped at 8 s), 64 KiB stdout, 8 KiB stderr,
  1 GiB virtual memory (`RLIMIT_AS`), at most 64 processes (`RLIMIT_NPROC`),
  and at most 64 MiB total folder size (`SNAP_MAX`).
- **Network (`network: true`):** `pasta` runs the sandbox in its own network
  namespace (`--no-map-gw`, no inbound port forwarding, `/etc/ssl` and
  `/etc/static/ssl` bound read-only if present), and `ip route replace unreachable` blocks
  every local address belonging to the host plus `100.100.100.100` and
  `fd7a:115c:a1e0::53` (`app/plugins.py:615–640`, `:672–674`).
