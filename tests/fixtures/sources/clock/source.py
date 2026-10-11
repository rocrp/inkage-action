"""Fixture: draws the current minute as a bar, no browser. Every 5 minutes."""

from PIL import Image, ImageDraw

from inkage.schedule import Schedule
from inkage.source import Source


class Clock(Source):
    sizes = ((250, 122),)
    schedule = Schedule.parse({"every": "5m"})

    async def fetch(self, ctx):
        return {"minute": ctx.local_now.minute}

    def render(self, ctx, panel, data):
        img = Image.new("RGB", panel.size, "white")
        ImageDraw.Draw(img).rectangle((0, 0, data["minute"] * 4, 20), fill="black")
        return img
