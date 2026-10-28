# ruff: noqa: F401, F811 - pytest fixtures imported from test_implementation
import pytest
from fastapi.testclient import TestClient
from test_implementation import approve_plan, commit_file, env, repos, sh
from test_review import make_impl

from app.main import app, get_runner
from app.stages import implementer
from app.stages.planner import run_command


async def real_runner(args, cwd, timeout):
    return await run_command(args, cwd, timeout)


@pytest.fixture
def client(env):
    app.dependency_overrides[get_runner] = lambda: real_runner
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def add_commit(work, name, message):
    sh(work, "git", "checkout", "-q", "AB-1_add_dark_mode")
    (work / name).write_text("line1\nline2\n")
    sh(work, "git", "add", name)
    sh(work, "git", "commit", "-q", "-m", message)
    sh(work, "git", "checkout", "-q", "main")


def test_changes_cover_the_whole_branch_without_touching_the_checkout(client, env):
    tmp_path, work = env
    make_impl(tmp_path, work)
    add_commit(work, "second.txt", "AB-1: review fix - second")
    body = client.get("/api/cards/AB-1/changes").json()
    assert body["branch"] == "AB-1_add_dark_mode"
    assert [c["subject"] for c in body["commits"]] == [
        "AB-1: step 1 - add toggle",
        "AB-1: review fix - second",
    ]
    assert "diff --git a/feature.txt b/feature.txt" in body["diff"]
    assert "diff --git a/second.txt b/second.txt" in body["diff"]
    assert "+line1" in body["diff"]
    assert body["selected_commit"] is None
    assert sh(work, "git", "rev-parse", "--abbrev-ref", "HEAD") == "main"


def test_a_single_commit_can_be_selected(client, env):
    tmp_path, work = env
    make_impl(tmp_path, work)
    add_commit(work, "second.txt", "AB-1: review fix - second")
    commits = client.get("/api/cards/AB-1/changes").json()["commits"]
    body = client.get(
        "/api/cards/AB-1/changes", params={"commit": commits[1]["short"]}
    ).json()
    assert body["selected_commit"] == commits[1]["sha"]
    assert "second.txt" in body["diff"] and "feature.txt" not in body["diff"]


@pytest.mark.parametrize("commit", ["--stat", "zzzzzzz", "abcdef1", "main"])
def test_unknown_or_unsafe_commits_are_rejected(client, env, commit):
    tmp_path, work = env
    make_impl(tmp_path, work)
    r = client.get("/api/cards/AB-1/changes", params={"commit": commit})
    assert r.status_code == 422


def test_no_implementation_or_bad_key_is_404(client, env):
    assert client.get("/api/cards/AB-1/changes").status_code == 404
    assert client.get("/api/cards/bad_key/changes").status_code == 404
