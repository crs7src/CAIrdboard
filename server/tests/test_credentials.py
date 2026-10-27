import base64
import json
import os
import stat

import pytest
import respx
from fastapi.testclient import TestClient

from app.config import get_settings, read_saved_credentials, save_credentials
from app.main import app

BASE = "https://example.atlassian.net"
NEW_BASE = "https://other.atlassian.net"


@pytest.fixture
def cred_file(tmp_path, monkeypatch):
    path = tmp_path / "data" / "jira.json"
    monkeypatch.setenv("JIRA_BASE_URL", BASE)
    monkeypatch.setenv("JIRA_EMAIL", "me@example.com")
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    monkeypatch.setenv("JIRA_CREDENTIALS_FILE", str(path))
    monkeypatch.chdir(tmp_path)  # keep any real server/.env out of the test
    return path


@pytest.fixture
def client(cred_file):
    with TestClient(app) as c:
        yield c


def basic(email: str, token: str) -> str:
    return "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()


def test_save_merges_and_is_private(tmp_path):
    path = tmp_path / "sub" / "jira.json"
    save_credentials(path, {"jira_api_token": "abc", "jira_email": "a@x.com"})
    save_credentials(path, {"jira_api_token": "def"})
    assert read_saved_credentials(path) == {
        "jira_api_token": "def",
        "jira_email": "a@x.com",
    }
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_read_missing_or_corrupt_is_empty(tmp_path):
    assert read_saved_credentials(tmp_path / "nope") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert read_saved_credentials(bad) == {}


def test_saved_values_override_env(cred_file, monkeypatch):
    monkeypatch.setenv("JIRA_API_TOKEN", "from-env")
    assert get_settings().jira_api_token == "from-env"
    save_credentials(
        cred_file, {"jira_api_token": "from-file", "jira_email": "new@x.com"}
    )
    settings = get_settings()
    assert settings.jira_api_token == "from-file"
    assert settings.jira_email == "new@x.com"
    assert settings.jira_base_url == BASE


@respx.mock
def test_update_all_fields_validates_saves_and_is_used(client, cred_file):
    route = respx.get(f"{NEW_BASE}/rest/api/3/myself").respond(
        json={"displayName": "Me"}
    )
    response = client.put(
        "/api/jira/credentials",
        json={"base_url": f"{NEW_BASE}/", "email": " new@x.com ", "token": " key "},
    )
    assert response.status_code == 200
    assert response.json() == {"connected": True, "user": "Me"}
    assert "key" not in response.text
    assert route.calls.last.request.headers["authorization"] == basic(
        "new@x.com", "key"
    )
    assert json.loads(cred_file.read_text()) == {
        "jira_base_url": NEW_BASE,
        "jira_email": "new@x.com",
        "jira_api_token": "key",
    }

    respx.get(f"{NEW_BASE}/rest/api/3/search/jql").respond(json={"issues": []})
    assert client.get("/api/cards").status_code == 200


@respx.mock
def test_partial_update_keeps_other_fields(client, cred_file):
    save_credentials(cred_file, {"jira_api_token": "old"})
    respx.get(f"{BASE}/rest/api/3/myself").respond(json={"displayName": "Me"})
    assert (
        client.put("/api/jira/credentials", json={"email": "z@x.com"}).status_code
        == 200
    )
    saved = read_saved_credentials(cred_file)
    assert saved == {"jira_api_token": "old", "jira_email": "z@x.com"}
    assert respx.calls.last.request.headers["authorization"] == basic("z@x.com", "old")


@respx.mock
def test_rejected_credentials_are_not_saved(client, cred_file):
    save_credentials(cred_file, {"jira_api_token": "good"})
    respx.get(f"{BASE}/rest/api/3/myself").respond(401)
    response = client.put("/api/jira/credentials", json={"token": "bad"})
    assert response.status_code == 400
    assert read_saved_credentials(cred_file) == {"jira_api_token": "good"}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"token": "   "},
        {"email": ""},
        {"base_url": "example.atlassian.net"},
    ],
)
def test_invalid_input_rejected(client, cred_file, body):
    assert client.put("/api/jira/credentials", json=body).status_code == 422
    assert not cred_file.exists()


def test_incomplete_result_rejected(client, cred_file):
    # No token anywhere yet, and only the email is being set.
    assert (
        client.put("/api/jira/credentials", json={"email": "a@x.com"}).status_code
        == 422
    )
    assert not cred_file.exists()


@respx.mock
def test_status_exposes_site_and_email_but_never_token(client, cred_file):
    save_credentials(cred_file, {"jira_api_token": "secret-token"})
    respx.get(f"{BASE}/rest/api/3/myself").respond(json={"displayName": "Me"})
    response = client.get("/api/jira/status")
    body = response.json()
    assert body["connected"] is True
    assert body["base_url"] == BASE
    assert body["email"] == "me@example.com"
    assert "secret-token" not in response.text
