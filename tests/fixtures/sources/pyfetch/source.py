"""Fixture: Python Source with a custom fetch feeding the default template render."""

from typing import Any, ClassVar

from inkage.schedule import Schedule
from inkage.source import Source


class PyFetch(Source):
    schedule = Schedule.parse({"every": "1h"})
    params: ClassVar[dict[str, Any]] = {"bars": 3}
    fields = ("bars",)

    async def fetch(self, ctx):
        return {"bars": list(range(ctx.params["bars"]))}
