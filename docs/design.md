# Inkage design

Vocabulary: see [`CONTEXT.md`](../CONTEXT.md). Decisions with trade-offs: [`docs/adr/`](adr/).

## Goal

Generate e-paper Frames for many Sources × Panels on per-Source Schedules, running **only on GitHub Actions**, publishing a static Site that devices download. Upstream repo ships a default config and is itself the reusable action; users fork nothing — they reference the action from a tiny repo holding `inkage.toml` and optional custom Sources.

## GitHub Actions constraints (verified against official docs, 2026-10)

| Constraint | Effect | Mitigation |
|---|---|---|
| `schedule` min interval 5 min | per-minute refresh impossible | Schedule = min interval + active window; stocks 5–15 min in market hours |
| Top-of-hour delay (5–30 min), jobs may be dropped | ticks jitter / skip | cron phase `2-59/5`; due check with 1-tick tolerance; `next_due` is a hint only |
| Public repo: schedules disabled after 60 days without commits | silent death | workflow step re-enables itself via `gh workflow enable` |
| Stateless runners | no "last generated" memory | previous Manifest fetched from live Site = state |
| Pages: custom-workflow deploys not subject to 10 builds/hour; 100 GB/month soft bandwidth; deploy ≤10 min | fine at 288 deploys/day | full-site snapshot each Run (carry-over of non-due Frames) |
| Runner IPs blocked by some finance APIs | data source choice | default config uses only key-less, runner-reachable public sources |
| Job max 6 h | irrelevant | — |

## Architecture

```
user repo                      inkage-action (this repo)
┌────────────────┐             ┌──────────────────────────────┐
│ inkage.toml    │  uses:      │ .github/workflows/publish.yml│ reusable workflow
│ sources/ (opt) │ ──────────▶ │   checkout caller            │
│ fonts/   (opt) │             │   ▶ action.yml (composite)   │ generate → dist/
│ .github/wf.yml │             │   ▶ upload-pages-artifact    │
└────────────────┘             │   ▶ deploy-pages             │
                               │ src/inkage/  (Python 3.13)   │
                               │ sources/     built-in        │
                               │ presets/     Panel catalog   │
                               └──────────────────────────────┘
```

Two reuse layers: **composite action** (`rocrp/inkage-action@v1`, inputs `config`, `sources_dir`, `site_url`; output `dist/`) and **reusable workflow** wrapping it with Pages deploy. Users default to the workflow; those wanting another publish channel (release assets) use the action. `v1` is a floating tag.

## Run algorithm

1. Load `inkage.toml`; validate fully (unknown Preset, unsupported size, missing secret, bad schedule) → **fail before touching anything**.
2. Fetch previous `manifest.json` + Frames from `site_url`. Missing/unreachable → treat as empty (full regenerate).
3. For each configured (Source, Panel): due?
   - `every`: `now - generated_at >= every - 1m` (inside window), else `fallback`.
   - `at`: first Run after a listed local time since last generation.
4. Due → `fetch()` → `render()` → dither → indexed PNG + Sidecar + Preview + configured Encoders. Runtime failure → keep previous Frame, record `error` in Manifest entry.
5. Not due → copy previous Frame + Sidecar unchanged.
6. Write `manifest.json`, `index.html` gallery.
7. Exit non-zero if any Source failed at runtime (site still deploys; GitHub notifies).

## Site layout

```
/manifest.json
/index.html                    gallery: Preview + URL + generated_at per Frame
/<source>/<panel>.png          Frame (indexed PNG, exactly N palette entries, Ink Order)
/<source>/<panel>.json         Sidecar
/<source>/<panel>.preview.png  Preview (RGB)
/<source>/<panel>.<enc>        Encoder output (.pcim, later .bin/.bmp/.jpg)
```

Manifest entry: `source, panel, url, sha256, generated_at, next_due, error?`. Devices use `If-None-Match` (Pages serves ETag) and may sleep until `next_due`.

## Panel

`id, width, height, palette (bw|bwr|bwry|spectra6), nominal[], measured[]?, encoders[]`. Palette is always a **prefix of Ink Order** `black, white, red, yellow, blue, green`. `nominal` is written into the PNG palette; `measured` (default = nominal) is the dither target. Presets catalog ships: 250×122, 296×128, 400×300, 648×480, 800×480 in their common palettes; 800×480 and 400×600 Spectra 6. Measured values: BWR/BWRY from EPD-nRF5 reference, Spectra 6 white-balanced from epdoptimize (credited).

Known trap: Pillow `quantize` palette image must hold exactly N entries; padding to 256 produces phantom indices.

## Source

```python
class Csi300(Source):
    sizes = [(800, 480), (400, 300)]           # compatibility by size, not panel id
    schedule = Schedule(every="5m", window=Window("09:30-15:00", "mon-fri"), fallback="6h")
    dither = "threshold"                        # UI default; photo sources use "floyd-steinberg" etc.
    requires_secrets = []
    async def fetch(self, ctx) -> dict: ...     # must raise on incomplete data
    def render(self, ctx, panel) -> str | Image: ...  # default: Jinja2 templates/<w>x<h>.html
```

Loading: built-in `sources/<name>/`, user `sources_dir/<name>/`. A Source may be template-only (no Python). Template context includes `panel.palette` so layouts can use red when available. Config selects Sources, picks Panels, overrides Schedule.

## Rendering

- Primary: HTML → Playwright Chromium (Linux runner). Fontconfig `antialias=false` on the runner makes text hard-edged; verify in prototype.
- Secondary: Pillow drawing for pixel-exact small panels.
- Dither per Source: `threshold` (nearest measured color), `floyd-steinberg`, `atkinson`, `stucki`, `jjn`, `burkes`, `sierra`, `bayer4`, `bayer8`; serpentine + strength options; YCbCr-weighted distance. Photo Sources render at 2× then downsample.
- Fonts: `apt install fonts-noto-cjk` in the action; user `fonts/` appended; pixel fonts (GPL bitmap) bundled.

## Config (`inkage.toml`)

```toml
[defaults]
timezone = "Asia/Shanghai"

[panels.p75-bwr]
preset = "waveshare-7in5-bwr"
encoders = []

[panels.p73-s6]
preset = "waveshare-7in3-spectra6"
encoders = ["pcim"]

[sources.calendar]
panels = ["p75-bwr", "p213-bwr"]
schedule = { at = ["00:05"] }

[sources.index]
symbol = "000300"          # CSI 300
panels = ["p75-bwr"]
schedule = { every = "5m", window = { time = "09:30-15:00", days = "mon-fri" }, fallback = "6h" }
```

Default config enables `800x480-bwr`, `250x122-bwr`, `800x480-spectra6`.

## MVP

1. `calendar` Source end-to-end (config → render → dither → Site → Pages) on the default repo.
2. `index` (CSI 300 / SSE) and `stock` (US equities) — data sources: key-less, runner-reachable; to be researched.
3. Encoder `pcim` only (hardware available; byte-level spec as test oracle).

Out of scope here: the rctlsr BLE bridge (consumes the indexed PNG from its own host tool).

## Testing

- Unit with external oracles: Schedule due table (tz, midnight, weekend, tolerance); PCIM bytes hand-computed; Ink Order / palette validation from spec; config samples.
- Dither: FS kernel vs Pillow's FS golden; other kernels on tiny hand-computed images.
- E2E (Playwright): template → browser → PNG has correct size and exactly N palette entries. No visual goldens (fonts differ across hosts).

## Operations

- Default workflow cron `2-59/5 * * * *` (off the hour).
- License MIT. inkboard (GPLv3) and rcinkimage are idea sources only; no code copied.
