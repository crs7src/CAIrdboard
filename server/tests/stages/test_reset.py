import subprocess
from pathlib import Path

import pytest
from dbutil import db
from fastapi.testclient import TestClient

from app.core.ai_config import AiConfig, save_ai_config
from app.core.db import Approvals, Resets
from app.main import app, get_runner
from app.stages import implementer, planner, reset, tester
from app.stages.planner import run_command

BASE = "https://example.atlassian.net"


def sh(cwd: Path, *args: str) -> str:
    return subprocess.run(
        args, cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def work(tmp_path):
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    sh(tmp_path, "git", "init", "-q", "--bare", "-b", "main", str(origin))
    sh(tmp_path, "git", "clone", "-q", str(origin), str(work))
    for cfg in (("user.email", "t@example.com"), ("user.name", "Test")):
        sh(work, "git", "config", *cfg)
    sh(work, "git", "checkout", "-q", "-b", "main")
    (work / "a.txt").write_text("a")
    sh(work, "git", "add", "a.txt")
    sh(work, "git", "commit", "-q", "-m", "initial")
    sh(work, "git", "push", "-q", "-u", "origin", "main")
    sh(work, "git", "checkout", "-q", "-b", "AB-1_thing")
    (work / "b.txt").write_text("b")
    sh(work, "git", "add", "b.txt")
    sh(work, "git", "commit", "-q", "-m", "AB-1: step 1")
    return work


def seed(key="AB-1"):
    plans = planner.PlanStore(db())
    plan = plans.create(key, "DEV In Progress", None)
    plan.state = "approved"
    plans.save(plan)
    impl = implementer.ImplementationStore(db()).create(key, 1)
    impl.state, impl.branch = "completed", "AB-1_thing" if key == "AB-1" else None
    implementer.ImplementationStore(db()).save(impl)
    Approvals(db()).approve(key)


def store():
    return tester.TestStore(db(), Path("/tmp/unused-test-runs"))


def branches(work):
    return sh(work, "git", "branch", "--format=%(refname:short)").split()


async def do_reset(work, key="AB-1", delete_branch=True):
    return await reset.reset_card(
        run_command, db(), store(), key, str(work), delete_branch
    )


async def test_reset_deletes_progress_and_branch_and_leaves_other_cards(work):
    seed()
    seed("AB-2")
    result = await do_reset(work)
    assert result.branch == "AB-1_thing" and result.branch_deleted
    assert result.deleted_sha
    assert branches(work) == ["main"]
    assert sh(work, "git", "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert planner.PlanStore(db()).latest("AB-1") is None
    assert implementer.ImplementationStore(db()).latest("AB-1") is None
    assert Approvals(db()).get("AB-1") is None
    assert planner.PlanStore(db()).latest("AB-2")
    assert Approvals(db()).get("AB-2")
    assert Resets(db()).get("AB-1")
    assert not implementer.ACTIVE_REPOS


async def test_reset_without_branch_deletion_keeps_branch(work):
    seed()
    result = await do_reset(work, delete_branch=False)
    assert not result.branch_deleted
    assert "AB-1_thing" in branches(work)
    assert planner.PlanStore(db()).latest("AB-1") is None


async def test_dirty_repo_refuses_and_keeps_data(work):
    seed()
    sh(work, "git", "checkout", "-q", "main")
    (work / "a.txt").write_text("changed")
    with pytest.raises(reset.ResetError) as e:
        await do_reset(work)
    assert e.value.status == 409
    assert "AB-1_thing" in branches(work)
    assert planner.PlanStore(db()).latest("AB-1")
    assert not implementer.ACTIVE_REPOS


@pytest.mark.parametrize("module", [planner, implementer])
async def test_active_run_refuses(work, module):
    seed()
    module.ACTIVE.add("AB-1")
    try:
        with pytest.raises(reset.ResetError):
            await do_reset(work)
    finally:
        module.ACTIVE.discard("AB-1")
    assert planner.PlanStore(db()).latest("AB-1")


async def test_running_test_app_is_stopped_first(work, monkeypatch):
    seed()
    stopped = []

    async def fake_stop(_store, key):
        stopped.append(key)
        implementer.ACTIVE_REPOS.discard(str(work))

    monkeypatch.setattr(tester, "stop_app", fake_stop)
    implementer.ACTIVE_REPOS.add(str(work))
    await do_reset(work)
    assert stopped == ["AB-1"]


async def test_busy_repo_refuses(work):
    seed()
    implementer.ACTIVE_REPOS.add(str(work))
    try:
        with pytest.raises(reset.ResetError):
            await do_reset(work)
    finally:
        implementer.ACTIVE_REPOS.discard(str(work))


# ---- routes ---------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch, work):
    monkeypatch.setenv("JIRA_BASE_URL", BASE)
    monkeypatch.setenv("JIRA_EMAIL", "me@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok")
    monkeypatch.setenv("JIRA_CREDENTIALS_FILE", str(tmp_path / "jira.json"))
    monkeypatch.setenv("AI_CONFIG_FILE", str(tmp_path / "ai.json"))
    save_ai_config(tmp_path / "ai.json", AiConfig(project_repos={"AB": str(work)}))
    app.dependency_overrides[get_runner] = lambda: run_command
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_reset_route(client, work):
    seed()
    r = client.post("/api/cards/AB-1/reset", json={"delete_branch": False})
    assert r.status_code == 200 and r.json()["branch_deleted"] is False
    r = client.post("/api/cards/AB-1/reset")
    assert r.json()["branch_deleted"] is True
    assert branches(work) == ["main"]


def test_reset_route_conflict_and_unmapped(client):
    seed()
    planner.ACTIVE.add("AB-1")
    try:
        assert client.post("/api/cards/AB-1/reset").status_code == 409
    finally:
        planner.ACTIVE.discard("AB-1")
    assert client.post("/api/cards/ZZ-1/reset").status_code == 422


@pytest.mark.parametrize(
    ("reopened", "activity", "expected"),
    [
        ("2999-01-01T00:00:00.000+0000", True, True),
        ("2000-01-01T00:00:00.000+0000", True, False),
        (None, True, False),
        ("2999-01-01T00:00:00.000+0000", False, True),
    ],
)
def test_reset_needed(client, reopened, activity, expected):
    from app.routes.reset import reset_pending

    if activity:
        seed()
    from app.core.config import Settings

    assert reset_pending(Settings(), "AB-1", reopened) is expected


def test_dismiss_persists_until_a_newer_reopen(client):
    from app.core.config import Settings
    from app.routes.reset import reset_pending

    reopened = "2999-01-01T00:00:00.000+0000"
    assert reset_pending(Settings(), "AB-1", reopened)
    assert client.put("/api/cards/AB-1/reopen-prompt/dismiss").status_code == 204
    assert Resets(db()).get("AB-1")
    assert reset_pending(Settings(), "AB-1", "2000-01-01T00:00:00.000+0000") is False
    assert reset_pending(Settings(), "AB-1", "2999-06-01T00:00:00.000+0000") is True
