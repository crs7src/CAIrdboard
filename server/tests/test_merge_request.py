# ruff: noqa: F401, F811 - pytest fixtures imported from test_implementation
import json

import pytest
import respx
from dbutil import db
from fastapi.testclient import TestClient
from test_implementation import (
    approve_plan,
    commit_file,
    env,
    make_card,
    mock_jira,
    repos,
    sh,
)
from test_review import BRANCH, make_impl

from app import implementer, merge_request
from app.main import app, get_runner
from app.planner import run_command

GL = "https://git.example.com"
PROJECT = "grp/app"
MR_API = f"{GL}/api/v4/projects/grp%2Fapp/merge_requests"
CREATED = {"iid": 42, "web_url": f"{GL}/grp/app/-/merge_requests/42"}


@pytest.fixture
def client(env):
    tmp_path, _ = env
    mp = pytest.MonkeyPatch()
    mp.setenv("GITLAB_URL", GL)
    mp.setenv("GITLAB_TOKEN", "glpat")
    mp.setenv("GITLAB_CREDENTIALS_FILE", str(tmp_path / "gitlab.json"))
    app.dependency_overrides[get_runner] = lambda: run_command
    with TestClient(app) as c:
        c.put("/api/repo-hosts/AB", json={"provider": "gitlab", "path": PROJECT})
        yield c
    app.dependency_overrides.clear()
    mp.undo()


def ready(tmp_path, work, approved=True):
    approve_plan(tmp_path)
    impl = make_impl(tmp_path, work)
    if approved:
        from app.db import Approvals

        Approvals(db()).approve("AB-1")
    return impl


def origin_branches(work):
    return sh(work, "git", "ls-remote", "--heads", "origin").splitlines()


@respx.mock
def test_pushes_the_branch_and_creates_the_mr(client, env):
    tmp_path, work = env
    mock_jira()
    ready(tmp_path, work)
    respx.get(MR_API).respond(json=[])
    create = respx.post(MR_API).respond(201, json=CREATED)

    response = client.post("/api/cards/AB-1/merge-request")
    assert response.status_code == 202

    run = client.get("/api/cards/AB-1/merge-request").json()
    assert run["state"] == "created"
    assert run["mr_url"] == CREATED["web_url"] and run["mr_iid"] == 42
    assert run["title"] == "AB-1 add dark mode"
    assert run["target_branch"] == "main" and not run["outdated"]
    assert any(f"refs/heads/{BRANCH}" in line for line in origin_branches(work))
    sent = json.loads(create.calls.last.request.content)
    assert sent["source_branch"] == BRANCH
    assert sent["target_branch"] == "main"
    assert sent["title"] == "AB-1 add dark mode"
    assert sent["remove_source_branch"] is True
    assert "[AB-1](https://example.atlassian.net/browse/AB-1)" in sent["description"]
    assert "- AB-1: step 1 - add toggle" in sent["description"]
    assert client.get("/api/merge-requests").json() == {"AB-1": "created"}


@respx.mock
def test_an_existing_open_mr_is_reused_after_new_commits(client, env):
    tmp_path, work = env
    mock_jira()
    ready(tmp_path, work)
    respx.get(MR_API).respond(json=[])
    create = respx.post(MR_API).respond(201, json=CREATED)
    client.post("/api/cards/AB-1/merge-request")

    sh(work, "git", "checkout", "-q", BRANCH)
    commit_file(work, "more.txt", "AB-1: review fix - more")
    sh(work, "git", "checkout", "-q", "main")
    assert client.get("/api/merge-requests").json() == {"AB-1": "outdated"}
    assert client.get("/api/cards/AB-1/merge-request").json()["outdated"] is True

    from app.db import Approvals

    Approvals(db()).approve("AB-1")
    respx.get(MR_API).respond(json=[CREATED])
    client.post("/api/cards/AB-1/merge-request")
    run = client.get("/api/cards/AB-1/merge-request").json()
    assert run["state"] == "created" and run["updated_existing"] is True
    assert run["version"] == 2 and not run["outdated"]
    assert create.call_count == 1
    assert sh(work, "git", "rev-parse", BRANCH) in sh(
        work, "git", "ls-remote", "origin", BRANCH
    )


@respx.mock
def test_requires_approval_gitlab_and_a_mapping(client, env):
    tmp_path, work = env
    mock_jira()
    assert client.post("/api/cards/AB-1/merge-request").status_code == 409
    ready(tmp_path, work, approved=False)
    assert client.post("/api/cards/AB-1/merge-request").status_code == 409
    from app.db import Approvals

    Approvals(db()).approve("AB-1")
    client.delete("/api/repo-hosts/AB")
    response = client.post("/api/cards/AB-1/merge-request")
    assert (
        response.status_code == 409
        and "No GitLab or GitHub project" in response.json()["detail"]
    )
    assert client.post("/api/cards/bad/merge-request").status_code == 404
    assert client.get("/api/cards/AB-1/merge-request").status_code == 404
    assert origin_branches(work) == [
        line for line in origin_branches(work) if "refs/heads/main" in line
    ]


@respx.mock
def test_gitlab_not_configured_is_503(client, env, monkeypatch):
    tmp_path, work = env
    mock_jira()
    ready(tmp_path, work)
    monkeypatch.setenv("GITLAB_TOKEN", "")
    assert client.post("/api/cards/AB-1/merge-request").status_code == 503


@respx.mock
def test_gitlab_failure_is_recorded_and_can_be_retried(client, env):
    tmp_path, work = env
    mock_jira()
    ready(tmp_path, work)
    respx.get(MR_API).respond(json=[])
    respx.post(MR_API).respond(409, json={"message": ["Branch is protected"]})
    client.post("/api/cards/AB-1/merge-request")
    run = client.get("/api/cards/AB-1/merge-request").json()
    assert run["state"] == "failed" and "Branch is protected" in run["error"]
    assert client.get("/api/merge-requests").json() == {"AB-1": "failed"}

    respx.post(MR_API).respond(201, json=CREATED)
    client.post("/api/cards/AB-1/merge-request")
    assert client.get("/api/cards/AB-1/merge-request").json()["state"] == "created"


@respx.mock
def test_push_failure_is_recorded_and_no_mr_is_made(client, env):
    tmp_path, work = env
    mock_jira()
    ready(tmp_path, work)
    sh(work, "git", "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    create = respx.post(MR_API).respond(201, json=CREATED)
    client.post("/api/cards/AB-1/merge-request")
    run = client.get("/api/cards/AB-1/merge-request").json()
    assert run["state"] == "failed" and "git push" in run["error"]
    assert not create.called


@respx.mock
def test_a_busy_card_is_refused_and_a_stale_run_recovers(client, env):
    tmp_path, work = env
    mock_jira()
    impl = ready(tmp_path, work)
    store = merge_request.MergeRequestStore(db())
    store.create("AB-1", impl, "gitlab", PROJECT)  # "running" but not in ACTIVE
    run = client.get("/api/cards/AB-1/merge-request").json()
    assert run["state"] == "failed" and "Interrupted" in run["error"]

    merge_request.ACTIVE.add("AB-1")
    try:
        assert client.post("/api/cards/AB-1/merge-request").status_code == 409
    finally:
        merge_request.ACTIVE.discard("AB-1")


@respx.mock
def test_github_creates_a_pull_request(client, env, monkeypatch):
    tmp_path, work = env
    mock_jira()
    ready(tmp_path, work)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp")
    monkeypatch.setenv("GITHUB_CREDENTIALS_FILE", str(tmp_path / "github.json"))
    client.put("/api/repo-hosts/AB", json={"provider": "github", "path": "me/app"})
    api = "https://api.github.com/repos/me/app/pulls"
    respx.get(api).respond(json=[])
    create = respx.post(api).respond(
        201, json={"number": 9, "html_url": "https://github.com/me/app/pull/9"}
    )
    assert client.post("/api/cards/AB-1/merge-request").status_code == 202
    run = client.get("/api/cards/AB-1/merge-request").json()
    assert run["state"] == "created" and run["provider"] == "github"
    assert run["mr_url"].endswith("/pull/9") and run["mr_iid"] == 9
    sent = json.loads(create.calls.last.request.content)
    assert sent["head"] == BRANCH and sent["base"] == "main"
    assert "remove_source_branch" not in sent


@respx.mock
def test_a_target_missing_on_origin_falls_back_to_the_default_branch(client, env):
    tmp_path, work = env
    mock_jira()
    impl = ready(tmp_path, work)
    impl.base_branch = "develop"  # never pushed to origin
    implementer.ImplementationStore(db()).save(impl)
    respx.get(MR_API).respond(json=[])
    respx.get(f"{GL}/api/v4/projects/grp%2Fapp").respond(
        json={
            "id": 1,
            "path_with_namespace": "grp/app",
            "web_url": f"{GL}/grp/app",
            "default_branch": "main",
        }
    )
    create = respx.post(MR_API).respond(201, json=CREATED)
    assert client.post("/api/cards/AB-1/merge-request").status_code == 202
    run = client.get("/api/cards/AB-1/merge-request").json()
    assert run["state"] == "created" and run["target_branch"] == "main"
    assert json.loads(create.calls.last.request.content)["target_branch"] == "main"


@respx.mock
def test_defaults_endpoint(client, env):
    tmp_path, work = env
    mock_jira()
    assert client.get("/api/cards/AB-1/merge-request/defaults").status_code == 409
    ready(tmp_path, work, approved=False)
    body = client.get("/api/cards/AB-1/merge-request/defaults").json()
    assert body["title"] == "AB-1 add dark mode"
    assert "[AB-1](https://example.atlassian.net/browse/AB-1)" in body["description"]
    assert "- AB-1: step 1 - add toggle" in body["description"]
    assert client.get("/api/cards/bad/merge-request/defaults").status_code == 404
    assert client.get("/api/cards/AB-1/merge-request").status_code == 404
