from urllib.parse import quote, urlsplit

import httpx

from app.config import Settings
from app.remotes import ChangeRequest, HostError, HostProject

API_VERSION = "2022-11-28"


class GitHubError(HostError):
    """GitHub was reachable but the request failed, or it could not be reached."""


def web_host(api_url: str) -> str:
    """The host git remotes use for this API URL (api.github.com -> github.com)."""
    host = (urlsplit(api_url).hostname or "").lower()
    return "github.com" if host == "api.github.com" else host


def _client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.github_url.rstrip("/"),
        headers={
            "Authorization": f"Bearer {settings.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
        },
        timeout=15,
    )


def _detail(response: httpx.Response) -> str:
    """GitHub's own explanation of a failure, if it gave one."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    parts = [str(body["message"])] if body.get("message") else []
    for err in body.get("errors") or []:
        parts.append(
            str(err.get("message") or err) if isinstance(err, dict) else str(err)
        )
    return f": {'; '.join(parts)}"[:400] if parts else ""


async def _request(settings: Settings, method: str, path: str, **kwargs):
    try:
        async with _client(settings) as client:
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        if code == 404 and method == "GET":
            raise GitHubError("Repository not found, or the token cannot see it") from e
        raise GitHubError(f"GitHub returned {code}{_detail(e.response)}") from e
    except httpx.HTTPError as e:
        raise GitHubError("Could not reach GitHub") from e
    return response.json()


def _repo_url(path: str) -> str:
    return f"/repos/{quote(path, safe='/')}"


async def fetch_current_user(settings: Settings) -> str:
    data = await _request(settings, "GET", "/user")
    return data.get("name") or data["login"]


async def fetch_project(settings: Settings, path: str) -> HostProject:
    data = await _request(settings, "GET", _repo_url(path))
    return HostProject(
        provider="github",
        path=data["full_name"],
        web_url=data["html_url"],
        default_branch=data.get("default_branch"),
    )


async def find_open_pull_request(
    settings: Settings, path: str, branch: str
) -> ChangeRequest | None:
    owner = path.split("/")[0]
    found = await _request(
        settings,
        "GET",
        f"{_repo_url(path)}/pulls",
        params={"head": f"{owner}:{branch}", "state": "open"},
    )
    if not found:
        return None
    return ChangeRequest(iid=found[0]["number"], web_url=found[0]["html_url"])


async def create_pull_request(
    settings: Settings,
    path: str,
    branch: str,
    base: str,
    title: str,
    body: str,
) -> ChangeRequest:
    data = await _request(
        settings,
        "POST",
        f"{_repo_url(path)}/pulls",
        json={"title": title, "head": branch, "base": base, "body": body},
    )
    return ChangeRequest(iid=data["number"], web_url=data["html_url"])
