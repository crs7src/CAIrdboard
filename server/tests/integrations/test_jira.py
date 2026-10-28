import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app

BASE = "https://example.atlassian.net"
CONFIGURED = Settings(
    jira_base_url=BASE,
    jira_email="me@example.com",
    jira_api_token="tok",
    _env_file=None,
)
UNCONFIGURED = Settings(_env_file=None)


def issue(key: str, priority: str | None = "High") -> dict:
    return {
        "key": key,
        "fields": {
            "summary": f"Summary {key}",
            "status": {"name": "To Do"},
            "priority": {"name": priority} if priority else None,
        },
    }


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def use(settings: Settings):
    app.dependency_overrides[get_settings] = lambda: settings


@respx.mock
def test_cards_are_normalized(client):
    use(CONFIGURED)
    route = respx.get(f"{BASE}/rest/api/3/search/jql").respond(
        json={"issues": [issue("AB-1"), issue("AB-2", None)], "isLast": True}
    )
    response = client.get("/api/cards")
    assert response.status_code == 200
    assert response.json() == [
        {
            "key": "AB-1",
            "summary": "Summary AB-1",
            "status": "To Do",
            "priority": "High",
            "url": f"{BASE}/browse/AB-1",
            "project": "AB",
            "description": "",
            "comments": [],
            "status_history": [],
            "reopened": False,
            "last_reopened_at": None,
            "source": "jira",
            "external_repo": None,
        },
        {
            "key": "AB-2",
            "summary": "Summary AB-2",
            "status": "To Do",
            "priority": None,
            "url": f"{BASE}/browse/AB-2",
            "project": "AB",
            "description": "",
            "comments": [],
            "status_history": [],
            "reopened": False,
            "last_reopened_at": None,
            "source": "jira",
            "external_repo": None,
        },
    ]
    request = route.calls.last.request
    assert "currentUser()" in request.url.params["jql"]
    assert request.headers["authorization"].startswith("Basic ")


@respx.mock
def test_cards_follow_pagination(client):
    use(CONFIGURED)
    route = respx.get(f"{BASE}/rest/api/3/search/jql").mock(
        side_effect=[
            httpx.Response(
                200, json={"issues": [issue("AB-1")], "nextPageToken": "n1"}
            ),
            httpx.Response(200, json={"issues": [issue("AB-2")], "isLast": True}),
        ]
    )
    response = client.get("/api/cards")
    assert [c["key"] for c in response.json()] == ["AB-1", "AB-2"]
    assert route.calls.last.request.url.params["nextPageToken"] == "n1"


def test_cards_not_configured(client):
    use(UNCONFIGURED)
    assert client.get("/api/cards").status_code == 503


@respx.mock
def test_cards_jira_error_returns_502(client):
    use(CONFIGURED)
    respx.get(f"{BASE}/rest/api/3/search/jql").respond(401)
    response = client.get("/api/cards")
    assert response.status_code == 502
    assert "401" in response.json()["detail"]


@respx.mock
def test_cards_unreachable_returns_502(client):
    use(CONFIGURED)
    respx.get(f"{BASE}/rest/api/3/search/jql").mock(
        side_effect=httpx.ConnectError("boom")
    )
    assert client.get("/api/cards").status_code == 502


def test_status_not_configured(client):
    use(UNCONFIGURED)
    assert client.get("/api/jira/status").json() == {
        "base_url": "",
        "email": "",
        "configured": False,
        "connected": False,
        "user": None,
    }


@respx.mock
def test_status_connected(client):
    use(CONFIGURED)
    respx.get(f"{BASE}/rest/api/3/myself").respond(json={"displayName": "Me"})
    assert client.get("/api/jira/status").json() == {
        "base_url": BASE,
        "email": "me@example.com",
        "configured": True,
        "connected": True,
        "user": "Me",
    }


@respx.mock
def test_status_bad_credentials(client):
    use(CONFIGURED)
    respx.get(f"{BASE}/rest/api/3/myself").respond(401)
    assert client.get("/api/jira/status").json() == {
        "base_url": BASE,
        "email": "me@example.com",
        "configured": True,
        "connected": False,
        "user": None,
    }
