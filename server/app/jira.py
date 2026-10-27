import httpx
from pydantic import BaseModel

from app.config import Settings

ASSIGNED_JQL = (
    "assignee = currentUser() AND resolution = Unresolved ORDER BY updated DESC"
)


class JiraError(Exception):
    """Jira was reachable but the request failed, or Jira could not be reached."""


class Card(BaseModel):
    key: str
    summary: str
    status: str
    priority: str | None
    url: str


def _client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.jira_base_url.rstrip("/"),
        auth=(settings.jira_email, settings.jira_api_token),
        headers={"Accept": "application/json"},
        timeout=15,
    )


def _to_card(issue: dict, base_url: str) -> Card:
    fields = issue["fields"]
    priority = fields.get("priority")
    return Card(
        key=issue["key"],
        summary=fields["summary"],
        status=fields["status"]["name"],
        priority=priority["name"] if priority else None,
        url=f"{base_url.rstrip('/')}/browse/{issue['key']}",
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
        "fields": "summary,status,priority",
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
