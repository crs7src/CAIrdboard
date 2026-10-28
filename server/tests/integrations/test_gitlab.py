import json
import stat
import subprocess

import pytest
import respx
from fastapi.testclient import TestClient

from app.auth.credentials import GITLAB_FIELDS, read_saved_credentials
from app.core.ai_config import AiConfig, save_ai_config
from app.core.config import get_settings
from app.integrations.remotes import parse_remote
from app.main import app

URL = "https://git.example.com"
TOKEN = "glpat-secret"


@pytest.fixture
def env(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    cred = tmp_path / "data" / "gitlab.json"
    monkeypatch.setenv("GITLAB_CREDENTIALS_FILE", str(cred))
    monkeypatch.setenv("AI_CONFIG_FILE", str(tmp_path / "ai.json"))
    monkeypatch.delenv("GITLAB_URL", raising=False)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)  # keep any real server/.env out of the test
    save_ai_config(tmp_path / "ai.json", AiConfig(project_repos={"AB": str(repo)}))
    with TestClient(app) as client:
        yield client, repo, cred


def set_origin(repo, url):
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", url], check=True)


def configure(cred):
    cred.parent.mkdir(parents=True, exist_ok=True)
    cred.write_text(json.dumps({"gitlab_url": URL, "gitlab_token": TOKEN}))


@pytest.mark.parametrize(
    "remote,expected",
    [
        ("git@git.example.com:grp/sub/app.git", ("git.example.com", "grp/sub/app")),
        ("ssh://git@Git.Example.com:2222/grp/app.git", ("git.example.com", "grp/app")),
        ("https://user:pw@git.example.com/grp/app", ("git.example.com", "grp/app")),
        ("https://git.example.com/grp/app.git/", ("git.example.com", "grp/app")),
        ("https://git.example.com/onlyone", None),
        ("/local/path/repo", None),
        ("", None),
    ],
)
def test_parse_remote(remote, expected):
    assert parse_remote(remote) == expected


def test_status_unconfigured(env):
    client, _, _ = env
    assert client.get("/api/gitlab/status").json() == {
        "configured": False,
        "connected": False,
        "user": None,
        "url": "",
    }


@respx.mock
def test_status_never_exposes_token(env):
    client, _, cred = env
    configure(cred)
    route = respx.get(f"{URL}/api/v4/user").respond(json={"name": "Me"})
    response = client.get("/api/gitlab/status")
    assert response.json() == {
        "configured": True,
        "connected": True,
        "user": "Me",
        "url": URL,
    }
    assert TOKEN not in response.text
    assert route.calls.last.request.headers["private-token"] == TOKEN


@respx.mock
def test_status_when_gitlab_rejects(env):
    client, _, cred = env
    configure(cred)
    respx.get(f"{URL}/api/v4/user").respond(401)
    body = client.get("/api/gitlab/status").json()
    assert body["configured"] and not body["connected"]


@respx.mock
def test_save_credentials_verified_and_private(env):
    client, _, cred = env
    respx.get(f"{URL}/api/v4/user").respond(json={"username": "me"})
    response = client.put(
        "/api/gitlab/credentials", json={"url": f" {URL}/ ", "token": TOKEN}
    )
    assert response.json() == {"connected": True, "user": "me"}
    assert TOKEN not in response.text
    assert read_saved_credentials(cred, GITLAB_FIELDS) == {
        "gitlab_url": URL,
        "gitlab_token": TOKEN,
    }
    assert stat.S_IMODE(cred.stat().st_mode) == 0o600
    assert get_settings().gitlab_token == TOKEN


@respx.mock
def test_rejected_credentials_not_saved(env):
    client, _, cred = env
    respx.get(f"{URL}/api/v4/user").respond(401)
    response = client.put("/api/gitlab/credentials", json={"url": URL, "token": "bad"})
    assert response.status_code == 400
    assert not cred.exists()


@respx.mock
def test_partial_update_keeps_other_field(env):
    client, _, cred = env
    configure(cred)
    respx.get(f"{URL}/api/v4/user").respond(json={"name": "Me"})
    assert (
        client.put("/api/gitlab/credentials", json={"token": "new"}).status_code == 200
    )
    assert read_saved_credentials(cred, GITLAB_FIELDS) == {
        "gitlab_url": URL,
        "gitlab_token": "new",
    }


@pytest.mark.parametrize(
    "body", [{}, {"url": "git.example.com", "token": "x"}, {"url": URL, "token": " "}]
)
def test_invalid_credentials_rejected(env, body):
    client, _, cred = env
    assert client.put("/api/gitlab/credentials", json=body).status_code == 422
    assert not cred.exists()


def test_incomplete_credentials_rejected(env):
    client, _, cred = env
    assert client.put("/api/gitlab/credentials", json={"url": URL}).status_code == 422
    assert not cred.exists()


def test_projects_detect_from_origin_and_override(env):
    client, repo, cred = env
    configure(cred)
    set_origin(repo, "git@git.example.com:grp/app.git")
    (info,) = client.get("/api/repo-hosts").json()
    assert info["project"] == "AB"
    assert info["detected"] == {"provider": "gitlab", "path": "grp/app"}
    assert (info["provider"], info["path"], info["source"]) == (
        "gitlab",
        "grp/app",
        "origin",
    )

    response = client.put(
        "/api/repo-hosts/AB", json={"provider": "gitlab", "path": "other/proj.git"}
    )
    assert response.json()["source"] == "override"
    assert response.json()["path"] == "other/proj"
    assert response.json()["detected"]["path"] == "grp/app"

    response = client.delete("/api/repo-hosts/AB")
    assert response.json()["source"] == "origin"
    assert response.json()["path"] == "grp/app"


def test_remote_on_another_host_is_not_detected(env):
    client, repo, cred = env
    configure(cred)
    set_origin(repo, "git@bitbucket.org:grp/app.git")
    assert client.get("/api/repo-hosts").json()[0]["detected"] is None


def test_no_origin_means_nothing_detected(env):
    client, _, _ = env
    assert client.get("/api/repo-hosts").json()[0]["path"] is None


def test_mapping_validation_and_unknown_project(env):
    client, _, _ = env
    body = {"provider": "gitlab", "path": "nogroup"}
    assert client.put("/api/repo-hosts/AB", json=body).status_code == 422
    body = {"provider": "github", "path": "a/b/c"}
    assert client.put("/api/repo-hosts/AB", json=body).status_code == 422
    body = {"provider": "gitlab", "path": "a/b"}
    assert client.put("/api/repo-hosts/ZZ", json=body).status_code == 404
    assert client.get("/api/repo-hosts/ZZ/check").status_code == 404


@respx.mock
def test_check_returns_default_branch(env):
    client, repo, cred = env
    configure(cred)
    set_origin(repo, "git@git.example.com:grp/app.git")
    route = respx.get(f"{URL}/api/v4/projects/grp%2Fapp").respond(
        json={
            "id": 7,
            "path_with_namespace": "grp/app",
            "web_url": f"{URL}/grp/app",
            "default_branch": "main",
        }
    )
    response = client.get("/api/repo-hosts/AB/check")
    assert response.json() == {
        "provider": "gitlab",
        "path": "grp/app",
        "web_url": f"{URL}/grp/app",
        "default_branch": "main",
    }
    assert route.called


@respx.mock
def test_check_uses_override(env):
    client, repo, cred = env
    configure(cred)
    set_origin(repo, "git@git.example.com:grp/app.git")
    client.put("/api/repo-hosts/AB", json={"provider": "gitlab", "path": "x/y"})
    route = respx.get(f"{URL}/api/v4/projects/x%2Fy").respond(
        json={
            "id": 1,
            "path_with_namespace": "x/y",
            "web_url": "u",
            "default_branch": None,
        }
    )
    assert client.get("/api/repo-hosts/AB/check").status_code == 200
    assert route.called


@respx.mock
def test_check_errors(env):
    client, _, cred = env
    assert client.get("/api/repo-hosts/AB/check").status_code == 409
    client.put("/api/repo-hosts/AB", json={"provider": "gitlab", "path": "x/y"})
    assert client.get("/api/repo-hosts/AB/check").status_code == 503
    configure(cred)
    respx.get(f"{URL}/api/v4/projects/x%2Fy").respond(404)
    response = client.get("/api/repo-hosts/AB/check")
    assert response.status_code == 502
    assert "not found" in response.json()["detail"].lower()
