"""Prove packaged fonts load in Chromium without system font fallback."""

import asyncio
from pathlib import Path

import pytest

import inkage.fonts
from inkage.render import Renderer


def test_missing_bundled_font_fails_before_browser_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(inkage.fonts, "FONT_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="bundled font missing:.*reinstall inkage"):
        Renderer()


def test_renderer_uses_bundled_fonts_without_implicit_fallback(tmp_path):
    # PostScript names come from the selected upstream artifacts, independently
    # of the registration code. Mixed CJK/Latin tests load and glyph coverage.
    cases = [
        ("Fusion Pixel 12", 12, "墨水屏 中文鬱 2026", "Fusion-Pixel-12px-Prop-zh-Hans-Regular"),
        ("Fusion Pixel 10", 10, "上海 气温更新 13:30", "Fusion-Pixel-10px-Prop-zh-Hans-Regular"),
        ("Unifont", 16, "静夜思 明月光 123", "Unifont"),
        ("Departure Mono", 22, "$42,750.00 -1.23% BTC", "DepartureMono-Regular"),
    ]

    async def verify():
        async with Renderer() as renderer:
            html = (
                "<html><head></head><body>"
                + "".join(
                    f'<p id="sample{i}" style="font: {size}px \'{family}\'">{text}</p>'
                    for i, (family, size, text, _) in enumerate(cases)
                )
                + '<p id="consumer" style="font: 12px serif">Custom typography</p></body></html>'
            )
            await renderer.html_to_image(html=html, width=500, height=200, base_dir=tmp_path)
            # Reopen the exact file produced by Renderer, with its font rules.
            assert renderer._browser is not None
            page = await renderer._browser.new_page()
            try:
                await page.goto((Path(renderer._tmp.name) / "page.html").as_uri())
                await page.evaluate("document.fonts.ready")
                cdp = await page.context.new_cdp_session(page)
                await cdp.send("DOM.enable")
                await cdp.send("CSS.enable")
                root = (await cdp.send("DOM.getDocument"))["root"]["nodeId"]
                for i, (_, _, _, expected) in enumerate(cases):
                    node = await cdp.send("DOM.querySelector", {"nodeId": root, "selector": f"#sample{i}"})
                    fonts = (await cdp.send("CSS.getPlatformFontsForNode", {"nodeId": node["nodeId"]}))["fonts"]
                    assert {(font["postScriptName"], font["isCustomFont"]) for font in fonts} == {(expected, True)}
                assert await page.locator("#consumer").evaluate("e => getComputedStyle(e).fontFamily") == "serif"
            finally:
                await page.close()

    asyncio.run(verify())
