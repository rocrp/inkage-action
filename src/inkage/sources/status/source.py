"""Public Statuspage summary: official rollup, components, unresolved incidents."""

from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from inkage.schedule import Schedule
from inkage.source import Context, Source

INDICATORS = {"none": "OPERATIONAL", "minor": "DEGRADED", "major": "PARTIAL OUTAGE", "critical": "MAJOR OUTAGE"}
STATES = {
    "operational": (0, "Operational"),
    "under_maintenance": (1, "Maintenance"),
    "degraded_performance": (2, "Degraded"),
    "partial_outage": (3, "Partial outage"),
    "major_outage": (4, "Major outage"),
}


class StatusError(RuntimeError):
    pass


def text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StatusError(f"status: missing or invalid {field}")
    return value.strip()


def parse_summary(raw: dict, ctx: Context) -> dict:
    try:
        page, status = raw["page"], raw["status"]
        name = text(page["name"], "page.name")
        indicator = status["indicator"]
        if indicator not in INDICATORS:
            raise StatusError(f"status: unknown indicator {indicator!r}")
        description = text(status["description"], "status.description")
        updated = datetime.fromisoformat(text(page["updated_at"], "page.updated_at"))
        if updated.tzinfo is None:
            raise StatusError("status: page.updated_at needs a timezone")
        components, incidents = raw["components"], raw["incidents"]
        if not isinstance(components, list) or not isinstance(incidents, list):
            raise StatusError("status: components and incidents must be lists")
        rows = []
        for component in components:
            label = text(component["name"], "component.name")
            state = component["status"]
            if state not in STATES:
                raise StatusError(f"status: unknown component status {state!r}")
            # Respect the provider's presentation flags; the rollup still covers the whole page.
            if component.get("group") or component.get("showcase") is False:
                continue
            severity, label_state = STATES[state]
            rows.append({"name": label, "state": label_state, "severity": severity})
        rows.sort(key=lambda row: -row["severity"])
        alerts = [
            {"name": text(i["name"], "incident.name"), "state": text(i["status"], "incident.status")} for i in incidents
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise StatusError(f"status: malformed summary ({exc})") from exc
    return {
        "label": ctx.params["label"] or name,
        "headline": INDICATORS[indicator],
        "description": description,
        "alert": indicator != "none",
        "components": rows,
        "incidents": alerts,
        "affected": sum(row["severity"] > 0 for row in rows),
        "updated": updated.astimezone(ctx.tz).strftime("%m-%d %H:%M"),
        "checked": ctx.local_now.strftime("%m-%d %H:%M"),
    }


class Status(Source):
    schedule = Schedule.parse({"every": "15m"})
    params = {"url": "https://www.githubstatus.com", "label": ""}
    fields = ("label", "headline", "checked")

    async def fetch(self, ctx: Context) -> dict:
        url, label = ctx.params["url"], ctx.params["label"]
        if not isinstance(url, str) or not isinstance(label, str):
            raise ValueError("status: url and label must be strings")
        parts = urlsplit(url)
        if (
            parts.scheme not in {"https", "http"}
            or not parts.hostname
            or parts.username
            or parts.query
            or parts.fragment
        ):
            raise ValueError("status: url must be a public Statuspage base URL without credentials/query/fragment")
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(f"{url.rstrip('/')}/api/v2/summary.json")
            response.raise_for_status()
        return parse_summary(response.json(), ctx)
