import re
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlsplit

import httpx

from app.config import Settings
from app.db import Database
from app.jira import Card, CardNotFound, Comment
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


KEY_PREFIX = "GH_"
CLOSED_DAYS = 30
MAX_PAGES = 5


def is_issue_key(key: str) -> bool:
    return key.startswith(KEY_PREFIX)


def project_slug(path: str) -> str:
    """Card-key project for a repo: GH_ plus the upper-cased repo name (owner omitted)."""
    name = re.sub(r"[^A-Z0-9]+", "_", path.split("/")[-1].upper()).strip("_")
    return f"{KEY_PREFIX}{name or 'REPO'}"


class IssueRepos:
    """Remembers which owner/repo a card-key project (GH_APP) stands for."""

    def __init__(self, db: Database):
        self.db = db

    def get(self, slug: str) -> str | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT path FROM github_issue_repos WHERE slug = ?", (slug,)
            ).fetchone()
        return row[0] if row else None

    def claim(self, slug: str, path: str) -> bool:
        """Record the slug for this repo; False if another repo already holds it."""
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT path FROM github_issue_repos WHERE slug = ?", (slug,)
            ).fetchone()
            if row:
                return row[0].lower() == path.lower()
            conn.execute(
                "INSERT INTO github_issue_repos (slug, path) VALUES (?, ?)",
                (slug, path),
            )
        return True


def _repo_of(issue: dict) -> str:
    return issue["repository_url"].split("/repos/", 1)[1]


def _to_card(issue: dict) -> Card:
    path = _repo_of(issue)
    return Card(
        key=f"{project_slug(path)}-{issue['number']}",
        summary=issue["title"],
        status="Open" if issue["state"] == "open" else "Closed",
        priority=None,
        url=issue["html_url"],
        project=project_slug(path),
        description=(issue.get("body") or "").strip(),
        source="github",
        external_repo=path,
    )


async def _search(settings: Settings, query: str) -> list[dict]:
    items: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        data = await _request(
            settings,
            "GET",
            "/search/issues",
            params={
                "q": query,
                "sort": "updated",
                "per_page": 100,
                "page": page,
            },
        )
        items += data["items"]
        if len(data["items"]) < 100:
            break
    return items


async def fetch_assigned_issues(settings: Settings, db: Database) -> list[Card]:
    """Open issues assigned to the token's user, plus ones closed recently."""
    since = (datetime.now(UTC) - timedelta(days=CLOSED_DAYS)).date().isoformat()
    found = await _search(settings, "is:issue assignee:@me is:open")
    found += await _search(
        settings, f"is:issue assignee:@me is:closed closed:>={since}"
    )
    repos = IssueRepos(db)
    cards: list[Card] = []
    for issue in found:
        card = _to_card(issue)
        # Two repos with the same name would share a key prefix; keep the first.
        if card.external_repo and repos.claim(card.project, card.external_repo):
            cards.append(card)
    return cards


async def _fetch_comments(settings: Settings, path: str, number: int) -> list[Comment]:
    comments: list[Comment] = []
    for page in range(1, MAX_PAGES + 1):
        batch = await _request(
            settings,
            "GET",
            f"{_repo_url(path)}/issues/{number}/comments",
            params={"per_page": 100, "page": page},
        )
        comments += [
            Comment(
                author=(c.get("user") or {}).get("login", "unknown"),
                created=c["created_at"],
                body=c.get("body") or "",
            )
            for c in batch
        ]
        if len(batch) < 100:
            break
    return comments


async def fetch_issue_card(settings: Settings, db: Database, key: str) -> Card:
    slug, _, number = key.rpartition("-")
    path = IssueRepos(db).get(slug)
    if path is None:
        # First sight of this repo in this database: listing records it.
        await fetch_assigned_issues(settings, db)
        path = IssueRepos(db).get(slug)
    if path is None:
        raise CardNotFound(key)
    try:
        issue = await _request(settings, "GET", f"{_repo_url(path)}/issues/{number}")
    except GitHubError as e:
        if "not found" in str(e).lower():
            raise CardNotFound(key) from e
        raise
    if "pull_request" in issue:
        raise CardNotFound(key)
    issue.setdefault(
        "repository_url", f"{settings.github_url.rstrip('/')}/repos/{path}"
    )
    card = _to_card(issue)
    card.comments = await _fetch_comments(settings, path, int(number))
    return card
