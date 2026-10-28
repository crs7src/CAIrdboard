from urllib.parse import quote

import httpx

from app.config import Settings
from app.remotes import ChangeRequest, HostError, HostProject


class GitLabError(HostError):
    """GitLab was reachable but the request failed, or it could not be reached."""


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


async def fetch_project(settings: Settings, path: str) -> HostProject:
    data = await _get(settings, _project_url(path))
    return HostProject(
        provider="gitlab",
        path=data["path_with_namespace"],
        web_url=data["web_url"],
        default_branch=data.get("default_branch"),
    )


def _project_url(path: str) -> str:
    return f"/projects/{quote(path, safe='')}"


async def find_open_merge_request(
    settings: Settings, path: str, source_branch: str
) -> ChangeRequest | None:
    found = await _get(
        settings,
        f"{_project_url(path)}/merge_requests",
        params={"source_branch": source_branch, "state": "opened"},
    )
    if not found:
        return None
    return ChangeRequest(iid=found[0]["iid"], web_url=found[0]["web_url"])


async def create_merge_request(
    settings: Settings,
    path: str,
    source_branch: str,
    target_branch: str,
    title: str,
    description: str,
) -> ChangeRequest:
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
    return ChangeRequest(iid=data["iid"], web_url=data["web_url"])
