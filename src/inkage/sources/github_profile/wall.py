"""Static calendar geometry; SVG keeps output independent of badge services."""

import math
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from inkage.panel import Panel
from inkage.sources.github_profile.calendar import Day


def wall_data(days: tuple[Day, ...], panel: Panel, layout: str) -> dict[str, Any]:
    compact = panel.width == 250
    isometric = layout == "isometric" and not compact
    origin = days[0].date - timedelta(days=(days[0].date.weekday() + 1) % 7)
    cells, months = [], []
    previous_month = None
    for day in days:
        week, weekday = divmod((day.date - origin).days, 7)
        if isometric:
            x, y = 10 + week * 12 + weekday * 8, 118 - week * 1.1 + weekday * 8
            height = 0 if not day.count else min(76, 4 + 8 * math.log2(1 + day.count))
            top = [(x, y - height), (x + 10, y - 1 - height), (x + 16, y + 5 - height), (x + 6, y + 6 - height)]
            sides = [
                [top[1], top[2], (x + 16, y + 5), (x + 10, y - 1)],
                [top[2], top[3], (x + 6, y + 6), (x + 16, y + 5)],
            ]
            cells.append(
                {
                    "level": day.level,
                    "date": day.date.isoformat(),
                    "count": day.count,
                    "depth": y,
                    "top": points(top),
                    "sides": [points(side) for side in sides],
                }
            )
        else:
            pitch, row_pitch = (8, 8) if compact else (13, 24)
            x, y = (0 if compact else 34) + week * pitch, (0 if compact else 27) + weekday * row_pitch
            cells.append({"level": day.level, "date": day.date.isoformat(), "count": day.count, "x": x, "y": y})
            if not compact and day.date.month != previous_month:
                # First/last fragments can share the same month; suppress a colliding label at the right edge.
                if week < 51:
                    if months and x - months[-1]["x"] < 39:
                        months.pop()
                    months.append({"x": x, "label": day.date.strftime("%b")})
                previous_month = day.date.month
    if isometric:
        cells.sort(key=lambda cell: cell["depth"])
    return {"cells": cells, "months": months, "isometric": isometric, "compact": compact}


def points(vertices: Sequence[tuple[float, float]]) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in vertices)
