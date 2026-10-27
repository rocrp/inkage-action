"""Gallery structure against a hand-built Manifest: one section and one Freshness line per Source."""

import asyncio
import re

from playwright.async_api import async_playwright

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


def test_retry_heartbeat_preserves_overdue_frame_timestamp():
    page = gallery_html(
        Manifest(
            RUN,
            [
                Entry(
                    "weather",
                    "800x480-bwr",
                    "weather/800x480-bwr.png",
                    "cc",
                    WX_GEN,
                    "2026-10-11T23:00:00Z",
                    "upstream down",
                    retry_at="2026-10-12T00:30:00Z",
                ),
            ],
        )
    )
    heartbeat = re.search(r'<p class="fresh heartbeat">.*?</p>', page)[0]
    assert re.findall(r'datetime="([^"]*)"', heartbeat) == [RUN, "2026-10-12T00:30:00Z"]
    freshness = re.search(r"<p class=fresh>.*?</p>", page)[0]
    assert re.findall(r'datetime="([^"]*)"', freshness) == [WX_GEN, "2026-10-11T23:00:00Z"]
    assert "next retry 2026-10-12T00:30:00Z" in page


def test_gallery_has_no_url_code_and_only_relative_refs():
    page = gallery_html(MANIFEST)
    assert "<code>" not in page
    refs = re.findall(r'(?:src|href)="([^"]*)"', page)
    assert refs and all("://" not in r for r in refs)


def test_copy_image_url_uses_canonical_png_and_site_base():
    async def verify():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content(
                    gallery_html(MANIFEST).replace("<head>", '<head><base href="https://example.org/inkage/">')
                )
                await page.evaluate("""() => Object.defineProperty(navigator, 'clipboard', {
                    value: {writeText: async text => {window.copied = text;}}
                })""")
                buttons = page.get_by_role("button", name="Copy image URL", exact=True)
                assert await buttons.count() == 2  # Failed first generation has no image to copy.
                await buttons.first.click()
                assert await page.evaluate("window.copied") == "https://example.org/inkage/calendar/800x480-bwr.png"
                assert await buttons.count() == 1
            finally:
                await browser.close()

    asyncio.run(verify())
