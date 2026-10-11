"""Fixture: a fixed pattern, regenerated daily at 00:05."""

from PIL import Image, ImageDraw

from inkage.schedule import Schedule
from inkage.source import Source


class Daily(Source):
    sizes = ((250, 122),)
    schedule = Schedule.parse({"at": ["00:05"]})

    def render(self, ctx, panel, data):
        img = Image.new("RGB", panel.size, "white")
        ImageDraw.Draw(img).ellipse((10, 10, 110, 110), fill="red")
        return img
