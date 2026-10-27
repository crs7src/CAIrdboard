import asyncio
import re
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel

from app.config import Settings
from app.db import Database

PROJECT_PATH_RE = re.compile(r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)+$")
SCP_REMOTE_RE = re.compile(r"^(?:[^@/]+@)?(?P<host>[^:/]+):(?P<path>[^/].*)$")


class GitLabError(Exception):
    """GitLab was reachable but the request failed, or it could not be reached."""


class GitLabProject(BaseModel):
    id: int
    path: str
    web_url: str
    default_branch: str | None


def _client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.gitlab_url.rstrip("/") + "/api/v4",
        headers={"PRIVATE-TOKEN": settings.gitlab_token},
        timeout=15,
    )


def _detail(response: httpx.Response) -> str:
    """GitLab's own explanation of a failure, if it gave one."""
    try:
        body = response.json()
    except ValueError:
        return ""
    message = (
        body.get("message") or body.get("error") if isinstance(body, dict) else None
    )
    if isinstance(message, list):
        message = "; ".join(map(str, message))
    elif isinstance(message, dict):
        message = "; ".join(f"{k}: {v}" for k, v in message.items())
    return f": {message}"[:400] if message else ""


async def _request(settings: Settings, method: str, path: str, **kwargs):
    try:
        async with _client(settings) as client:
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        if code == 404 and method == "GET":
            raise GitLabError("Project not found, or the token cannot see it") from e
        raise GitLabError(f"GitLab returned {code}{_detail(e.response)}") from e
    except httpx.HTTPError as e:
        raise GitLabError("Could not reach GitLab") from e
    return response.json()


async def _get(settings: Settings, path: str, **kwargs):
    return await _request(settings, "GET", path, **kwargs)


async def fetch_current_user(settings: Settings) -> str:
    data = await _get(settings, "/user")
    return data.get("name") or data["username"]


async def fetch_project(settings: Settings, path: str) -> GitLabProject:
    data = await _get(settings, _project_url(path))
    return GitLabProject(
        id=data["id"],
        path=data["path_with_namespace"],
        web_url=data["web_url"],
        default_branch=data.get("default_branch"),
    )


class MergeRequestInfo(BaseModel):
    iid: int
    web_url: str


def _project_url(path: str) -> str:
    return f"/projects/{quote(path, safe='')}"


async def find_open_merge_request(
    settings: Settings, path: str, source_branch: str
) -> MergeRequestInfo | None:
    found = await _get(
        settings,
        f"{_project_url(path)}/merge_requests",
        params={"source_branch": source_branch, "state": "opened"},
    )
    if not found:
        return None
    return MergeRequestInfo(iid=found[0]["iid"], web_url=found[0]["web_url"])


async def create_merge_request(
    settings: Settings,
    path: str,
    source_branch: str,
    target_branch: str,
    title: str,
    description: str,
) -> MergeRequestInfo:
    data = await _request(
        settings,
        "POST",
        f"{_project_url(path)}/merge_requests",
        json={
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
            "description": description,
            "remove_source_branch": True,
        },
    )
    return MergeRequestInfo(iid=data["iid"], web_url=data["web_url"])


def parse_remote(url: str) -> tuple[str, str] | None:
    """Split a git remote URL into (host, project path), or None if unrecognised."""
    url = url.strip()
    if "://" in url:
        parts = urlsplit(url)
        host, path = parts.hostname, parts.path
    else:
        m = SCP_REMOTE_RE.match(url)
        if not m:
            return None
        host, path = m["host"], m["path"]
    path = path.strip("/").removesuffix(".git")
    if not host or not PROJECT_PATH_RE.match(path):
        return None
    return host.lower(), path


async def detect_project_path(repo: str, gitlab_url: str = "") -> str | None:
    """The GitLab project path of the repo's origin remote, if it points at our GitLab."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        repo,
        "remote",
        "get-url",
        "origin",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        return None
    parsed = parse_remote(out.decode())
    if parsed is None:
        return None
    host, path = parsed
    configured = (urlsplit(gitlab_url).hostname or "").lower()
    if configured and host != configured:
        return None
    return path


class ProjectMappings:
    """Per-Jira-project override of the GitLab project path."""

    def __init__(self, db: Database):
        self.db = db

    def get(self, project: str) -> str | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT path FROM gitlab_projects WHERE project = ?", (project,)
            ).fetchone()
        return row[0] if row else None

    def set(self, project: str, path: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO gitlab_projects (project, path) VALUES (?, ?) "
                "ON CONFLICT(project) DO UPDATE SET path = excluded.path",
                (project, path),
            )

    def delete(self, project: str) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM gitlab_projects WHERE project = ?", (project,))
