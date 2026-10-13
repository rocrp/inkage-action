# inkage-action

Ready-to-display images for e-paper panels, rendered on a schedule by **GitHub Actions only** and published as a static GitHub Pages Site that devices download. No server. Refresh cadence is real (down to a minute): each Run dispatches the next one, so GitHub's unreliable cron is not in the loop.

- Live Site of this repo: <https://rocrp.github.io/inkage-action/> (gallery) · [`manifest.json`](https://rocrp.github.io/inkage-action/manifest.json)
- Vocabulary: [`CONTEXT.md`](CONTEXT.md) · design: [`docs/design.md`](docs/design.md) · decisions: [`docs/adr/`](docs/adr/)

Each **Frame** is an indexed PNG whose palette has exactly N entries in the fixed **Ink Order** `black, white, red, yellow, blue, green` (a BW panel uses the first 2, BWR 3, BWRY 4, Spectra 6 all 6). Index `i` means the same ink everywhere. Optional **Encoders** (e.g. `pcim`) add device-native packings beside it.

## Use in your own repo

1. Create a repo (public keeps Actions minutes free) with `inkage.toml`:

   ```toml
   [defaults]
   timezone = "Europe/Berlin"

   [sources.calendar]
   panels = ["800x480-bwr"]          # Preset ids, or your own [panels.<id>]
   ```

2. Add `.github/workflows/inkage.yml`:

   ```yaml
   name: inkage
   on:
     schedule:
       - cron: "2-59/5 * * * *"      # only restarts the chain if it ever breaks
     workflow_dispatch:              # required: each Run dispatches the next
   permissions:
     contents: read
     pages: write
     id-token: write
     actions: write                  # dispatch the next Run, re-enable the schedule
   jobs:
     publish:
       uses: rocrp/inkage-action/.github/workflows/publish.yml@v1
       # with:
       #   config: inkage.toml
       #   sources_dir: sources       # custom Sources
       #   fonts_dir: fonts           # defaults to ./fonts when present
       #   chain: false               # private repo: do not keep a (billed) job waiting
   ```

3. Repo **Settings → Pages → Source: GitHub Actions** (or `gh api -X POST repos/OWNER/REPO/pages -f build_type=workflow`).
4. Run the workflow once (`gh workflow run inkage`). Frames appear at `https://OWNER.github.io/REPO/<source>/<panel>.png`.

That first run starts the **chain**: after deploying, a second job waits until the earliest `next_due` and dispatches the next Run. GitHub's `schedule` drops most 5-minute ticks (measured: 3 of ~130 in 11 hours), so the cron is only there to restart the chain after a runner dies. A push or manual run deploys immediately and takes over the chain. The chain keeps one mostly-sleeping job alive around the clock: free on public repos, billed on private ones (set `chain: false` there and live with cron). For belt and braces, any external cron can `gh workflow run inkage -R OWNER/REPO` with a token holding `actions: write`.

A complete example lives in [`examples/consumer/`](examples/consumer/).

**Only the action** (publish somewhere else, e.g. release assets): `uses: rocrp/inkage-action@v1` with inputs `config`, `sources_dir`, `fonts_dir`, `site_url` (live Site holding the previous Manifest; empty = regenerate all), `out`, `force` (regenerate all while retaining previous Frames on failure). Outputs: `dist` (Site directory), `failed` (`'true'` if a Source failed at runtime) and `next_due` (earliest next due time, for your own chain step).

### Custom Sources

Put each Source in `sources/<name>/` and pass `sources_dir: sources`. Names must not collide with any built-in Source; a collision fails validation.

- **Template-only**: `sources/<name>/templates/<w>x<h>.html` (Jinja2). Supported sizes come from the file names. Set `schedule` in the config.
- **Python**: add `sources/<name>/source.py` with one `Source` subclass:

  ```python
  from inkage.schedule import Schedule
  from inkage.source import Context, Source

  class Weather(Source):
      sizes = ((800, 480),)                    # or omit: taken from templates/
      schedule = Schedule.parse({"every": "30m"})
      dither = "threshold"                     # or "floyd-steinberg", "atkinson", ... (see below)
      requires_secrets = ("WEATHER_KEY",)      # env vars checked at validation
      params = {"city": "Berlin"}              # config keys with defaults
      fields = ("temp",)                       # fetch() must return these, non-empty

      async def fetch(self, ctx: Context) -> dict:
          ...                                  # raise on incomplete data; never return blanks
          return {"temp": 21}
      # render() defaults to templates/<w>x<h>.html; may also return a PIL Image.
  ```

Template context: `data` (from `fetch`), `now` (local datetime), `params`, `panel` (`id`, `width`, `height`, `palette`, `inks`) and `ink` (CSS hex per available ink, e.g. `{{ ink.red }}`). Use `{% if 'red' in panel.inks %}` to adapt to the palette. Pages render in headless Chromium at the Panel's exact size; text is drawn without antialiasing.

**Fonts**: built-in templates bundle Fusion Pixel 12 (body), Fusion Pixel 10 (metadata), Unifont 16 (larger Chinese), and Departure Mono 11 (Latin/numerals). Sizes use integer multiples of each font's base size, without synthetic bold. [Font versions and licenses](src/inkage/fonts/README.md). Consumer files in `fonts/` (`.ttf .otf .woff .woff2`) remain available as families named after the file stem: `fonts/Pixel.ttf` → `font-family: "Pixel"`. Noto Sans CJK SC remains installed for custom templates. A code push regenerates all Frames so daily layouts receive font/template changes immediately, retaining the previous Frame if its Source fails. For a manual CLI refresh, use `inkage run --site-url <live-site> --force`.

**Secrets**: map repository secrets to environment variables in your own workflow when you need them; a Source's `requires_secrets` must all be set or validation fails. With the reusable workflow, call the action directly in your own job (steps: checkout, `actions/configure-pages`, `rocrp/inkage-action@v1` with `env:` secrets, `upload-pages-artifact`, `deploy-pages`) since reusable workflows do not forward arbitrary env.

## Config

```toml
[defaults]
timezone = "Asia/Shanghai"            # default for Schedules and display

[panels.tag]                          # inline Panel ...
width = 250
height = 122
palette = "bwr"                       # bw | bwr | bwry | spectra6
measured = [[30, 30, 30], [255, 255, 255], [190, 40, 40]]   # dither target (default: nominal)
encoders = ["pcim"]

[panels.frame]                        # ... or a Preset
preset = "800x480-spectra6"

[sources.csi300]                      # instance id = site path
source = "index"                      # Source name (default: the instance id)
symbols = ["sh000300", "sh000001"]  # Source params; several symbols = one Watchlist Frame
panels = ["tag", "800x480-bwr"]
timezone = "Asia/Shanghai"            # optional override
schedule = { every = "5m", window = { time = "09:30-15:00", days = "mon-fri" }, fallback = "6h" }
dither = { method = "atkinson", serpentine = true, strength = 0.8, distance = "ycbcr" }
```

- **Schedule**: `every` (+ optional `window` and `fallback`; no fallback = no refresh outside the window) or `at = ["00:05", "12:00"]`, never both. A window crossing midnight belongs to the weekday it starts on. Four minutes of tolerance absorb Run jitter: a late Run followed by an on-time one never skips a cycle. `every = "1m"` works (a Run takes about a minute), but every regeneration is a Pages deploy and, on the device, an e-paper refresh; 5 minutes is the sensible floor for prices.
- **Presets**: `{250x122,296x128,400x300,648x480,800x480}-{bw,bwr,bwry}`, `800x480-spectra6`, `400x600-spectra6`.
- **Dither**: `threshold` (nearest color, default for UI), `floyd-steinberg`, `atkinson`, `stucki`, `jjn`, `burkes`, `sierra`, `bayer4`, `bayer8`; options `serpentine`, `strength` (0–2), `distance` (`rgb` | `ycbcr`).

Built-in Sources (all key-less; every one has 800×480 and 250×122 layouts unless noted):

| Source | What | Default Schedule | Params |
|---|---|---|---|
| `calendar` | date, weekday, lunar date, solar term, festivals, month grid | daily 00:05 | — |
| `index` | China indices (up = red); several `symbols` = a Watchlist table | 5 min 09:30–15:00 Mon–Fri Asia/Shanghai, else 6 h | `symbols` (Tencent codes: `sh000300` CSI 300, `sh000001` SSE, `sz399006` ChiNext), `label` (single symbol only), `max_age_hours` |
| `stock` | US equities (up = green or black, down = red); Watchlist as above | 5 min 09:30–16:00 Mon–Fri America/New_York, else 12 h | `symbols`, `label`, `max_age_hours` |
| `crypto` | Kraken spot prices, change since today's open, 24 h range; up to 6 coins | every 5 min, 24/7 | `symbols` (`BTC`, `ETH`, `SOL`, `DOGE`, …), `quote` (`USD`) |
| `weather` | Open-Meteo current conditions + 5-day or next-hours forecast | every 30 min | `latitude`, `longitude`, `label`, `units` (`celsius` / `fahrenheit`), `layout` (`daily` / `hourly`) |
| `air_quality` | CAMS/Open-Meteo model forecast: U.S. AQI, PM2.5/PM10, hourly trend | every 1 h | `latitude`, `longitude`, `label` |
| `fx` | ECB rates via Frankfurter, change vs previous business day | every 6 h | `base`, `symbols` (1–6) |
| `astro` | sunrise, sunset, dawn/dusk, day length, moon phase; offline (`astral`) | daily 00:05 | `latitude`, `longitude`, `label`; the Source's `timezone` must match the location |
| `github` | repo stars, forks, issues, last commit, latest release | every 30 min | `repo` (`owner/name`); uses `GITHUB_TOKEN` when set |
| `github_ci` | recent public GitHub Actions runs, explicit running / completed outcomes | every 15 min | `repo`, `branch` (empty = all), `count` (1–5); anonymous |
| `github_profile` | public identity + contribution calendar; Profile or isometric wall | every 6 h | `username`, `layout` (`profile` / `isometric`); anonymous |
| `status` | public Statuspage rollup, components and unresolved incidents | every 15 min | `url` (base URL; default GitHub Status), `label` |
| `news` | Hacker News top stories, or any RSS/Atom feed | every 30 min | `feed` (`hn` or a URL), `count` (1–30), `label` |
| `poetry` | complete public-domain short poems; offline selection with provenance | daily 00:10 | `language` (`mixed` / `en` / `zh`); six curated poems |
| `art` | public-domain Met Museum painting, entire artwork retained with caption | daily 00:10 | `artwork_id` (0 = daily curated rotation; otherwise Met object ID) |
| `countdown` | days until (or since) your events; offline | daily 00:05 | `events = [{ title, date, repeat = "yearly" \| "none" }]` |
| `photo` | a photo cover-cropped to the Panel, Atkinson-dithered; any Preset size | daily 00:10 | `url` (empty = Bing's photo of the day) |

[Detailed source notes and examples](docs/sources.md): contribution definitions, small-panel layouts, museum/poem provenance, anonymous API limits. The demo includes English and Chinese reading content; interface labels are English-first.

## Site

```
manifest.json                   { generated_at, frames: [{source, panel, url, sha256, generated_at, next_due, error?, retry_at?, encoders}] }
index.html                      gallery
<source>/<panel>.png            Frame (indexed PNG, Ink Order)
<source>/<panel>.json           Sidecar: that Frame's Manifest entry
<source>/<panel>.preview.png    RGB Preview (humans only)
<source>/<panel>.pcim           Encoder output, when enabled
```

Devices: fetch the Sidecar (or Manifest), compare `sha256`, download the PNG with `If-None-Match`, sleep until about `retry_at` (if present) or `next_due` plus a minute (Run overhead; after a broken chain the cron's recovery takes hours). Every `url` is Site-relative: join it with the base you fetched the Manifest from, so a mirror of the Site works unchanged. A Source that fails keeps its previous Frame and original freshness timestamps, gets `error` and an independent scheduled `retry_at`, and fails the workflow run after the Site is deployed. A successful deployment still continues the Chain; retries wait for their due time, so a persistent upstream failure cannot trigger immediate redispatch loops.

**pcim**: 16-byte little-endian header `"PCIM"`, version `1`, bpp `4`, palette count, reserved `0`, width u16, height u16, payload length u32; then 4bpp pixels, high nibble first, rows padded to a whole byte.

## CLI

```sh
just setup                                   # uv sync + Chromium
uv run inkage validate inkage.toml           # resolved (Source, Panel) pairs
uv run inkage plan --manifest prev.json      # due / not due, reason, next_due
uv run inkage convert photo.jpg --panel 800x480-spectra6 --dither atkinson
uv run inkage render calendar --panel 800x480-bwr
uv run inkage run --site-url https://rocrp.github.io/inkage-action/ --out dist
just check                                   # lint, types, tests
```

## Credits

Spectra 6 measured palette derived from [epdoptimize](https://github.com/Utzel-Butzel/epdoptimize); BW/BWR/BWRY dither colors follow the [EPD-nRF5](https://github.com/tsl0922/EPD-nRF5) web tool. Market data: Tencent's public quote endpoint. License: MIT.
