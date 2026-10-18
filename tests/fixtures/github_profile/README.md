# GitHub profile captures

Anonymous HTTPS captures, 2026-10-13 UTC; no Authorization header, cookies or token.

- `user.json`: `https://api.github.com/users/RoCry`, Accept `application/vnd.github+json`.
- `contributions.html`: `https://github.com/users/RoCry/contributions`, Accept `text/html`, Accept-Language `en`.
- `avatar.jpg`: URL in `user.json`, `https://avatars.githubusercontent.com/u/1117026?v=4`; original JPEG bytes.

Hand-read oracles: profile login/name RoCry, 78 public repos, 305 followers, null bio.
Calendar heading 21,840 contributions in last year; data-from 2025-10-12 UTC,
data-to 2026-10-13 UTC. First tooltip 4 contributions on October 12th (level 1).
2026-10-11: 338 (level 4); 2026-10-12: 1225 (level 4); 2026-10-13: 459 (level 4).
2026-08-23: No contributions (level 0). Calendar is Sunday-first and DOM cells
are grouped by weekday, not chronological order. Inclusive range 367 days.
Published counts may include anonymized private contributions; they are not commit counts.

## Sunday rollover capture

`contributions-sunday.html`: anonymous response from the same contributions endpoint,
2026-10-18 10:14 UTC, Accept `text/html`, Accept-Language `en`; HTML with trailing line whitespace removed.
Heading 24,380; metadata 2025-10-12–2026-10-18. Visible grid contains 365 days,
2025-10-19–2026-10-18, totaling 24,325. First day: 3 (level 1); last: 157 (level 1).
The original Oct 13 fixture's Oct 12–18, 2025 counts are 4, 18, 2, 9, 8, 12, 2:
55 in total, exactly the summary/grid difference. This captured failure, not
the parser's formula, is the rollover oracle. See the [research note](../../../docs/research/github-calendar-range-mismatch.md).

SHA256 `contributions-sunday.html`:
`c767282c885335c6b8e055daf8e59e0fc2752bab4301b237377ed105104e3081`.

SHA256:

```
b53c2b29a5b72edab7cc313bceffa93a4ea49bb9f0585f8d8b933fc22eaed77e avatar.jpg
b6d26fa33ccb7734f8f30e2f589d7b652518b9185c42ba598e64db7947adf373 contributions.html
5606f8ad6604b08ff440f60f517fc1c3d603550a42fabab46d00530aa6bdbf6f user.json
```
