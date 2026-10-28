import json
import subprocess

import pytest
import respx
from fastapi.testclient import TestClient

from app import github
from app.ai_config import AiConfig, save_ai_config
from app.main import app

API = "https://api.github.com"
TOKEN = "ghp_secret"
REPO = {
    "full_name": "me/app",
    "html_url": "https://github.com/me/app",
    "default_branch": "main",
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    cred = tmp_path / "data" / "github.json"
    monkeypatch.setenv("GITHUB_CREDENTIALS_FILE", str(cred))
    monkeypatch.setenv("GITLAB_CREDENTIALS_FILE", str(tmp_path / "gitlab.json"))
    monkeypatch.setenv("AI_CONFIG_FILE", str(tmp_path / "ai.json"))
    for name in ("GITHUB_URL", "GITHUB_TOKEN", "GITLAB_URL", "GITLAB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    save_ai_config(tmp_path / "ai.json", AiConfig(project_repos={"AB": str(repo)}))
    with TestClient(app) as client:
        yield client, repo, cred


def configure(cred):
    cred.parent.mkdir(parents=True, exist_ok=True)
    cred.write_text(json.dumps({"github_url": API, "github_token": TOKEN}))


def set_origin(repo, url):
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", url], check=True)


def test_web_host():
    assert github.web_host("https://api.github.com") == "github.com"
    assert github.web_host("https://ghe.example.com/api/v3") == "ghe.example.com"


def test_status_unconfigured(env):
    client, _, _ = env
    status = client.get("/api/github/status").json()
    assert status["configured"] is False and status["connected"] is False
    assert status["url"] == API


@respx.mock
def test_status_connected_never_exposes_token(env):
    client, _, cred = env
    configure(cred)
    route = respx.get(f"{API}/user").respond(json={"login": "me", "name": None})
    response = client.get("/api/github/status")
    assert response.json()["user"] == "me" and response.json()["connected"]
    assert TOKEN not in response.text
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"


@respx.mock
def test_status_when_rejected(env):
    client, _, cred = env
    configure(cred)
    respx.get(f"{API}/user").respond(401)
    status = client.get("/api/github/status").json()
    assert status["configured"] and not status["connected"]


@respx.mock
def test_save_credentials_verified_and_private(env):
    client, _, cred = env
    respx.get(f"{API}/user").respond(json={"login": "me", "name": "Me"})
    response = client.put("/api/github/credentials", json={"token": TOKEN})
    assert response.json() == {"connected": True, "user": "Me"}
    assert json.loads(cred.read_text())["github_token"] == TOKEN
    assert oct(cred.stat().st_mode)[-3:] == "600"
    assert TOKEN not in response.text


@respx.mock
def test_rejected_credentials_not_saved(env):
    client, _, cred = env
    respx.get(f"{API}/user").respond(401, json={"message": "Bad credentials"})
    response = client.put("/api/github/credentials", json={"token": "x"})
    assert response.status_code == 400
    assert not cred.exists()


def test_invalid_credentials_rejected(env):
    client, _, cred = env
    assert client.put("/api/github/credentials", json={}).status_code == 422
    assert client.put("/api/github/credentials", json={"url": "ghe"}).status_code == 422
    assert not cred.exists()


@respx.mock
def test_enterprise_url_is_used(env):
    client, _, _ = env
    route = respx.get("https://ghe.example.com/api/v3/user").respond(
        json={"login": "me"}
    )
    response = client.put(
        "/api/github/credentials",
        json={"url": "https://ghe.example.com/api/v3/", "token": TOKEN},
    )
    assert response.status_code == 200 and route.called


def test_detects_github_origin_and_override(env):
    client, repo, _ = env
    set_origin(repo, "git@github.com:me/app.git")
    (info,) = client.get("/api/repo-hosts").json()
    assert (info["provider"], info["path"], info["source"]) == (
        "github",
        "me/app",
        "origin",
    )
    response = client.put(
        "/api/repo-hosts/AB", json={"provider": "gitlab", "path": "g/s/p"}
    )
    assert (response.json()["provider"], response.json()["path"]) == ("gitlab", "g/s/p")
    assert response.json()["detected"] == {"provider": "github", "path": "me/app"}
    response = client.put(
        "/api/repo-hosts/AB", json={"provider": "github", "path": "o/r"}
    )
    assert response.json()["provider"] == "github"
    # one override per project: switching provider replaced the previous row
    assert client.delete("/api/repo-hosts/AB").json()["source"] == "origin"


def test_github_path_must_be_owner_repo(env):
    client, _, _ = env
    body = {"provider": "github", "path": "a/b/c"}
    assert client.put("/api/repo-hosts/AB", json=body).status_code == 422


@respx.mock
def test_check(env):
    client, repo, cred = env
    configure(cred)
    set_origin(repo, "https://github.com/me/app.git")
    route = respx.get(f"{API}/repos/me/app").respond(json=REPO)
    assert client.get("/api/repo-hosts/AB/check").json() == {
        "provider": "github",
        "path": "me/app",
        "web_url": "https://github.com/me/app",
        "default_branch": "main",
    }
    assert route.called


@respx.mock
def test_check_errors(env):
    client, repo, cred = env
    set_origin(repo, "https://github.com/me/app.git")
    assert client.get("/api/repo-hosts/AB/check").status_code == 503
    configure(cred)
    respx.get(f"{API}/repos/me/app").respond(404)
    response = client.get("/api/repo-hosts/AB/check")
    assert response.status_code == 502 and "not found" in response.text.lower()


@respx.mock
async def test_pull_request_find_and_create(env):
    _, _, cred = env
    configure(cred)
    from app.config import Settings

    settings = Settings(github_url=API, github_token=TOKEN)
    find = respx.get(f"{API}/repos/me/app/pulls").respond(json=[])
    assert await github.find_open_pull_request(settings, "me/app", "AB-1_x") is None
    assert find.calls.last.request.url.params["head"] == "me:AB-1_x"
    respx.get(f"{API}/repos/me/app/pulls").respond(
        json=[{"number": 5, "html_url": "https://github.com/me/app/pull/5"}]
    )
    found = await github.find_open_pull_request(settings, "me/app", "AB-1_x")
    assert found.iid == 5
    create = respx.post(f"{API}/repos/me/app/pulls").respond(
        201, json={"number": 6, "html_url": "https://github.com/me/app/pull/6"}
    )
    pr = await github.create_pull_request(settings, "me/app", "b", "main", "T", "D")
    assert pr.iid == 6
    assert json.loads(create.calls.last.request.content) == {
        "title": "T",
        "head": "b",
        "base": "main",
        "body": "D",
    }


@respx.mock
async def test_error_detail_is_surfaced(env):
    from app.config import Settings

    settings = Settings(github_url=API, github_token=TOKEN)
    respx.post(f"{API}/repos/me/app/pulls").respond(
        422,
        json={
            "message": "Validation Failed",
            "errors": [{"message": "A pull request already exists"}],
        },
    )
    with pytest.raises(github.GitHubError, match="already exists"):
        await github.create_pull_request(settings, "me/app", "b", "main", "T", "D")


@respx.mock
async def test_field_errors_without_a_message_are_readable():
    from app.config import Settings

    settings = Settings(github_url=API, github_token=TOKEN)
    respx.post(f"{API}/repos/me/app/pulls").respond(
        422,
        json={
            "message": "Validation Failed",
            "errors": [{"resource": "PullRequest", "field": "base", "code": "invalid"}],
        },
    )
    with pytest.raises(github.GitHubError, match="PullRequest base is invalid"):
        await github.create_pull_request(settings, "me/app", "b", "main", "T", "D")
