"""HTML -> RGB image via headless Chromium (Playwright). One browser per Renderer.

Text should be hard-edged before dithering: on Linux the action disables
fontconfig antialiasing; on macOS ``-webkit-font-smoothing: none`` does it.
Fonts from a consumer ``fonts/`` dir are injected as ``@font-face`` rules whose
family is the file stem.
"""

from __future__ import annotations

import io
import re
import tempfile
from pathlib import Path
from types import TracebackType

from PIL import Image
from playwright.async_api import Browser, Playwright, async_playwright

FONT_SUFFIXES = (".ttf", ".otf", ".woff", ".woff2")
_HEAD = re.compile(r"<head(\s[^>]*)?>", re.IGNORECASE)
_BASE_CSS = "html,body{margin:0;padding:0;overflow:hidden}*{-webkit-font-smoothing:none}"


def font_face_css(fonts_dir: Path | None) -> str:
    if fonts_dir is None:
        return ""
    if not fonts_dir.is_dir():
        raise ValueError(f"fonts dir {fonts_dir} does not exist")
    return "".join(
        f'@font-face{{font-family:"{p.stem}";src:url("{p.resolve().as_uri()}")}}'
        for p in sorted(fonts_dir.iterdir())
        if p.suffix.lower() in FONT_SUFFIXES
    )


def _inject_head(html: str, head: str) -> str:
    """Insert ``head`` right after ``<head>`` (keeping the doctype first), else prepend it."""
    if m := _HEAD.search(html):
        return html[: m.end()] + head + html[m.end() :]
    return head + html


class Renderer:
    def __init__(self, fonts_dir: Path | None = None) -> None:
        self._css = _BASE_CSS + font_face_css(fonts_dir)
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._tmp = tempfile.TemporaryDirectory(prefix="inkage-")

    async def __aenter__(self) -> Renderer:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self._tmp.cleanup()

    async def html_to_image(self, html: str, width: int, height: int, base_dir: Path, scale: int = 1) -> Image.Image:
        """Render at ``width``×``height`` CSS px × ``scale``; relative URLs resolve in ``base_dir``."""
        if self._browser is None:  # launched lazily: Runs with nothing to render never start Chromium
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(args=["--font-render-hinting=none", "--disable-lcd-text"])
        head = f'<base href="{base_dir.resolve().as_uri()}/"><style>{self._css}</style>'
        page_file = Path(self._tmp.name) / "page.html"
        page_file.write_text(_inject_head(html, head), encoding="utf-8")
        page = await self._browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=scale)
        try:
            await page.goto(page_file.as_uri(), wait_until="networkidle")
            await page.evaluate("document.fonts.ready")
            png = await page.screenshot(type="png", full_page=False)
        finally:
            await page.close()
        img = Image.open(io.BytesIO(png)).convert("RGB")
        if img.size != (width * scale, height * scale):
            raise RuntimeError(f"rendered {img.size}, expected {(width * scale, height * scale)}")
        return img
