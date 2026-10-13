"""Recent public GitHub Actions runs, fetched anonymously in one request."""

import re
from datetime import datetime
from typing import Any

import httpx

from inkage.schedule import Schedule
from inkage.source import Context, Source

RUN_STATES = {"queued", "in_progress", "requested", "waiting", "pending", "completed"}
CONCLUSIONS = {
    "success",
    "failure",
    "neutral",
    "cancelled",
    "skipped",
    "timed_out",
    "action_required",
    "stale",
    "startup_failure",
}
FAILED = {"failure", "timed_out", "action_required", "startup_failure"}


class CIError(RuntimeError):
    pass


def text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CIError(f"github_ci: missing or invalid {field}")
    return value.strip()


def parse_runs(raw: dict, ctx: Context) -> dict:
    try:
        runs = raw["workflow_runs"]
        if not isinstance(runs, list):
            raise CIError("github_ci: workflow_runs must be a list")
        rows = []
        for run in runs[: ctx.params["count"]]:
            status, conclusion = run["status"], run["conclusion"]
            if status not in RUN_STATES:
                raise CIError(f"github_ci: unknown run status {status!r}")
            if status == "completed" and conclusion not in CONCLUSIONS:
                raise CIError(f"github_ci: completed run has invalid conclusion {conclusion!r}")
            stamp = datetime.fromisoformat(text(run["updated_at"], "updated_at"))
            if stamp.tzinfo is None:
                raise CIError("github_ci: updated_at needs a timezone")
            state = conclusion if status == "completed" else status
            rows.append(
                {
                    "name": text(run["name"], "name"),
                    "title": text(run["display_title"], "display_title"),
                    "branch": text(run["head_branch"], "head_branch"),
                    "sha": text(run["head_sha"], "head_sha")[:7],
                    "state": state.replace("_", " ").upper(),
                    "failed": state in FAILED,
                    "updated": stamp.astimezone(ctx.tz).strftime("%m-%d %H:%M"),
                }
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise CIError(f"github_ci: malformed workflow run ({exc})") from exc
    return {
        "repo": ctx.params["repo"],
        "branch": ctx.params["branch"],
        "runs": rows,
        "checked": ctx.local_now.strftime("%m-%d %H:%M"),
    }


class GitHubCI(Source):
    schedule = Schedule.parse({"every": "15m"})
    params = {"repo": "rocrp/inkage-action", "branch": "", "count": 5}
    fields = ("repo", "checked")

    async def fetch(self, ctx: Context) -> dict:
        repo, branch, count = (ctx.params[k] for k in ("repo", "branch", "count"))
        if not isinstance(repo, str) or not re.fullmatch(r"[\w.-]+/[\w.-]+", repo, flags=re.ASCII):
            raise ValueError("github_ci: repo must be owner/name")
        if not isinstance(branch, str):
            raise ValueError("github_ci: branch must be a string")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 5:
            raise ValueError("github_ci: count must be an integer 1..5")
        query = {"per_page": str(count)}
        if branch:
            query["branch"] = branch
        async with httpx.AsyncClient(
            timeout=20,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        ) as client:
            response = await client.get(f"https://api.github.com/repos/{repo}/actions/runs", params=query)
            response.raise_for_status()
        return parse_runs(response.json(), ctx)
