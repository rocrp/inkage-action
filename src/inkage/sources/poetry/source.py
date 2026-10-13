"""Complete short public-domain poems; offline, with verifiable edition provenance.

``language = 'mixed'`` alternates English/Chinese daily. ``en`` and ``zh``
rotate within that language. Local calendar date determines selection, so
retries and every Panel show the same complete poem. No generated translations.
"""

import json
from pathlib import Path
from typing import Any

from inkage.schedule import Schedule
from inkage.source import Context, Source

POEMS = json.loads(Path(__file__).with_name("poems.json").read_text(encoding="utf-8"))


class Poetry(Source):
    schedule = Schedule.parse({"at": ["00:10"]})
    dither = "threshold"
    params = {"language": "mixed"}
    fields = ("title", "author", "lines", "language", "source", "edition", "source_label")

    async def fetch(self, ctx: Context) -> dict[str, Any]:
        language = ctx.params["language"]
        if language not in ("mixed", "en", "zh"):
            raise ValueError("poetry: language must be 'mixed', 'en', or 'zh'")
        poems = [p for p in POEMS if language == "mixed" or p["language"] == language]
        return dict(poems[ctx.local_now.date().toordinal() % len(poems)])
