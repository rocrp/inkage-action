"""Fixture: fetch fails when the config says so."""

from typing import Any, ClassVar

from PIL import Image

from inkage.schedule import Schedule
from inkage.source import Source


class Flaky(Source):
    sizes = ((250, 122),)
    schedule = Schedule.parse({"every": "5m"})
    params: ClassVar[dict[str, Any]] = {"fail": False}
    fields = ("value",)

    async def fetch(self, ctx):
        if ctx.params["fail"]:
            raise ConnectionError("upstream down")
        return {"value": ctx.local_now.minute}

    def render(self, ctx, panel, data):
        return Image.new("RGB", panel.size, (data["value"] * 4, 0, 0))
