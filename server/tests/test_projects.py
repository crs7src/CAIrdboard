import httpx
import pytest
import respx
from dbutil import db
from fastapi.testclient import TestClient

from app import hosting, tester
from app.ai_config import AiConfig, load_ai_config, save_ai_config
from app.config import Settings, get_settings
from app.main import app

API = "https://api.github.com"
JIRA = "https://example.atlassian.net"


def settings(jira=True, gh=True) -> Settings:
    return Settings(
        jira_base_url=JIRA if jira else "",
        jira_email="me@x.com" if jira else "",
        jira_api_token="t" if jira else "",
        github_url=API,
        github_token="ghp" if gh else "",
        _env_file=None,
    )


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    return str(path)


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "ai.json"
    monkeypatch.setenv("AI_CONFIG_FILE", str(path))
    return path


@pytest.fixture
def client(config_file):
    app.dependency_overrides[get_settings] = settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def create(client, repo, **extra):
    body = {
        "name": "My project",
        "key": "ab",
        "repo_path": repo,
        "jira_enabled": True,
        **extra,
    }
    return client.post("/api/projects", json=body)


def test_list_empty(client):
    assert client.get("/api/projects").json() == []


def test_create_jira_with_github_host(client, repo, config_file):
    response = create(client, repo, provider="github", host_path="me/app")
    assert response.status_code == 201
    project = response.json()
    assert project["key"] == "AB" and project["name"] == "My project"
    assert project["jira"] is True and project["repo_exists"] is True
    assert project["host"]["provider"] == "github"
    assert project["host"]["path"] == "me/app"
    assert project["host"]["source"] == "override"
    done = {i["id"]: i["done"] for i in project["status"]}
    assert done == {
        "repo": True,
        "jira": True,
        "host": True,
        "host_credentials": True,
        "tests": False,
    }
    config = load_ai_config(config_file)
    assert config.project_repos == {"AB": repo}
    assert config.project_names == {"AB": "My project"}
    assert [p["key"] for p in client.get("/api/projects").json()] == ["AB"]


def test_create_jira_with_gitlab_host(client, repo):
    project = create(client, repo, provider="gitlab", host_path="g/sub/app").json()
    assert project["host"]["provider"] == "gitlab"
    done = {i["id"]: i["done"] for i in project["status"]}
    assert done["host_credentials"] is False  # GitLab is not configured


def test_create_github_only_generates_key(client, repo):
    response = create(
        client,
        repo,
        key=None,
        jira_enabled=False,
        provider="github",
        host_path="me/my-app",
    )
    assert response.status_code == 201
    project = response.json()
    assert project["key"] == "GH_MY_APP" and project["jira"] is False
    assert "jira" not in {i["id"] for i in project["status"]}


def test_create_without_host_is_allowed_but_incomplete(client, repo):
    project = create(client, repo).json()
    assert project["host"]["path"] is None
    assert {i["id"]: i["done"] for i in project["status"]}["host"] is False


@pytest.mark.parametrize(
    "extra",
    [
        {"key": "a"},
        {"key": "GH_X"},
        {"key": None},
        {"name": " "},
        {"provider": "github"},
        {"provider": "github", "host_path": "no-owner"},
        {"jira_enabled": False},
        {"jira_enabled": False, "provider": "gitlab", "host_path": "g/p"},
    ],
)
def test_bad_input_is_422(client, repo, extra):
    assert create(client, repo, **extra).status_code == 422


def test_repo_path_must_be_absolute_and_exist(client, tmp_path):
    assert create(client, "relative/dir").status_code == 422
    assert create(client, str(tmp_path / "missing")).status_code == 422


def test_duplicate_key_is_409(client, repo):
    assert create(client, repo).status_code == 201
    assert create(client, repo).status_code == 409
    github_only = {
        "key": None,
        "jira_enabled": False,
        "provider": "github",
        "host_path": "me/app",
    }
    assert create(client, repo, **github_only).status_code == 201
    assert create(client, repo, **github_only).status_code == 409


def test_github_slug_held_by_another_repo_is_409(client, repo):
    body = {"key": None, "jira_enabled": False, "provider": "github"}
    assert create(client, repo, host_path="me/app", **body).status_code == 201
    client.delete("/api/projects/GH_APP")
    assert create(client, repo, host_path="them/app", **body).status_code == 409


def test_update_changes_name_repo_and_host(client, repo, tmp_path, config_file):
    create(client, repo, provider="github", host_path="me/app")
    other = tmp_path / "other"
    other.mkdir()
    response = client.put(
        "/api/projects/ab",
        json={
            "name": "Renamed",
            "repo_path": str(other),
            "provider": "gitlab",
            "host_path": "g/p",
        },
    )
    assert response.status_code == 200
    project = response.json()
    assert project["name"] == "Renamed" and project["repo_path"] == str(other)
    assert project["host"]["provider"] == "gitlab"
    assert hosting.Mappings(db()).get("AB") == hosting.Target(
        provider="gitlab", path="g/p"
    )
    cleared = client.put(
        "/api/projects/AB", json={"name": "Renamed", "repo_path": repo}
    ).json()
    assert cleared["host"]["path"] is None
    assert hosting.Mappings(db()).get("AB") is None


def test_update_unknown_is_404_and_github_only_key_is_fixed(client, repo):
    body = {"name": "x", "repo_path": repo}
    assert client.put("/api/projects/ZZ", json=body).status_code == 404
    create(
        client,
        repo,
        key=None,
        jira_enabled=False,
        provider="github",
        host_path="me/app",
    )
    other = {**body, "provider": "github", "host_path": "me/different"}
    assert client.put("/api/projects/GH_APP", json=other).status_code == 422
    assert client.put("/api/projects/GH_APP", json=body).status_code == 422
    same = {**body, "provider": "github", "host_path": "other/app"}
    assert client.put("/api/projects/GH_APP", json=same).status_code == 200


def test_delete_removes_only_the_project_setup(client, repo, tmp_path, config_file):
    other = tmp_path / "o"
    other.mkdir()
    save_ai_config(
        config_file,
        AiConfig(
            project_repos={"CD": str(other)},
            project_names={"CD": "Keep"},
            eligible_statuses=["Doing"],
        ),
    )
    create(client, repo, provider="github", host_path="me/app")
    tester.ConfigStore(db()).save(
        "AB",
        [tester.AppSpec(name="web", start_command="x", ready_url="http://localhost:1")],
        "settings",
    )
    assert client.delete("/api/projects/ab").status_code == 204
    config = load_ai_config(config_file)
    assert config.project_repos == {"CD": str(other)}
    assert config.project_names == {"CD": "Keep"}
    assert config.eligible_statuses == ["Doing"]
    assert hosting.Mappings(db()).get("AB") is None
    assert "AB" in tester.ConfigStore(db()).projects()
    assert client.delete("/api/projects/AB").status_code == 404


def test_existing_project_appears_with_key_as_name(client, repo, config_file):
    save_ai_config(config_file, AiConfig(project_repos={"OLD": repo}))
    projects = client.get("/api/projects").json()
    assert projects[0]["name"] == "OLD"
    tester.ConfigStore(db()).save(
        "OLD",
        [tester.AppSpec(name="web", start_command="x", ready_url="http://localhost:1")],
        "settings",
    )
    assert client.get("/api/projects").json()[0]["test_apps_configured"] is True


def jira_issue(key, status="To Do"):
    return {"key": key, "fields": {"summary": f"S {key}", "status": {"name": status}}}


def gh_issue(number, repo="me/my-app"):
    return {
        "number": number,
        "title": f"Issue {number}",
        "state": "open",
        "html_url": f"https://github.com/{repo}/issues/{number}",
        "body": "",
        "repository_url": f"{API}/repos/{repo}",
    }


def mock_sources(jira_keys=("AB-1", "CD-2"), gh=None, gh_status=200):
    gh = [gh_issue(5)] if gh is None else gh
    respx.get(f"{JIRA}/rest/api/3/search/jql").respond(
        json={"issues": [jira_issue(k) for k in jira_keys], "isLast": True}
    )

    def search(request: httpx.Request):
        items = [] if "is:closed" in request.url.params["q"] else list(gh)
        return httpx.Response(gh_status, json={"items": items})

    respx.get(f"{API}/search/issues").mock(side_effect=search)


@respx.mock
def test_project_detail_has_only_its_cards(client, repo):
    create(client, repo)
    create(
        client,
        repo,
        key=None,
        jira_enabled=False,
        provider="github",
        host_path="me/my-app",
    )
    mock_sources()
    ab = client.get("/api/projects/AB").json()
    assert [c["key"] for c in ab["cards"]] == ["AB-1"]
    assert ab["cards"][0]["status"] == "To Do" and ab["cards"][0]["eligible"]
    assert ab["cards"][0]["plan_state"] is None and ab["card_warnings"] is None
    gh = client.get("/api/projects/GH_MY_APP").json()
    assert [c["key"] for c in gh["cards"]] == ["GH_MY_APP-5"]
    assert gh["cards"][0]["source"] == "github"


@respx.mock
def test_project_cards_include_step_states(client, repo):
    from app import planner

    create(client, repo)
    mock_sources()
    plan = planner.PlanStore(db()).create("AB-1", "To Do", None)
    plan.state = "approved"
    planner.PlanStore(db()).save(plan)
    cards = client.get("/api/projects/AB").json()["cards"]
    assert cards[0]["plan_state"] == "approved"


@respx.mock
def test_project_detail_survives_one_source_failing(client, repo):
    create(client, repo)
    mock_sources(gh_status=500)
    body = client.get("/api/projects/AB").json()
    assert [c["key"] for c in body["cards"]] == ["AB-1"]
    assert "GitHub returned 500" in body["card_warnings"]


@respx.mock
def test_project_detail_with_every_source_failing_has_warning(client, repo):
    create(client, repo)
    respx.get(f"{JIRA}/rest/api/3/search/jql").respond(500)
    respx.get(f"{API}/search/issues").respond(500)
    response = client.get("/api/projects/AB")
    assert response.status_code == 200
    assert response.json()["cards"] == [] and response.json()["card_warnings"]


def test_project_detail_without_sources_is_not_a_503(client, repo):
    create(client, repo)
    app.dependency_overrides[get_settings] = lambda: settings(jira=False, gh=False)
    body = client.get("/api/projects/AB")
    assert body.status_code == 200
    assert body.json()["cards"] == [] and body.json()["card_warnings"] is None


@respx.mock
def test_project_with_no_cards_is_empty(client, repo):
    create(client, repo)
    mock_sources(jira_keys=(), gh=())
    assert client.get("/api/projects/AB").json()["cards"] == []


def test_unknown_project_detail_is_404(client):
    assert client.get("/api/projects/NOPE").status_code == 404


@respx.mock
def test_card_listing_does_not_overwrite_a_manual_github_mapping(
    client, repo, tmp_path, config_file
):
    create(
        client,
        repo,
        key=None,
        jira_enabled=False,
        provider="github",
        host_path="me/my-app",
    )
    other = tmp_path / "other"
    other.mkdir()
    mock_sources()
    client.get("/api/cards")
    client.get("/api/projects/GH_MY_APP")
    assert load_ai_config(config_file).project_repos["GH_MY_APP"] == repo
