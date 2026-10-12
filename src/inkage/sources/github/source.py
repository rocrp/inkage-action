"""One GitHub repository: stars, forks, open issues, last commit, latest release.

GitHub REST, key-less (60 req/h per IP) or with ``GITHUB_TOKEN`` from the
environment when set (Actions provides one). Three calls per refresh:
``/repos/{repo}``, ``/repos/{repo}/commits?per_page=1`` and
``/repos/{repo}/releases/latest``; the last answers 404 when the repo has no
release, which is not an error.
"""

import asyncio
import os
from datetime import datetime
from typing import Any

import httpx

from inkage.schedule import Schedule
from inkage.source import Context, Source

API = "https://api.github.com"


class GitHubError(RuntimeError):
    pass


async def fetch_github(path: str, *, missing_ok: bool = False) -> Any:
    """GET ``API + path`` as JSON; ``None`` on 404 when ``missing_ok``."""
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        resp = await client.get(API + path)
        if missing_ok and resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()


def _local(stamp: str, ctx: Context) -> str:
    return datetime.fromisoformat(stamp).astimezone(ctx.tz).strftime("%Y-%m-%d %H:%M")


def summarize(
    repo: dict[str, Any], commits: list[dict[str, Any]], release: dict[str, Any] | None, ctx: Context
) -> dict[str, Any]:
    """Flatten the three responses for the template; raise on missing core fields."""
    if not isinstance(repo.get("stargazers_count"), int) or not repo.get("pushed_at"):
        raise GitHubError(f"GitHub {repo.get('full_name')!r}: missing stargazers_count or pushed_at")
    if not commits:
        raise GitHubError(f"GitHub {repo['full_name']}: no commits")
    commit = commits[0]["commit"]
    return {
        "repo": repo["full_name"],
        "description": repo.get("description") or "",
        "language": repo.get("language") or "",
        "stars": repo["stargazers_count"],
        "forks": repo["forks_count"],
        "open_issues": repo["open_issues_count"],
        "pushed_at": _local(repo["pushed_at"], ctx),
        "commit_message": commit["message"].splitlines()[0],
        "commit_author": commit["author"]["name"],
        "commit_date": _local(commit["author"]["date"], ctx),
        "commit_sha": commits[0]["sha"][:7],
        "release": release["tag_name"] if release else "",
        "release_date": _local(release["published_at"], ctx) if release else "",
    }


class GitHub(Source):
    schedule = Schedule.parse({"every": "30m"})
    dither = "threshold"
    params = {"repo": "rocrp/inkage-action"}
    fields = ("repo", "stars", "pushed_at", "commit_message")

    async def fetch(self, ctx: Context) -> dict[str, Any]:
        repo = ctx.params["repo"]
        if not isinstance(repo, str) or repo.count("/") != 1:
            raise ValueError(f"github: repo must be 'owner/name', got {repo!r}")
        meta, commits, release = await asyncio.gather(
            fetch_github(f"/repos/{repo}"),
            fetch_github(f"/repos/{repo}/commits?per_page=1"),
            fetch_github(f"/repos/{repo}/releases/latest", missing_ok=True),
        )
        return summarize(meta, commits, release, ctx)
