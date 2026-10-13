# GitHub profile UI references

Research date: 2026-10-13. Scope: visual inspiration for Inkage; English-first labels, Chinese and English content; every new Source must work without a key or login. This report approves no implementation or additional metrics.

## Inspected references

| Reference | Observed visual hierarchy | Transfer to Inkage |
| --- | --- | --- |
| [GitHub Readme Stats](https://github.com/anuraghazra/github-readme-stats#github-stats-card) · [official live example](https://github-readme-stats.vercel.app/api?username=anuraghazra&show_icons=true) | Title above five aligned icon/label/value rows; large rank circle at right; thin border, white background, blue accents. | Borrow aligned labels and strong numeric column. Prefer 2–3 public, explainable values; the rank is the project's own calculation, not a GitHub-issued rating. |
| [GitHub Readme Streak Stats](https://github.com/DenverCoder1/github-readme-streak-stats) · [README's default preview](https://i.imgur.com/IaTuYdS.png) | Three columns: total contributions, current streak, longest streak. Current streak gets an orange circle/flame and stronger label; dates are secondary. | Borrow one dominant number with two supporting values. A streak requires a separately agreed definition and is not part of the approved first profile card. |
| [lowlighter Metrics](https://github.com/lowlighter/metrics) · [classic example](https://github.com/lowlighter/metrics/blob/1dac69e51ce95a1dc71e901ad4e5ad2968def9e5/metrics.classic.svg) | Avatar/name at upper left; joined/follower facts underneath; compact contribution strip at upper right; balanced two-column lists with icons. | Good identity + activity composition. Enlarge typography and remove dense secondary facts. Keep the calendar dominant instead of growing a dashboard of plugins. |
| [Metrics isocalendar](https://github.com/lowlighter/metrics/tree/master/source/plugins/isocalendar) · [full-year example](https://github.com/lowlighter/metrics/blob/1dac69e51ce95a1dc71e901ad4e5ad2968def9e5/metrics.plugin.isocalendar.fullyear.svg) | Narrow diagonal yearly plane with green extruded cells; title upper left, textual summary fills the opposite corner. | Useful economical 3D composition: contribution height becomes an additional cue. The diagonal consumes more space than a rectangular calendar. |
| [GitHub Profile 3D Contrib](https://github.com/yoshi389111/github-profile-3d-contrib) · [official GitBlock demo](https://raw.githubusercontent.com/yoshi389111/github-profile-3d-contrib/main/docs/demo/profile-gitblock.svg) | Long diagonal LEGO-like wall, radar upper right, language donut lower left, totals below. README also shows green, seasonal and night variants. | Borrow day footprints and extrusion; omit studs, radar and donut for 800×480 legibility. The official action requires `GITHUB_TOKEN`: visual reference only. |
| [Shields](https://shields.io/badges) · [flat-square build example](https://img.shields.io/badge/build-passing-brightgreen?style=flat-square) | Compact adjoining label/value blocks. Documented styles include flat, flat-square, plastic, for-the-badge and social. | Use the label/value grammar for CI or service status. Include status text and a shape/icon so meaning survives monochrome conversion. |

The GitHub Readme Stats README describes its rank as a weighted calculation over several statistics; importing the circle would imply a new metric and explanation. Streak Stats documents daily and weekly modes, date ranges and exclusions. These are design references, not permission to add their calculations. [Rank documentation](https://github.com/anuraghazra/github-readme-stats#github-stats-card), [streak options and definitions](https://github.com/DenverCoder1/github-readme-streak-stats#how-these-stats-are-calculated).

## 3D product status

The [GitHub Skyline website](https://skyline.github.com/) currently shows a “lights out” page pointing to [github/gh-skyline](https://github.com/github/gh-skyline), a CLI that generates an STL contribution skyline. Treat Skyline as a visual/physical precedent; do not present the currently unavailable website as a working online embed or infer permanent retirement. Site observed directly during this research; CLI was not run.

## Proposed layouts — pending design decision

- **800×480 profile, default:** identity header with avatar, username and short bio; 2–3 clear values; full-year rectangular calendar occupying the largest remaining area. Label the visible date range and contribution total. This fits the approved identity + contribution-wall scope.
- **800×480 isometric, optional:** same identity and limited metrics; large diagonal calendar, restrained extrusion, flat top/side faces. Keep date direction and legend visible. Borrow the spacious Metrics composition and the GitBlock height cue; avoid miniature ancillary charts.
- **250×122:** dedicated compact layout: username, one primary total and roughly 13 weeks of 2D cells. Never scale the entire desktop card down. A 53-column year within a ~230 px plot allows only ~4 px column pitch before labels; it cannot carry the same detail as the large panel. Specify recent-period total separately if shown beside an annual total.
- **CI/service status:** separate status Source; large readable label + explicit value, with freshness/observation time. Shields supplies visual grammar, not the upstream data dependency.

These are layout proposals, not a proposal to fetch third-party badge images. Inkage should fetch the accepted public GitHub data and render its own templates. References requiring authentication do not relax the no-key/no-login requirement.

## E-paper adaptation — design inference, not hardware verification

| Palette | Candidate treatment | Limit |
| --- | --- | --- |
| BW | White background, black text; calendar levels via consistent ordered fill density/geometry; extrusions use solid faces and sparse hatching. | Gray/green screenshots cannot simply become black: levels merge. Assess pattern noise at actual size. |
| BWR | Black for all core text/structure; red reserved for one emphasis or highest activity band. | Red alone cannot encode five ordered activity levels. Preserve intensity with additional fill/shape cues. |
| Spectra6 | Deliberate palette assignments for flat faces, plus height or density as the ordered cue. | Different hues are not inherently ordered. Avoid assuming GitHub's green ramp survives palette quantization. |

All palettes need explicit date range, timezone/cutoff semantics and readable labels. Preserve upstream metric names: contributions must not be relabeled commits, and annual totals must not be described as recent-period totals. Isometric height needs a documented mapping and cap; otherwise one unusually active day can dominate the wall or obscure other days. Exact pixel sizes, hatch patterns and cap remain unverified until rendered through Inkage and inspected at native size.

## Evidence and boundaries

- Read upstream READMEs/docs through `localwebrs`; GitHub Readme Stats README retrieved from its first-party raw URL after the page fetch stalled. No implementation code was copied or adopted.
- Visually inspected official Stats, Streak, Metrics classic, Metrics full-year isocalendar, GitBlock and Shields examples. Metrics example files pinned above to examples-branch SHA `1dac69e51ce95a1dc71e901ad4e5ad2968def9e5` (example commit dated 2025-07-03); their displayed numbers are sample content, not current user data.
- Local screenshot cache: `/tmp/inkage-ui-references/readme-stats-browser.png`, `streak-default.png`, `metrics-classic-browser.png`, `isocalendar-browser.png`, `shields-build.png`. Temporary inspection evidence, not repository assets; upstream links remain the reproducible reference.
- Rendering caveat actually observed: Metrics SVGs use HTML `foreignObject`; `rsvg-convert` produced blank output while Chromium rendered their content. Stats entry animations hid numeric rows in an immediate rasterization; Chromium after animation completion showed them. Own static templates avoid inheriting either dependency. This is a reference-asset observation, not evidence that Inkage's current renderer fails.
- No hardware display verification, new Source implementation, anonymous-data reliability claim, or third-party service uptime assessment performed in this UI research.
