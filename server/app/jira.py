from datetime import datetime

import httpx
from pydantic import BaseModel

from app.config import Settings

ASSIGNED_JQL = (
    "assignee = currentUser() AND resolution = Unresolved ORDER BY updated DESC"
)


CARD_FIELDS = "summary,status,priority,description"


class JiraError(Exception):
    """Jira was reachable but the request failed, or Jira could not be reached."""


class CardNotFound(JiraError):
    """The requested issue does not exist or is not visible to this user."""


REOPENED_STATUS = "reopened"


class Comment(BaseModel):
    author: str
    created: str
    body: str
    after_reopen: bool = False


class StatusChange(BaseModel):
    from_status: str
    to_status: str
    when: str
    author: str


class Card(BaseModel):
    key: str
    summary: str
    status: str
    priority: str | None
    url: str
    project: str
    description: str
    comments: list[Comment] = []
    status_history: list[StatusChange] = []
    # True if the card is, or ever was, in the Reopened status.
    reopened: bool = False
    last_reopened_at: str | None = None


def _client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.jira_base_url.rstrip("/"),
        auth=(settings.jira_email, settings.jira_api_token),
        headers={"Accept": "application/json"},
        timeout=15,
    )


def adf_to_text(node: dict | list | str | None) -> str:
    """Flatten Jira's Atlassian Document Format into readable plain text."""
    if not node:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_to_text(n) for n in node)
    kind = node.get("type")
    if kind == "text":
        return node.get("text", "")
    if kind == "hardBreak":
        return "\n"
    inner = adf_to_text(node.get("content"))
    if kind == "listItem":
        return f"- {inner.strip()}\n"
    if kind in {"paragraph", "heading", "codeBlock", "blockquote"}:
        return inner.strip("\n") + "\n\n"
    return inner


def _to_card(issue: dict, base_url: str) -> Card:
    fields = issue["fields"]
    priority = fields.get("priority")
    return Card(
        key=issue["key"],
        summary=fields["summary"],
        status=fields["status"]["name"],
        priority=priority["name"] if priority else None,
        url=f"{base_url.rstrip('/')}/browse/{issue['key']}",
        project=issue["key"].split("-")[0],
        description=adf_to_text(fields.get("description")).strip(),
    )


async def _get(
    client: httpx.AsyncClient, path: str, params: dict | None = None
) -> dict:
    try:
        response = await client.get(path, params=params)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise JiraError(f"Jira returned {e.response.status_code}") from e
    except httpx.HTTPError as e:
        raise JiraError("Could not reach Jira") from e
    return response.json()


async def fetch_assigned_cards(settings: Settings) -> list[Card]:
    cards: list[Card] = []
    params: dict = {
        "jql": ASSIGNED_JQL,
        "fields": CARD_FIELDS,
        "maxResults": 100,
    }
    async with _client(settings) as client:
        while True:
            data = await _get(client, "/rest/api/3/search/jql", params)
            cards += [_to_card(i, settings.jira_base_url) for i in data["issues"]]
            token = data.get("nextPageToken")
            if not token:
                return cards
            params = {**params, "nextPageToken": token}


async def fetch_current_user(settings: Settings) -> str:
    async with _client(settings) as client:
        data = await _get(client, "/rest/api/3/myself")
    return data["displayName"]


async def _fetch_comments(client: httpx.AsyncClient, key: str) -> list[Comment]:
    comments: list[Comment] = []
    start = 0
    while True:
        data = await _get(
            client,
            f"/rest/api/3/issue/{key}/comment",
            {"startAt": start, "maxResults": 100, "orderBy": "created"},
        )
        page = data.get("comments", [])
        comments += [
            Comment(
                author=(c.get("author") or {}).get("displayName", "Unknown"),
                created=c.get("created", ""),
                body=adf_to_text(c.get("body")).strip(),
            )
            for c in page
        ]
        start += len(page)
        if not page or start >= data.get("total", 0):
            return comments


async def _fetch_status_history(
    client: httpx.AsyncClient, key: str
) -> list[StatusChange]:
    changes: list[StatusChange] = []
    start = 0
    while True:
        data = await _get(
            client,
            f"/rest/api/3/issue/{key}/changelog",
            {"startAt": start, "maxResults": 100},
        )
        page = data.get("values", [])
        for entry in page:
            for item in entry.get("items", []):
                if item.get("field") == "status":
                    changes.append(
                        StatusChange(
                            from_status=item.get("fromString") or "",
                            to_status=item.get("toString") or "",
                            when=entry.get("created", ""),
                            author=(entry.get("author") or {}).get(
                                "displayName", "Unknown"
                            ),
                        )
                    )
        start += len(page)
        if not page or data.get("isLast", True) or start >= data.get("total", 0):
            return sorted(changes, key=lambda c: _when(c.when))


def _when(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.min


def is_reopened_status(status: str) -> bool:
    return status.strip().casefold().replace("-", "") == REOPENED_STATUS


def apply_history(card: Card) -> None:
    """Derive the reopened flag and mark comments posted after the latest reopen."""
    reopens = [c.when for c in card.status_history if is_reopened_status(c.to_status)]
    card.last_reopened_at = max(reopens, key=_when) if reopens else None
    card.reopened = bool(reopens) or is_reopened_status(card.status)
    if card.last_reopened_at:
        cutoff = _when(card.last_reopened_at)
        for c in card.comments:
            c.after_reopen = _when(c.created) > cutoff


async def fetch_card(settings: Settings, key: str) -> Card:
    async with _client(settings) as client:
        try:
            response = await client.get(
                f"/rest/api/3/issue/{key}", params={"fields": CARD_FIELDS}
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise CardNotFound(key) from e
            raise JiraError(f"Jira returned {e.response.status_code}") from e
        except httpx.HTTPError as e:
            raise JiraError("Could not reach Jira") from e
        card = _to_card(response.json(), settings.jira_base_url)
        card.comments = await _fetch_comments(client, key)
        card.status_history = await _fetch_status_history(client, key)
    apply_history(card)
    return card
