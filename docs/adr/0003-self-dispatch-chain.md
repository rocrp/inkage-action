# Each Run dispatches the next; cron only resurrects the Chain

ADR 0001 accepted GitHub's `schedule` jitter as "5–30 minutes under load". Measured on this repo (2026-10-11/12) the cron `2-59/5 * * * *` fired 3 times in 11 hours: GitHub drops most ticks, not just delays them, and community reports say this has been the norm since late August 2026. A 5-minute stock Frame refreshed once per trading morning. A Schedule that cannot be honoured within hours makes the product pointless for anything but daily content.

We keep "GitHub only, no server" and replace the trigger: after deploying, a Run's `chain` job sleeps until the Site's earliest `next_due` (minus setup lead, capped at 5 h 50 min by the 6 h job limit) and then dispatches the calling workflow with `gh workflow run`. `workflow_dispatch` is one of the two events that a `GITHUB_TOKEN`-initiated action may create, so no PAT is needed; dispatches are API calls and are not dropped. The cron stays only to restart the Chain after a broken link (runner killed, GitHub incident). The `chain` job has its own concurrency group with `cancel-in-progress: true`, so a push, a cron tick or a manual dispatch replaces the sleeping waiter instead of queueing behind it for hours; the `publish` job keeps `cancel-in-progress: false` so a deploy is never cut short.

## Considered options

- **Keep cron, document reality**: honest but useless for intraday data; rejected.
- **External pinger** (home server, cron-job.org, Cloudflare Worker hitting `workflow_dispatch` with a PAT): reliable, but every user needs a second system and a secret; kept as an optional hardening in the README, not the default.
- **One long job looping fetch → render → deploy inside itself**: the "long-running loop" ADR 0001 rejected. Each Pages deploy inside one job needs a fresh artifact and the run's logs/summary become one 6-hour blob; the Chain gets the same compute shape with one Run per Frame generation, normal per-Run logs, and a natural restart point.
- **Shorter sleeps (e.g. ≤ 55 min) to detect a dead Chain sooner**: a dead Chain is dead regardless of how long it intended to sleep; more Runs just redeploy an unchanged Site. Rejected.

## Consequences

- A public repo has one job running (mostly sleeping) at all times: about 43 k Actions minutes a month, free on public repos, ruinous on private ones. `chain: false` turns it off; the README says so.
- Cadence is bounded by Run overhead (~1 min), not by cron: `every = "1m"` is accepted, so the README warns about e-paper refresh wear and deploy count instead.
- `next_due` becomes a real promise within about a minute, except after a broken link, where the cron's hours-late tick is the recovery time.
- Terms of service risk: a perpetually sleeping job may be read as idle compute. The sleep is bounded by the project's own Schedules and every Run publishes the project's output, which is what Actions is for; if GitHub objects, the fallback is the external pinger.
- Supersedes the "accept cron limits" part of ADR 0001; the rest of 0001 (Site as the only state, full-snapshot deploy) stands.
