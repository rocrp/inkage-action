"""Gallery structure against a hand-built Manifest: one section and one Freshness line per Source."""

import re

from inkage.gallery import gallery_html
from inkage.site import Entry, Manifest

CAL_GEN, CAL_DUE = "2026-10-12T00:00:00Z", "2026-10-12T01:00:00Z"
WX_GEN = "2026-10-11T22:00:00Z"
RUN = "2026-10-12T00:05:00Z"

MANIFEST = Manifest(
    generated_at=RUN,
    frames=[
        Entry("calendar", "800x480-bwr", "calendar/800x480-bwr.png", "aa", CAL_GEN, CAL_DUE, None, {"pcim": {}}),
        Entry("calendar", "400x300-bw", "calendar/400x300-bw.png", "bb", CAL_GEN, CAL_DUE),
        Entry("weather", "800x480-bwr", "weather/800x480-bwr.png", None, WX_GEN, None, "upstream down"),
    ],
)


def test_gallery_groups_by_source_with_one_freshness_line_each():
    page = gallery_html(MANIFEST)
    sections = re.findall(r"<section>.*?</section>", page)
    assert [re.search(r"<h2>(.*?)</h2>", s)[1] for s in sections] == ["calendar", "weather"]
    assert [s.count("<p class=fresh>") for s in sections] == [1, 1]
    cal, wx = sections
    assert re.findall(r'datetime="([^"]*)"', cal) == [CAL_GEN, CAL_DUE]
    assert re.findall(r'datetime="([^"]*)"', wx) == [WX_GEN]  # next_due None: no <time>
    assert '<a href="calendar/800x480-bwr.png">800x480-bwr</a> · <a href="calendar/800x480-bwr.pcim">pcim</a>' in cal
    assert "<p class=error>error: upstream down</p>" in wx and "no frame yet" in wx
    assert "error" not in cal


def test_heartbeat_points_at_earliest_next_due():
    page = gallery_html(MANIFEST)
    heartbeat = re.search(r'<p class="fresh heartbeat">.*?</p>', page)[0]
    assert re.findall(r'datetime="([^"]*)"', heartbeat) == [RUN, CAL_DUE]
    assert "next Run" in heartbeat


def test_heartbeat_without_any_next_due():
    only_failed = Manifest(generated_at=RUN, frames=MANIFEST.frames[2:])
    assert "no Run scheduled" in gallery_html(only_failed)


def test_gallery_has_no_url_code_and_only_relative_refs():
    page = gallery_html(MANIFEST)
    assert "<code>" not in page
    refs = re.findall(r'(?:src|href)="([^"]*)"', page)
    assert refs and all("://" not in r for r in refs)
