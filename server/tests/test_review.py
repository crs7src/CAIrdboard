# ruff: noqa: F401, F811 - pytest fixtures imported from test_implementation
from pathlib import Path

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

from app import implementer, reviewer
from app.main import app, get_runner
from app.planner import CommandResult, run_command

BRANCH = "AB-1_add_dark_mode"


class FakeReviewer:
    """Real git, fake copilot: the 'review' optionally commits fixes."""

    def __init__(
        self,
        fixes=(),
        report="## Review summary\nLooks fine",
        returncode=0,
        stderr="",
        leave_dirty=False,
        switch_branch=False,
    ):
        self.fixes = fixes
        self.report = report
        self.returncode = returncode
        self.stderr = stderr
        self.leave_dirty = leave_dirty
        self.switch_branch = switch_branch
        self.ai_calls: list[list[str]] = []

    async def __call__(self, args, cwd, timeout):
        if args[0] == "git":
            return await run_command(args, cwd, timeout)
        self.ai_calls.append(args)
        cwd_path = Path(cwd)
        for i, message in enumerate(self.fixes, 1):
            commit_file(cwd_path, f"fix{i}.txt", f"AB-1: review fix - {message}")
        if self.leave_dirty:
            (cwd_path / "dirty.txt").write_text("x")
        if self.switch_branch:
            sh(cwd_path, "git", "checkout", "-q", "main")
        return CommandResult(self.returncode, self.report, self.stderr)


def make_impl(tmp_path, work, state="completed"):
    """A card branch with one implementation commit and a stored implementation."""
    base = sh(work, "git", "rev-parse", "HEAD")
    sh(work, "git", "checkout", "-q", "-b", BRANCH)
    commit_file(work, "feature.txt", "AB-1: step 1 - add toggle")
    sh(work, "git", "checkout", "-q", "main")
    store = implementer.ImplementationStore(db())
    impl = store.create("AB-1", 1)
    impl.state, impl.branch, impl.base_commit = state, BRANCH, base
    impl.report = "## Summary\nImplemented"
    return store.save(impl)


async def run_rev(tmp_path, work, impl, ai):
    store = reviewer.ReviewStore(db())
    run = store.create("AB-1", impl)
    reviewer.ACTIVE.add("AB-1")
    implementer.ACTIVE_REPOS.add(str(work))
    await reviewer.run_review(
        store, run, impl, make_card(), "1. Do it", str(work), "copilot", 60, ai
    )
    return store.latest("AB-1")


async def test_clean_review_checks_out_the_branch_and_reports(env):
    tmp_path, work = env
    impl = make_impl(tmp_path, work)
    ai = FakeReviewer()
    run = await run_rev(tmp_path, work, impl, ai)
    assert run.state == "clean", run.error
    assert run.fix_commits == []
    assert run.report.startswith("## Review summary")
    assert sh(work, "git", "rev-parse", "--abbrev-ref", "HEAD") == BRANCH
    assert "AB-1" not in reviewer.ACTIVE
    assert str(work) not in implementer.ACTIVE_REPOS


async def test_fixes_mark_the_review_as_needing_another_pass(env):
    tmp_path, work = env
    impl = make_impl(tmp_path, work)
    run = await run_rev(tmp_path, work, impl, FakeReviewer(fixes=("null check",)))
    assert run.state == "fixed"
    assert [c.subject for c in run.fix_commits] == ["AB-1: review fix - null check"]


async def test_prompt_has_card_plan_report_and_code_review_agent(env):
    tmp_path, work = env
    impl = make_impl(tmp_path, work)
    ai = FakeReviewer()
    await run_rev(tmp_path, work, impl, ai)
    prompt = ai.ai_calls[0][ai.ai_calls[0].index("-p") + 1]
    assert "code-review" in prompt
    assert "AB-1 - Add a dark mode toggle" in prompt
    assert "1. Do it" in prompt
    assert "Implemented" in prompt
    assert impl.base_commit in prompt
    args = ai.ai_calls[0]
    assert "--no-ask-user" in args and "shell(git push)" in args


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"returncode": 1, "stderr": "boom"}, "boom"),
        ({"switch_branch": True}, "left the branch"),
    ],
)
async def test_failures_are_recorded(env, kwargs, message):
    tmp_path, work = env
    impl = make_impl(tmp_path, work)
    run = await run_rev(tmp_path, work, impl, FakeReviewer(**kwargs))
    assert run.state == "failed" and message in run.error


async def test_dirty_repo_is_refused_and_leftover_changes_are_noted(env):
    tmp_path, work = env
    impl = make_impl(tmp_path, work)
    (work / "dirty.txt").write_text("x")
    run = await run_rev(tmp_path, work, impl, FakeReviewer())
    assert run.state == "failed" and "uncommitted" in run.error
    (work / "dirty.txt").unlink()
    run = await run_rev(tmp_path, work, impl, FakeReviewer(leave_dirty=True))
    assert run.state == "clean"
    assert any("uncommitted" in n for n in run.notes)


@pytest.fixture(autouse=True)
def reviews_dir(env, monkeypatch):
    monkeypatch.setenv("REVIEWS_DIR", str(env[0] / "reviews"))


@pytest.fixture
def ai():
    fake = FakeReviewer()
    app.dependency_overrides[get_runner] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client(env, ai):
    with TestClient(app) as c:
        yield c


@respx.mock
def test_start_requires_a_completed_implementation(client, env):
    tmp_path, work = env
    mock_jira()
    approve_plan(tmp_path)
    assert client.post("/api/cards/AB-1/review").status_code == 409
    make_impl(tmp_path, work, state="failed")
    assert client.post("/api/cards/AB-1/review").status_code == 409


@respx.mock
def test_start_runs_review_and_get_returns_it(client, env):
    tmp_path, work = env
    mock_jira()
    approve_plan(tmp_path)
    make_impl(tmp_path, work)
    assert client.post("/api/cards/AB-1/review").status_code == 202
    body = client.get("/api/cards/AB-1/review").json()
    assert body["state"] == "clean", body["error"]
    assert body["implementation_version"] == 1
    assert client.get("/api/reviews").json() == {"AB-1": "clean"}


@respx.mock
def test_start_conflicts_when_busy(client, env):
    tmp_path, work = env
    mock_jira()
    approve_plan(tmp_path)
    make_impl(tmp_path, work)
    implementer.ACTIVE_REPOS.add(str(work))
    assert client.post("/api/cards/AB-1/review").status_code == 409
    implementer.ACTIVE_REPOS.clear()
    implementer.ACTIVE.add("AB-1")
    assert client.post("/api/cards/AB-1/review").status_code == 409


def test_get_without_review_is_404_and_stale_run_fails(client, env):
    tmp_path, work = env
    assert client.get("/api/cards/AB-1/review").status_code == 404
    assert client.get("/api/cards/bad_key/review").status_code == 404
    impl = make_impl(tmp_path, work)
    reviewer.ReviewStore(db()).create("AB-1", impl)
    body = client.get("/api/cards/AB-1/review").json()
    assert body["state"] == "failed" and "Interrupted" in body["error"]


def test_reviews_listing_empty(client):
    assert client.get("/api/reviews").json() == {}
