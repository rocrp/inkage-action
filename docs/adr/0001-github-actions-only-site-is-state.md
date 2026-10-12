# Run only on GitHub Actions; the published Site is the only state

> Partly superseded by [ADR 0003](0003-self-dispatch-chain.md): the cron is no longer the refresh trigger. Everything about statelessness and the Site as state still holds.

We want zero servers: every fork gets a working pipeline for free on a public repo. GitHub Actions runners are stateless and `schedule` cannot fire more often than every 5 minutes, with top-of-hour jitter and auto-disable after 60 days of inactivity. We accept these limits instead of adding an external scheduler or a server: a single workflow ticks every 5 minutes (phased off the hour), fetches the previous Manifest from the live GitHub Pages Site to learn each Frame's last generation time, regenerates only due Frames, carries the rest over, and redeploys the full Site. A keepalive step re-enables the schedule via API.

## Considered options

- **Server-side rendering with device polling** (inkboard, TRMNL): per-request freshness, but needs hosting; rejected as the whole point is no-ops.
- **Long-running job looping inside one run** (up to 6 h) to publish every minute: fragile boundaries, deploy storm, still subject to queueing; rejected.
- **External cron hitting `repository_dispatch`**: breaks "only GitHub"; rejected.
- **State in `actions/cache` or committed files**: cache is evictable, commits are noise; the Manifest already has to exist for devices, so it doubles as state.

## Consequences

- Minimum refresh is 5 minutes nominal, 10–30 minutes under load; `next_due` is a hint, never a promise.
- Stale CDN copies of the Manifest can cause one extra or one delayed regeneration; harmless.
- A Run must download the previous Site's Frames to carry them over (full-snapshot deploy).
