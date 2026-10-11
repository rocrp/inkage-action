# inkage-action

Ready-to-display images for e-paper panels, rendered on a schedule by **GitHub Actions only** and published as a static GitHub Pages Site that devices download. No server.

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
       - cron: "2-59/5 * * * *"      # every 5 min, off the top of the hour
     workflow_dispatch:
   permissions:
     contents: read
     pages: write
     id-token: write
     actions: write                  # keepalive: re-enables the schedule
   concurrency:
     group: inkage-pages
     cancel-in-progress: false
   jobs:
     publish:
       uses: rocrp/inkage-action/.github/workflows/publish.yml@v1
       # with:
       #   config: inkage.toml
       #   sources_dir: sources       # custom Sources
       #   fonts_dir: fonts           # defaults to ./fonts when present
   ```

3. Repo **Settings → Pages → Source: GitHub Actions** (or `gh api -X POST repos/OWNER/REPO/pages -f build_type=workflow`).
4. Run the workflow once (`gh workflow run inkage`). Frames appear at `https://OWNER.github.io/REPO/<source>/<panel>.png`.

A complete example lives in [`examples/consumer/`](examples/consumer/).

**Only the action** (publish somewhere else, e.g. release assets): `uses: rocrp/inkage-action@v1` with inputs `config`, `sources_dir`, `fonts_dir`, `site_url` (live Site holding the previous Manifest; empty = regenerate all), `out`. Outputs: `dist` (Site directory) and `failed` (`'true'` if a Source failed at runtime).

### Custom Sources

Put each Source in `sources/<name>/` and pass `sources_dir: sources`. Names must not collide with built-in Sources (`calendar`, `index`, `stock`); a collision fails validation.

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

**Fonts**: files in `fonts/` (`.ttf .otf .woff .woff2 .ttc`) become `@font-face` families named after the file stem: `fonts/Pixel.ttf` → `font-family: "Pixel"`. Noto Sans CJK SC is installed on the runner.

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
symbol = "sh000300"                   # Source params
panels = ["tag", "800x480-bwr"]
timezone = "Asia/Shanghai"            # optional override
schedule = { every = "5m", window = { time = "09:30-15:00", days = "mon-fri" }, fallback = "6h" }
dither = { method = "atkinson", serpentine = true, strength = 0.8, distance = "ycbcr" }
```

- **Schedule**: `every` (+ optional `window` and `fallback`; no fallback = no refresh outside the window) or `at = ["00:05", "12:00"]`, never both. A window crossing midnight belongs to the weekday it starts on. One minute of tolerance absorbs cron jitter.
- **Presets**: `{250x122,296x128,400x300,648x480,800x480}-{bw,bwr,bwry}`, `800x480-spectra6`, `400x600-spectra6`.
- **Dither**: `threshold` (nearest color, default for UI), `floyd-steinberg`, `atkinson`, `stucki`, `jjn`, `burkes`, `sierra`, `bayer4`, `bayer8`; options `serpentine`, `strength` (0–2), `distance` (`rgb` | `ycbcr`).

Built-in Sources:

| Source | What | Default Schedule | Params |
|---|---|---|---|
| `calendar` | date, weekday, lunar date, solar term, festivals, month grid | daily 00:05 | — |
| `index` | China index (up = red) | 5 min 09:30–15:00 Mon–Fri Asia/Shanghai, else 6 h | `symbol` (`sh000300` CSI 300, `sh000001` SSE), `label`, `max_age_hours` |
| `stock` | US equity (up = green or black, down = red) | 5 min 09:30–16:00 Mon–Fri America/New_York, else 12 h | `symbol`, `label`, `max_age_hours` |

## Site

```
manifest.json                   { generated_at, frames: [{source, panel, url, sha256, generated_at, next_due, error?, encoders}] }
index.html                      gallery
<source>/<panel>.png            Frame (indexed PNG, Ink Order)
<source>/<panel>.json           Sidecar: that Frame's Manifest entry
<source>/<panel>.preview.png    RGB Preview (humans only)
<source>/<panel>.pcim           Encoder output, when enabled
```

Devices: fetch the Sidecar (or Manifest), compare `sha256`, download the PNG with `If-None-Match`, sleep until about `next_due` (a hint: Actions cron runs 5–30 min late under load). A Source that fails keeps its previous Frame, gets `error` in its entry, and fails the workflow run after the Site is deployed.

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
