import subprocess

import httpx
import pytest
import respx
from dbutil import db
from fastapi.testclient import TestClient
from test_plans import FakeRunner

from app import github
from app.ai_config import AiConfig, load_ai_config, save_ai_config
from app.config import Settings, get_settings
from app.main import app, get_runner
from app.merge_request import closing_line

API = "https://api.github.com"
JIRA = "https://example.atlassian.net"


def settings(jira=False, gh=True) -> Settings:
    return Settings(
        jira_base_url=JIRA if jira else "",
        jira_email="me@x.com" if jira else "",
        jira_api_token="t" if jira else "",
        github_url=API,
        github_token="ghp" if gh else "",
        _env_file=None,
    )


def issue(number, repo="me/my-app", state="open", **extra):
    return {
        "number": number,
        "title": f"Issue {number}",
        "state": state,
        "html_url": f"https://github.com/{repo}/issues/{number}",
        "body": "Body text",
        "repository_url": f"{API}/repos/{repo}",
        **extra,
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_CONFIG_FILE", str(tmp_path / "ai.json"))
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def use(s):
    app.dependency_overrides[get_settings] = lambda: s


def search(open_items, closed_items=()):
    def respond(request: httpx.Request):
        q = request.url.params["q"]
        items = closed_items if "is:closed" in q else open_items
        return httpx.Response(200, json={"items": list(items)})

    return respx.get(f"{API}/search/issues").mock(side_effect=respond)


def test_project_slug():
    assert github.project_slug("me/my-app") == "GH_MY_APP"
    assert github.project_slug("me/app.v2") == "GH_APP_V2"
    assert github.is_issue_key("GH_X-1") and not github.is_issue_key("AB-1")


@respx.mock
def test_assigned_issues_become_cards(client):
    use(settings())
    route = search([issue(12), issue(3, "me/other")], [issue(9, state="closed")])
    response = client.get("/api/cards")
    assert response.status_code == 200
    cards = response.json()
    assert [c["key"] for c in cards] == ["GH_MY_APP-12", "GH_OTHER-3", "GH_MY_APP-9"]
    first = cards[0]
    assert first["source"] == "github" and first["external_repo"] == "me/my-app"
    assert first["status"] == "Open" and cards[2]["status"] == "Closed"
    assert first["project"] == "GH_MY_APP" and first["description"] == "Body text"
    queries = [c.request.url.params["q"] for c in route.calls]
    assert "assignee:@me" in queries[0] and "is:open" in queries[0]
    assert "closed:>=" in queries[1]


@respx.mock
def test_pull_requests_are_not_cards(client):
    use(settings())
    search([issue(1), issue(2, pull_request={"url": "x"})])
    # PRs are excluded by the search query; one that slips through is still not a card
    assert client.get("/api/cards").status_code == 200
    assert "is:issue" in respx.calls[0].request.url.params["q"]


@respx.mock
def test_same_repo_name_under_another_owner_is_skipped(client):
    use(settings())
    search([issue(1, "me/app"), issue(2, "them/app")])
    assert [c["key"] for c in client.get("/api/cards").json()] == ["GH_APP-1"]


@respx.mock
def test_jira_and_github_are_merged_and_one_failure_is_a_warning(client):
    use(settings(jira=True))
    respx.get(f"{JIRA}/rest/api/3/search/jql").respond(
        json={
            "issues": [
                {
                    "key": "AB-1",
                    "fields": {"summary": "J", "status": {"name": "To Do"}},
                }
            ],
            "isLast": True,
        }
    )
    search([issue(5)])
    keys = [c["key"] for c in client.get("/api/cards").json()]
    assert keys == ["AB-1", "GH_MY_APP-5"]

    respx.get(f"{API}/search/issues").respond(500)
    response = client.get("/api/cards")
    assert [c["key"] for c in response.json()] == ["AB-1"]
    assert "GitHub returned 500" in response.headers["X-Card-Warnings"]


@respx.mock
def test_all_sources_failing_is_502_and_none_configured_is_503(client):
    use(settings())
    respx.get(f"{API}/search/issues").respond(401)
    assert client.get("/api/cards").status_code == 502
    use(settings(gh=False))
    assert client.get("/api/cards").status_code == 503


@respx.mock
def test_issue_card_detail_with_comments(client):
    use(settings())
    search([issue(12)])
    respx.get(f"{API}/repos/me/my-app/issues/12").respond(json=issue(12))
    respx.get(f"{API}/repos/me/my-app/issues/12/comments").respond(
        json=[
            {
                "user": {"login": "bob"},
                "created_at": "2026-01-01T00:00:00Z",
                "body": "hi",
            }
        ]
    )
    detail = client.get("/api/cards/GH_MY_APP-12").json()
    assert detail["key"] == "GH_MY_APP-12" and detail["source"] == "github"
    assert detail["comments"] == [
        {
            "author": "bob",
            "created": "2026-01-01T00:00:00Z",
            "body": "hi",
            "after_reopen": False,
        }
    ]
    assert detail["repo_configured"] is False and detail["eligible"] is True


@respx.mock
def test_issue_card_errors(client):
    use(settings())
    search([issue(12)])
    respx.get(f"{API}/repos/me/my-app/issues/99").respond(404)
    assert client.get("/api/cards/GH_MY_APP-99").status_code == 404
    assert client.get("/api/cards/GH_NOPE-1").status_code == 404
    respx.get(f"{API}/repos/me/my-app/issues/7").respond(
        json=issue(7, pull_request={"url": "x"})
    )
    assert client.get("/api/cards/GH_MY_APP-7").status_code == 404
    use(settings(gh=False))
    assert client.get("/api/cards/GH_MY_APP-12").status_code == 503


def test_repo_map_is_persisted(client):
    repos = github.IssueRepos(db())
    assert repos.claim("GH_A", "o/a") and repos.claim("GH_A", "O/A")
    assert not repos.claim("GH_A", "x/a")
    assert repos.get("GH_A") == "o/a" and repos.get("GH_B") is None


def test_closing_line():
    card = github.Card(
        key="GH_APP-4",
        summary="s",
        status="Open",
        priority=None,
        url="u",
        project="GH_APP",
        description="",
        source="github",
        external_repo="me/app",
    )
    assert closing_line(card, "github", "me/app") == "Closes #4"
    assert closing_line(card, "github", "Me/App") == "Closes #4"
    assert closing_line(card, "github", "org/app") == "Closes me/app#4"
    assert closing_line(card, "gitlab", "g/p") is None
    jira_card = card.model_copy(update={"source": "jira", "external_repo": None})
    assert closing_line(jira_card, "github", "me/app") is None


@pytest.fixture
def planning(tmp_path, monkeypatch):
    """A local repo whose origin is me/my-app, mapped under an unrelated project."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "remote",
            "add",
            "origin",
            "git@github.com:me/my-app.git",
        ],
        check=True,
    )
    cfg = tmp_path / "ai.json"
    monkeypatch.setenv("AI_CONFIG_FILE", str(cfg))
    save_ai_config(
        cfg,
        AiConfig(eligible_statuses=["To Do"], project_repos={"JIRAPROJ": str(repo)}),
    )
    runner = FakeRunner()
    app.dependency_overrides[get_runner] = lambda: runner
    return cfg, repo, runner


@respx.mock
def test_an_open_issue_gets_a_plan_with_its_repo_found_from_origin(client, planning):
    cfg, repo, runner = planning
    use(settings())
    search([issue(12)])
    respx.get(f"{API}/repos/me/my-app/issues/12").respond(json=issue(12))
    respx.get(f"{API}/repos/me/my-app/issues/12/comments").respond(json=[])
    detail = client.get("/api/cards/GH_MY_APP-12").json()
    assert detail["eligible"] and detail["repo_configured"]
    assert load_ai_config(cfg).repo_for("GH_MY_APP") == str(repo)

    response = client.post("/api/cards/GH_MY_APP-12/plan")
    assert response.status_code == 202
    assert client.get("/api/cards/GH_MY_APP-12/plan").json()["state"] == "ready"
    assert runner.calls[0][1] == str(repo)
    assert "GitHub status: Open" in runner.calls[0][0][3]


@respx.mock
def test_card_list_links_repos_and_closed_issues_stay_ineligible(client, planning):
    cfg, repo, _ = planning
    use(settings())
    search([issue(1), issue(2, "me/elsewhere")], [issue(3, state="closed")])
    client.get("/api/cards")
    assert load_ai_config(cfg).repo_for("GH_MY_APP") == str(repo)
    assert load_ai_config(cfg).repo_for("GH_ELSEWHERE") is None

    respx.get(f"{API}/repos/me/my-app/issues/3").respond(json=issue(3, state="closed"))
    respx.get(f"{API}/repos/me/my-app/issues/3/comments").respond(json=[])
    assert client.get("/api/cards/GH_MY_APP-3").json()["eligible"] is False
    assert client.post("/api/cards/GH_MY_APP-3/plan").status_code == 409
