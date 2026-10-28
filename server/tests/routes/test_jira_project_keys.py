import pytest
from dbutil import db
from fastapi.testclient import TestClient

from app.core.db import JiraProjects
from app.integrations import jira
from app.main import app, warm_jira_projects


def card(key, source="jira", project=None):
    return jira.Card(
        key=key,
        summary="s",
        status="To Do",
        priority=None,
        url="u",
        project=project or key.rsplit("-", 1)[0],
        description="",
        source=source,
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "me@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok")
    monkeypatch.setenv("JIRA_CREDENTIALS_FILE", str(tmp_path / "jira.json"))
    monkeypatch.setenv("AI_CONFIG_FILE", str(tmp_path / "ai.json"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def jira_cards(monkeypatch):
    state = {"cards": [], "calls": 0}

    async def fetch(settings):
        state["calls"] += 1
        return state["cards"]

    async def fetch_one(settings, key):
        return card(key)

    monkeypatch.setattr(jira, "fetch_assigned_cards", fetch)
    monkeypatch.setattr(jira, "fetch_card", fetch_one)
    return state


def test_cards_load_adds_projects_and_never_removes(env, jira_cards):
    with TestClient(app) as client:
        jira_cards["cards"] = [card("AB-1"), card("CD-3")]
        assert len(client.get("/api/cards").json()) == 2
        assert JiraProjects(db()).keys() == ["AB", "CD"]
        jira_cards["cards"] = [card("AB-1")]
        client.get("/api/cards")
        assert JiraProjects(db()).keys() == ["AB", "CD"]


def test_github_cards_are_not_stored(env, jira_cards):
    jira_cards["cards"] = [card("GH_REPO-1", source="github")]
    with TestClient(app) as client:
        client.get("/api/cards")
    assert JiraProjects(db()).keys() == []


def test_single_card_load_records_its_project(env, jira_cards):
    with TestClient(app) as client:
        assert client.get("/api/cards/EF-7").status_code == 200
    assert JiraProjects(db()).keys() == ["EF"]


def test_recording_failure_does_not_fail_the_request(env, jira_cards, monkeypatch):
    def boom(self, keys):
        raise RuntimeError("disk")

    monkeypatch.setattr(JiraProjects, "remember", boom)
    jira_cards["cards"] = [card("AB-1")]
    with TestClient(app) as client:
        assert client.get("/api/cards").status_code == 200


async def test_warm_up_records_keys_when_jira_is_configured(env, jira_cards):
    jira_cards["cards"] = [card("AB-1"), card("CD-2")]
    await warm_jira_projects()
    assert JiraProjects(db()).keys() == ["AB", "CD"]


async def test_warm_up_only_logs_when_unconfigured(env, jira_cards, monkeypatch):
    monkeypatch.delenv("JIRA_BASE_URL")
    monkeypatch.delenv("JIRA_EMAIL")
    monkeypatch.delenv("JIRA_API_TOKEN")
    await warm_jira_projects()
    assert jira_cards["calls"] == 0
    assert JiraProjects(db()).keys() == []


async def test_warm_up_swallows_jira_failure(env, monkeypatch):
    async def fail(settings):
        raise jira.JiraError("down")

    monkeypatch.setattr(jira, "fetch_assigned_cards", fail)
    await warm_jira_projects()
    assert JiraProjects(db()).keys() == []
