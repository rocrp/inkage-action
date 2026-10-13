# Typography acceptance inputs

`samples.json`: frozen source output used in the accepted local font gallery,
2026-10-13. Provenance stored per sample. Includes calendar, daily/hourly weather,
three-coin crypto, synthetic Chinese news headlines and complete bilingual poems.
News headlines test layout only; not factual reports.

`test_typography.py` supplements these with existing captured provider fixtures,
offline astronomy/countdown/calendar, all six bundled poems, both quote modes,
and both GitHub contribution layouts. Six-coin stress input copies captured
BTC/ETH/SOL price fields into three explicitly synthetic additional rows, solely
to exercise maximum row count. Art uses captured museum metadata with an existing
offline avatar image; only caption typography is checked.

54 browser cases share one Chromium process. Independent acceptance constraints:
bundled custom font actually used, each displayed glyph in its selected font,
font size an integer multiple of native grid (10/11/12/16 px), no synthetic bold,
no unintended text outside panel or hidden clipping, complete poem lines retained.
Declared CSS ellipsis and line-clamp are intentional truncation. Photo has no HTML
text template and remains covered by its existing image tests.
