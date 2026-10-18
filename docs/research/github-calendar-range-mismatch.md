# GitHub contribution-calendar range mismatch

Research date: 2026-10-18. Scope: identify upstream behavior versus Inkage parser assumptions; no runtime changes.

## Finding

GitHub's anonymous contribution HTML currently gives different ranges for summary metadata and rendered day cells. Inkage assumes exact equality and aborts. The upstream mismatch is directly reproducible across accounts; the local fatal equality assumption is demonstrably unsuitable for this response. No primary source found confirms this precise leading-week mismatch as an acknowledged GitHub bug.

## Live evidence

Live anonymous requests fetched the public endpoints independently on 2026-10-18:

| Account / source | `data-from`–`data-to` | Day-cell dates / count | Heading total | Cell sum | Difference |
| --- | --- | --- | ---: | ---: | ---: |
| [RoCry](https://github.com/users/RoCry/contributions) | 2025-10-12–2026-10-18 | 2025-10-19–2026-10-18 / 365 | 24,382 | 24,327 | 55 |
| [torvalds](https://github.com/users/torvalds/contributions) | 2025-10-12–2026-10-18 | 2025-10-19–2026-10-18 / 365 | 3,769 | 3,731 | 38 |
| [octocat](https://github.com/users/octocat/contributions) | 2025-10-12–2026-10-18 | 2025-10-19–2026-10-18 / 365 | 0 | 0 | 0 |

RoCry totals advanced by two during investigation; earlier capture was 24,380 versus 24,325, retaining the same difference of 55. These links are live, so future responses will differ.

Committed 2026-10-13 RoCry fixture contained 367 contiguous dates and matched its heading. Its Oct 12–18 daily counts are `4, 18, 2, 9, 8, 12, 2`, summing to exactly **55**. This supports the inference that today's heading still includes the preceding week while the visible grid has advanced. The grid contains 53 calendar columns after the Sunday rollover; independent summary/grid window calculations are a plausible mechanism, not confirmed GitHub implementation details.

Local failure: `src/inkage/sources/github_profile/calendar.py` requires every date between HTML metadata bounds and then requires cell sum to equal heading total. Those are Inkage assumptions; the current response violates both. This is HTML scraping, not an API schema validation failure.

## Primary-source research

1. [GitHub Community incident #203416](https://github.com/orgs/community/discussions/203416), opened 2026-07-29 by `ebndev`, explicitly labeled Community Manager updates, acknowledges profile rendering reports including signed-in versus signed-out differences and inaccurate contribution graphs. August 17/27 updates give no fix ETA; September 23 update specifically discusses delayed achievements. **Related acknowledged incident only:** neither the post nor inspected comments identifies a missing leading calendar week or confirms our exact case.
2. [GitHub profile contributions reference](https://docs.github.com/en/account-and-profile/reference/profile-contributions-reference) documents eligibility, visibility and date attribution. It does not specify an HTML `data-from`/`data-to` contract, fixed grid length, or equality between a page heading and visible cell sum. Its eligibility explanations do not explain why one response's metadata range and cell dates differ by a complete week.
3. [Official GraphQL `ContributionCalendar`](https://docs.github.com/en/graphql/reference/users#object-contributioncalendar) defines `totalContributions` as total contributions in that calendar and `weeks` as its contribution weeks. [`ContributionCalendarWeek`](https://docs.github.com/en/graphql/reference/users#object-contributioncalendarweek) exposes `contributionDays`; [`ContributionCalendarDay`](https://docs.github.com/en/graphql/reference/users#object-contributioncalendarday) exposes each `date`, `contributionCount` and `weekday`. This is a documented data model, unlike the scraped HTML attributes. This research did not compare a live GraphQL response; the schema alone cannot prove whether GraphQL reproduces the current HTML mismatch.

Searches used English queries through `localwebrs`, then GitHub issue/discussion search via `gh` API for `contribution calendar`, `first week`, `missing week`, `data-from`, `sum`, `total`, `mismatch`, and Sunday rollover. No exact matching acknowledged upstream report found. Search absence is not proof that none exists.

## Attribution and repair boundary

- **Confirmed upstream behavior:** raw GitHub HTML exposes different summary and day-cell ranges across multiple accounts, before Inkage parses it.
- **Confirmed local problem:** treating metadata range, heading total and visible grid as one invariant makes a usable continuous grid fatal.
- **Unconfirmed:** whether GitHub considers this a bug, a transient cache/window issue, or intended presentation behavior; whether incident #203416 shares its cause.
- **Repair direction:** keep summary range/total separate from visible-day range/sum; retain date continuity, duplicate detection, tooltip/date matching and current-cutoff checks. Do not synthesize the missing week's counts or claim the heading total is the visible-grid total. A GraphQL migration would be a separate dependency/authentication decision, given this project's anonymous-source requirement.
