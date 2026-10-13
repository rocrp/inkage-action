# Source notes

New Sources require no account, API key or login. Interface labels are English-first; original Chinese/English content is retained. Built-in demo configuration: [`../inkage.toml`](../inkage.toml). Every new Source supports 800×480 and 250×122 in BW, BWR and other compatible palettes.

## GitHub identity and contribution wall

```toml
[sources.profile]
source = "github_profile"
username = "RoCry"
layout = "profile" # or "isometric"
panels = ["800x480-bwr", "250x122-bw"]
```

- Profile: avatar, name, bio, public repository count, followers, annual contribution calendar and exact date range. Isometric: same identity and metrics, with a large extruded calendar. Visual research: [references](research/github-profile-ui-references.md).
- Small panel: dedicated compact 2D view of the latest 13 calendar-week columns, regardless of layout; recent and annual totals labeled separately. Never scales the entire large layout down.
- Data: anonymous [public user REST endpoint](https://docs.github.com/en/rest/users/users#get-a-user), official [contributions HTML](https://github.com/users/RoCry/contributions), official avatar. No third-party badge rendering service or token dependency.
- Contributions are GitHub's contributions, **not commits**; visible counts can include anonymized private contributions when enabled by the account. Date range/cutoff comes from GitHub, not the configured display timezone. [GitHub's contribution rules](https://docs.github.com/en/account-and-profile/reference/profile-contributions-reference).
- Parser checks complete daily coverage, associated tooltip counts and agreement with the published total. HTML structure changes fail explicitly and preserve the previous Frame. This is an observed website interface, not a versioned public API.
- 2D activity uses upstream relative levels with patterned fills. 3D height is zero for zero contributions; otherwise `min(76, 4 + 8*log2(1+count))` pixels. Log scaling limits visual domination by unusually active days. Date order/legend remain visible; color is not the only cue.
- Default refresh: 6 h. GitHub anonymous REST limits are [60 requests/hour per IP](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api); shared runner IP availability still needs deployment observation.

## Work status

- `github_ci`: anonymous [workflow runs](https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-repository). `repo="owner/name"`, `branch=""` for all branches, `count=5` (1–5). Shows latest runs, including repeated runs of the same workflow; not a synthesized repository health score. Small panel shows latest run. Empty history is valid; incomplete outcomes fail. Default 15 min.
- `status`: public Statuspage `url` + `/api/v2/summary.json`, e.g. [GitHub Status](https://www.githubstatus.com/api). Optional `label`; default uses provider page name. Keeps provider's whole-page rollup, prioritizes affected components, displays unresolved incident count/title. Large panel lists up to 12 visible components, small panel shows rollup and incident summary. Explicit check time; an old last-change timestamp does not imply a stale fetch. Default 15 min.

## Weather and air quality

- `weather.layout="daily"` remains default. `layout="hourly"` shows next six hourly intervals on 800×480, next three on 250×122. Temperature is at the interval end; probability and precipitation amount apply to the preceding hour. Both layouts accept existing location/units parameters. [Open-Meteo forecast API](https://open-meteo.com/en/docs).
- `air_quality`: location parameters `latitude`, `longitude`, `label`; default Shanghai. **U.S. AQI**, PM2.5/PM10 in μg/m³, next 12 hours (large) or six (small). Explicitly a CAMS/Open-Meteo model forecast, not a local station observation or Chinese AQI. Local forecast time comes from the API; invalid/stale current values or incomplete hourly columns fail. [Air-quality API and attribution](https://open-meteo.com/en/docs/air-quality-api). Default 1 h.

## Reading and art

- `news` already accepts RSS/Atom URLs. Demo adds [少数派 RSS](https://sspai.com/feed) beside English Hacker News; additional feeds use additional instances, not new adapters.
- `poetry.language`: `en`, `zh`, or default `mixed`. Six complete short public-domain poems: three English, three Chinese; local-date rotation, mixed alternates languages. Same-day retries and panels select the same poem. Text stays in its original language, without generated translations. This is a small offline collection, not an unlimited online feed; [corpus and edition links](../src/inkage/sources/poetry/poems.json) record every source. Daily 00:10.
- `art`: [Met Open Access API](https://metmuseum.github.io/), four curated public-domain works rotated by local date. Set `artwork_id` to a positive Met object ID to pin a work; `0` selects daily rotation. Each fetch verifies `isPublicDomain`, title/artist/date and museum image. Full artwork contained within a mat, with caption and museum credit; Atkinson dithering. Daily 00:10.
- Art Institute Chicago was researched first, but its documented image host returned a Cloudflare challenge during live verification. The working Met API/image path replaced it; no challenge-solving dependency. Met requests identify the client with a descriptive User-Agent.

## Failure scheduling

An upstream failure keeps its old PNG and original `generated_at`/`next_due` (freshness), while `retry_at` schedules the next attempt. Waiting errors remain visible; another Source's earlier wake does not retry the failed Source prematurely. First-run failures also receive a retry time despite having no prior image. Success clears both error and retry time. The Chain uses the earliest effective retry/due time and continues only after a successful deployment, even if the completed workflow reports Source errors.

Local API success and rendered previews establish the implementation path, not ongoing GitHub runner reachability or physical-panel appearance. Renderer/palette checks and native-size visual inspection precede device acceptance.
