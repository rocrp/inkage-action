# Inkage design

Vocabulary: see [`CONTEXT.md`](../CONTEXT.md). Decisions with trade-offs: [`docs/adr/`](adr/).

## Goal

Generate e-paper Frames for many Sources × Panels on per-Source Schedules, running **only on GitHub Actions**, publishing a static Site that devices download. Upstream repo ships a default config and is itself the reusable action; users fork nothing — they reference the action from a tiny repo holding `inkage.toml` and optional custom Sources.

## GitHub Actions constraints (verified against official docs, 2026-10)

| Constraint | Effect | Mitigation |
|---|---|---|
| `schedule` ticks are mostly dropped (measured: 3 of ~130 in 11 h, 2026-10), the rest hours late | cron alone cannot refresh anything intraday | the Chain: each Run dispatches the next at `next_due` ([ADR 0003](adr/0003-self-dispatch-chain.md)); cron only resurrects |
| Job max 6 h | one Run cannot wait longer | Chain sleep capped at 5 h 50 min; an idle Run redeploys the unchanged Site |
| Public repo: schedules disabled after 60 days without commits | silent death | workflow step re-enables itself via `gh workflow enable` |
| Stateless runners | no "last generated" memory | previous Manifest fetched from live Site = state |
| Pages: custom-workflow deploys not subject to 10 builds/hour; 100 GB/month soft bandwidth; deploy ≤10 min | fine at 288 deploys/day | full-site snapshot each Run (carry-over of non-due Frames) |
| Runner IPs blocked by some finance APIs | data source choice | default config uses only key-less, runner-reachable public sources |

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

## Chain

`publish.yml` has two jobs. `publish` renders and deploys (concurrency `inkage-publish`, never cancelled). `chain` (`needs: publish`, concurrency `inkage-chain`, `cancel-in-progress: true`) runs `scripts/chain-next.sh`: sleep until the action's `next_due` output minus a 60 s lead (the next Run's checkout and setup), capped at 5 h 50 min, then `gh workflow run <calling workflow> --ref <branch>` with `GITHUB_TOKEN`. A push, cron tick or manual dispatch deploys at once and its own `chain` job replaces the sleeping one, so exactly one waiter exists. Input `chain: false` disables it (private repos: minutes are billed).

## Run algorithm

1. Load `inkage.toml`; validate fully (unknown Preset, unsupported size, missing secret, bad schedule) → **fail before touching anything**.
2. Fetch previous `manifest.json` + Frames from `site_url`. Missing/unreachable → treat as empty (full regenerate).
3. For each configured (Source, Panel): due?
   - `every`: `now - generated_at >= every - 4m` (inside window), else `fallback`. 4m = one tick minus a minute: a late Run then an on-time one still regenerates; Runs a minute apart don't both.
   - Previous Manifest of another schema `version`, a missing carried file, or a Panel whose `encoders` changed → regenerate that Frame.
   - `at`: first Run after a listed local time since last generation.
4. Due → `fetch()` → `render()` → dither → indexed PNG + Sidecar + Preview + configured Encoders. Runtime failure → keep previous Frame and original freshness times, record `error` and independently scheduled `retry_at`. Failed Sources wait until that exact retry time, even when another Source wakes earlier; first-run failures also receive a retry without a prior PNG. Success clears retry state.
5. Not due → copy previous Frame + Sidecar unchanged.
6. Write `manifest.json`, `index.html` gallery.
7. Exit 3 if any Source has an unresolved runtime error (Site still written and deployed, then the job fails so GitHub notifies). The Chain still runs after a successful deployment, using the earliest `retry_at` or `next_due`; cancellation/deployment failure stop it. Config errors exit 2 before any output; crashes exit 1 and deploy nothing.

## Site layout

```
/manifest.json
/index.html                    Gallery: Previews grouped by Source, Freshness per Source, Chain heartbeat (overdue = next_due + 10 min)
/<source>/<panel>.png          Frame (indexed PNG, exactly N palette entries, Ink Order)
/<source>/<panel>.json         Sidecar
/<source>/<panel>.preview.png  Preview (RGB)
/<source>/<panel>.<enc>        Encoder output (.pcim, later .bin/.bmp/.jpg)
```

The Gallery is self-contained (inline style and script, no requests beyond Site-relative Previews and links); its 10 min grace is the only place the Overdue threshold is defined.

Manifest schema v3 entry: `source, panel, url, sha256, generated_at, next_due, encoders, error?, retry_at?`. Every `url` is Site-relative (devices join it with the base they fetched the Manifest from), so a mirror of the Site for networks where github.io is unreachable needs no rewriting. Devices use `If-None-Match` (Pages serves ETag) and may sleep until `retry_at` when present, otherwise `next_due`. A previous schema triggers full regeneration. Gallery Frame freshness uses original `next_due`; Chain heartbeat uses effective retry/due time.

## Panel

`id, width, height, palette (bw|bwr|bwry|spectra6), nominal[], measured[]?, encoders[]`. Palette is always a **prefix of Ink Order** `black, white, red, yellow, blue, green`. `nominal` is written into the PNG palette; `measured` (default = nominal) is the dither target. Presets catalog ships: 250×122, 296×128, 400×300, 648×480, 800×480 in their common palettes; 800×480 and 400×600 Spectra 6. Measured values: BW/BWR/BWRY = nominal (the EPD-nRF5 web tool dithers against pure colors too; measure a panel and set `measured` to improve); Spectra 6 white-balanced from epdoptimize (credited). Preset ids are `<w>x<h>-<palette>`.

Known trap: Pillow `quantize` palette image must hold exactly N entries; padding to 256 produces phantom indices.

## Source

```python
class Index(QuoteSource):
    sizes = [(800, 480), (400, 300)]           # compatibility by size, not panel id
    schedule = Schedule(every="5m", window=Window("09:30-15:00", "mon-fri"), fallback="6h")
    dither = "threshold"                        # UI default; photo sources use "floyd-steinberg" etc.
    requires_secrets = []
    timezone = "Asia/Shanghai"                  # Schedule/display zone unless config overrides
    params = {"symbols": ["sh000300"]}          # config keys + defaults; unknown keys rejected
    fields = ("price", "change")                # fetch result must hold these, non-empty
    async def fetch(self, ctx) -> dict: ...     # must raise on incomplete data
    def render(self, ctx, panel, data) -> str | Image: ...  # default: Jinja2 templates/<w>x<h>.html
```

Loading: built-in `sources/<name>/`, user `sources_dir/<name>/`. A Source may be template-only (no Python). Template context includes `panel.palette` so layouts can use red when available. Config selects Sources, picks Panels, overrides Schedule.

The catalog now includes anonymous GitHub identity/2D and isometric contribution walls, public CI, public Statuspage, air-quality forecasts, hourly weather, museum art and bilingual poetry. Parameters, upstream boundaries, provenance and sample instances: [Source notes](sources.md).

## Rendering

- Primary: HTML → Playwright Chromium headless shell (Linux runner). `scripts/setup-runner.sh` writes a fontconfig rule `antialias=false` + full hinting, and Chromium launches with `--font-render-hinting=none --disable-lcd-text`; macOS gets `-webkit-font-smoothing: none`. The E2E test asserts the raw render holds only the template's ink colors (no grey text edges) and runs in CI on the Linux runner.
- Secondary: Pillow drawing for pixel-exact small panels.
- Dither per Source: `threshold` (nearest measured color), `floyd-steinberg`, `atkinson`, `stucki`, `jjn`, `burkes`, `sierra`, `bayer4`, `bayer8`; serpentine + strength options; YCbCr-weighted distance. Photo Sources opt into `supersample = 2` (render at 2×, Lanczos downsample). Error diffusion keeps integer pixel values: incoming error is truncated toward zero before it is added, then clipped (Pillow's convention), so FS matches Pillow exactly where Pillow is exact. Pillow is *not* exact on colorful input (coarse nearest-color cache) nor at the right edge (it writes the blue channel's carried error into all three channels at each row end), so the golden test compares grey input on BW away from that edge.
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
symbols = ["sh000300"]     # Tencent codes: CSI 300 (sh000001 = SSE Composite); several = a Watchlist table
panels = ["p75-bwr"]
schedule = { every = "5m", window = { time = "09:30-15:00", days = "mon-fri" }, fallback = "6h" }
```

Default config enables `800x480-bwr`, `250x122-bwr`, `800x480-spectra6`. A source table key is the instance id (site path); `source = "index"` lets one Source appear twice (CSI 300 and SSE).

## MVP

1. `calendar` Source end-to-end (config → render → dither → Site → Pages) on the default repo.
2. `index` (CSI 300 / SSE) and `stock` (US equities) — data source below.
3. Encoder `pcim` only (hardware available; byte-level spec as test oracle).

Out of scope here: host-side device bridges (e.g. a BLE price-tag bridge consuming the indexed PNG with its own tool).

## Market data

Primary, both markets: Tencent `https://qt.gtimg.cn/q=<code>` (`sh000300`, `sh000001`, `usAAPL`). No key, no headers, GBK text `v_<code>="f0~f1~…";`. Fields: 1 name, 2 code, 3 last, 4 prev close, 30 time, 31 change, 32 change %, 33/34 high/low. Time is `YYYYMMDDHHMMSS` Asia/Shanghai for China, `YYYY-MM-DD HH:MM:SS` America/New_York for US. Unknown code → `v_pv_none_match="1";` (raises). Quotes older than `max_age_hours` (index 240 h spans Golden Week, stock 120 h) raise. Parsing is tested against captured responses in `tests/fixtures/quotes/`; reachability from runners is proven by the live Site's Runs.

Fallback (not implemented, switch here if Tencent blocks runners): Eastmoney `https://push2.eastmoney.com/api/qt/stock/get?secid=1.000300&fields=f43,f57,f58,f59,f60,f86,f169,f170` (JSON; prices × 10^f59, f170 = change % × 100, f86 = Unix time; US via `secid=105.AAPL`). Rejected: Yahoo (429 without browser UA, cloud IPs throttled), Sina (needs Referer), Stooq (endpoint gone).

## Testing

- Unit with external oracles: Schedule due table (tz, midnight, weekend, tolerance); PCIM bytes hand-computed; Ink Order / palette validation from spec; config samples.
- Dither: FS kernel vs Pillow's FS golden; other kernels on tiny hand-computed images.
- E2E (Playwright): template → browser → PNG has correct size and exactly N palette entries. No visual goldens (fonts differ across hosts).

## Operations

- Default workflow cron `2-59/5 * * * *` only resurrects the Chain; refresh cadence comes from the Chain.
- Users who want insurance against a dead Chain can add an external pinger (`gh workflow run inkage -R OWNER/REPO` from any cron with a PAT holding `actions: write`); a dispatch while a Run is in progress just replaces the waiter.
- License MIT. inkboard (GPLv3) and other prior projects are idea sources only; no code copied.
