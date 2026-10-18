"""Anonymous public GitHub identity + official contributions, without token use.

Calendar ranges/cutoffs belong to GitHub (UTC); private contributions may be
included anonymously when the user exposes them. Activity levels are GitHub's
relative bands. Isometric height uses exact count: 0 for zero, otherwise
4 + 8*log2(1+count) px, capped at 76 px. The 250×122 panel always shows 13
recent calendar columns in 2D, regardless of layout. Six-hour refresh.
"""

import asyncio
import base64
import io
import re
from datetime import UTC, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from inkage.panel import Panel
from inkage.schedule import Schedule
from inkage.source import Context, Source
from inkage.sources.github_profile.calendar import CalendarError, parse_calendar
from inkage.sources.github_profile.wall import wall_data


def avatar_data(raw: bytes) -> str:
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            avatar = ImageOps.fit(image.convert("RGB"), (112, 112), Image.Resampling.LANCZOS)
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ValueError(f"github_profile: invalid avatar image ({error})") from error
    output = io.BytesIO()
    avatar.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def profile_data(raw: Any, username: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or not isinstance(raw.get("login"), str) or raw["login"].lower() != username.lower():
        raise ValueError("github_profile: missing or mismatched public profile login")
    for field in ("public_repos", "followers"):
        if type(raw.get(field)) is not int or raw[field] < 0:
            raise ValueError(f"github_profile: missing or invalid public profile {field}")
    avatar = raw.get("avatar_url")
    if (
        not isinstance(avatar, str)
        or urlparse(avatar).scheme != "https"
        or urlparse(avatar).hostname != "avatars.githubusercontent.com"
    ):
        raise ValueError("github_profile: missing or invalid official avatar URL")
    for field in ("name", "bio"):
        if raw.get(field) is not None and not isinstance(raw[field], str):
            raise ValueError(f"github_profile: invalid profile {field}")
    return {
        "username": raw["login"],
        "name": raw.get("name") or raw["login"],
        "bio": raw.get("bio") or "",
        "repos": raw["public_repos"],
        "followers": raw["followers"],
        "avatar_url": avatar,
    }


class GitHubProfile(Source):
    schedule = Schedule.parse({"every": "6h"})
    dither = "threshold"
    params = {"username": "RoCry", "layout": "profile"}
    fields = ("username", "avatar", "calendar")

    async def fetch(self, ctx: Context) -> dict[str, Any]:
        username, layout = ctx.params["username"], ctx.params["layout"]
        if not isinstance(username, str) or not re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", username
        ):
            raise ValueError("github_profile: username must be a GitHub username (1–39 letters/digits/hyphens)")
        if layout not in ("profile", "isometric"):
            raise ValueError("github_profile: layout must be 'profile' or 'isometric'")
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            meta, page = await asyncio.gather(
                client.get(
                    f"https://api.github.com/users/{username}", headers={"Accept": "application/vnd.github+json"}
                ),
                client.get(
                    f"https://github.com/users/{username}/contributions",
                    headers={"Accept-Language": "en", "Accept": "text/html"},
                ),
            )
            meta.raise_for_status()
            page.raise_for_status()
            profile = profile_data(meta.json(), username)
            calendar = parse_calendar(page.text)
            if abs((ctx.now.astimezone(UTC).date() - calendar.end).days) > 1:
                raise CalendarError(f"GitHub calendar: unexpected cutoff {calendar.end}; expected current UTC day")
            avatar = await client.get(profile.pop("avatar_url"))
            avatar.raise_for_status()
        return {**profile, "avatar": avatar_data(avatar.content), "calendar": calendar}

    def render(self, ctx: Context, panel: Panel, data: dict[str, Any]) -> str:
        calendar = data["calendar"]
        # Align to GitHub's Sunday-first weeks; last 13 columns may end midweek.
        end_sunday = calendar.end - timedelta(days=(calendar.end.weekday() + 1) % 7)
        recent_start = end_sunday - timedelta(weeks=12)
        recent = tuple(day for day in calendar.days if day.date >= recent_start)
        view = {
            **data,
            "summary_total": calendar.summary.total,
            "start": calendar.start.isoformat(),
            "end": calendar.end.isoformat(),
            "recent_total": sum(day.count for day in recent),
            "recent_start": recent_start.isoformat(),
            "wall": wall_data(recent if panel.width == 250 else calendar.days, panel, ctx.params["layout"]),
        }
        return self.render_template(ctx, panel, view)
