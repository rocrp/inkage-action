"""The Gallery: Site's human-facing page. Previews grouped by Source, Freshness per Source, Chain heartbeat."""

from __future__ import annotations

from html import escape

from inkage.site import MANIFEST, Entry, Manifest, encoder_path, frame_path, preview_path, sidecar_path

# Rewrites every <time datetime> to relative text with a local-time title; marks Overdue (next_due + 10 min).
# The 10 min grace is defined here and nowhere else. No requests, no external resources.
SCRIPT = """<script>
const now = Date.now(), GRACE = 10 * 60e3;
const span = (s) =>
  s < 3600 ? `${Math.floor(s / 60)} min` : s < 172800 ? `${Math.floor(s / 3600)} h` : `${Math.floor(s / 86400)} d`;
for (const t of document.querySelectorAll("time[datetime]")) {
  const at = Date.parse(t.dateTime), s = Math.abs(at - now) / 1000;
  const label = t.textContent.slice(0, -t.dateTime.length).trim(), next = label.startsWith("next");
  t.title = new Date(at).toLocaleString();
  if (at > now) t.textContent = `${label} ${s < 60 ? "in a moment" : "in " + span(s)}`;
  else t.textContent = `${next ? (label.slice(4) + " due").trim() : label} ${s < 60 ? "just now" : span(s) + " ago"}`;
  if (next && now > at + GRACE) {
    const p = t.closest("p");
    p.classList.add("overdue");
    if (p.classList.contains("heartbeat")) t.after(" · chain broken, cron will recover");
  }
}
</script>"""

STYLE = """<style>
:root{color-scheme:light dark;--bg:#f6f6f4;--fg:#1d1d1b;--card:#fff;--muted:#6b6b66;--err:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#1b1b1a;--fg:#ececea;--card:#262624;--muted:#a3a39e;--err:#f2b8b5}}
body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif}
section{margin-bottom:24px} h2{font-size:16px;margin:0 0 4px}
.fresh,.retry{margin:0 0 8px;color:var(--muted)} .overdue{color:var(--err);font-weight:600}
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(min(100%,360px),1fr))}
figure{margin:0;padding:12px;background:var(--card);border-radius:8px}
img{max-width:100%;border:1px solid var(--muted)}
figcaption{margin-top:8px;color:var(--muted);word-break:break-all} figcaption a:first-child{color:var(--fg)}
.error{color:var(--err);margin:0 0 8px} .missing{padding:32px;text-align:center;border:1px dashed var(--muted)}
</style>"""


def _time(iso: str | None, label: str) -> str:
    return "—" if iso is None else f'<time datetime="{escape(iso)}">{label} {escape(iso)}</time>'


def _link(path: str, text: str) -> str:
    return f'<a href="{escape(path)}">{escape(text)}</a>'


def _card(e: Entry) -> str:
    img = (
        f'<img src="{escape(preview_path(e.source, e.panel))}" alt="">'
        if e.sha256
        else "<div class=missing>no frame yet</div>"
    )
    links = [_link(frame_path(e.source, e.panel), e.panel)]
    links += [_link(encoder_path(e.source, e.panel, name), name) for name in e.encoders]
    links.append(_link(sidecar_path(e.source, e.panel), "json"))
    return f"<figure>{img}<figcaption>{' · '.join(links)}</figcaption></figure>"


def _errors(entries: list[Entry]) -> str:
    failed = [e for e in entries if e.error]
    if len({e.error for e in failed}) == 1:
        return f"<p class=error>error: {escape(failed[0].error or '')}</p>"
    return "".join(f"<p class=error>{escape(e.panel)}: {escape(e.error or '')}</p>" for e in failed)


def _section(source: str, entries: list[Entry]) -> str:
    # All Panels of one Source share one Run's times, so the first entry speaks for the Source.
    head = entries[0]
    fresh = f"{_time(head.generated_at, 'generated')} · {_time(head.next_due, 'next')}"
    retries = [e.retry_at for e in entries if e.retry_at]
    retry = f"<p class=retry>{_time(min(retries), 'next retry')}</p>" if retries else ""
    cards = "".join(_card(e) for e in entries)
    return (
        f"<section><h2>{escape(source)}</h2><p class=fresh>{fresh}</p>{_errors(entries)}{retry}"
        f"<div class=grid>{cards}</div></section>"
    )


def gallery_html(manifest: Manifest) -> str:
    """Self-contained Gallery: only Site-relative requests, inline style and script."""
    by_source: dict[str, list[Entry]] = {}
    for e in manifest.frames:
        by_source.setdefault(e.source, []).append(e)
    # Same effective wake time as scripts/action-run.sh; Frame freshness remains independent.
    dues = [wake for e in manifest.frames if (wake := e.retry_at or e.next_due)]
    next_run = _time(min(dues), "next Run") if dues else "no Run scheduled"
    heartbeat = (
        f'<p class="fresh heartbeat">{_time(manifest.generated_at, "Run")} · {next_run} · '
        f'<a href="{MANIFEST}">manifest.json</a></p>'
    )
    sections = "".join(_section(source, entries) for source, entries in by_source.items())
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Inkage Frames</title>
{STYLE}</head><body>
<h1>Inkage Frames</h1>{heartbeat}
<main>{sections}</main>
{SCRIPT}
</body></html>
"""
