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
from test_review import BRANCH, make_impl

from app import feedback, implementer, reviewer
from app.main import app, get_runner
from app.planner import CommandResult, run_command


class FakeEditor:
    """Real git, fake copilot: the 'edit' commits one file per comment."""

    def __init__(
        self,
        commits=("tweak",),
        report="## Feedback summary\nDone",
        returncode=0,
        stderr="",
        leave_dirty=False,
        switch_branch=False,
    ):
        self.commits = commits
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
        for i, message in enumerate(self.commits, 1):
            commit_file(cwd_path, f"fb{i}.txt", f"AB-1: address feedback - {message}")
        if self.leave_dirty:
            (cwd_path / "dirty.txt").write_text("x")
        if self.switch_branch:
            sh(cwd_path, "git", "checkout", "-q", "main")
        return CommandResult(self.returncode, self.report, self.stderr)


@pytest.fixture(autouse=True)
def feedback_dirs(env, monkeypatch):
    monkeypatch.setenv("FEEDBACK_DIR", str(env[0] / "feedback"))
    feedback.ACTIVE.clear()


@pytest.fixture
def ai():
    fake = FakeEditor()
    app.dependency_overrides[get_runner] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client(env, ai):
    with TestClient(app) as c:
        yield c


def ready(tmp_path, work):
    mock_jira()
    approve_plan(tmp_path)
    return make_impl(tmp_path, work)


# ---- comments ---------------------------------------------------------------


def test_add_list_edit_and_delete_comments(client):
    general = client.post(
        "/api/cards/AB-1/feedback/comments", json={"text": " Rename it "}
    )
    assert general.status_code == 201
    line = client.post(
        "/api/cards/AB-1/feedback/comments",
        json={"text": "Null check", "file": "a.py", "line": 7, "code": "x = y.z"},
    ).json()
    assert general.json()["text"] == "Rename it" and general.json()["file"] is None
    assert line["side"] == "new" and line["status"] == "pending"

    data = client.get("/api/cards/AB-1/feedback").json()
    assert [c["text"] for c in data["comments"]] == ["Rename it", "Null check"]
    assert data["run"] is None

    edited = client.put(
        f"/api/cards/AB-1/feedback/comments/{line['id']}", json={"text": "Guard"}
    )
    assert edited.json()["text"] == "Guard"
    assert (
        client.delete(f"/api/cards/AB-1/feedback/comments/{line['id']}").status_code
        == 204
    )
    assert (
        client.delete(f"/api/cards/AB-1/feedback/comments/{line['id']}").status_code
        == 404
    )
    assert len(client.get("/api/cards/AB-1/feedback").json()["comments"]) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"text": "  "},
        {"text": "x", "line": 3},
        {"text": "x", "file": "a.py", "line": 0},
        {"text": "x", "file": "a.py", "side": "middle"},
    ],
)
def test_invalid_comments_are_rejected(client, body):
    assert (
        client.post("/api/cards/AB-1/feedback/comments", json=body).status_code == 422
    )


def test_bad_key_and_blank_edit(client):
    assert client.get("/api/cards/bad_key/feedback").status_code == 404
    c = client.post("/api/cards/AB-1/feedback/comments", json={"text": "x"}).json()
    assert (
        client.put(
            f"/api/cards/AB-1/feedback/comments/{c['id']}", json={"text": " "}
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/cards/AB-1/feedback/comments/nope", json={"text": "y"}
        ).status_code
        == 404
    )


# ---- submit -----------------------------------------------------------------


@respx.mock
def test_submit_needs_a_comment_and_a_completed_implementation(client, env):
    tmp_path, work = env
    mock_jira()
    approve_plan(tmp_path)
    assert client.post("/api/cards/AB-1/feedback/submit").status_code == 409
    make_impl(tmp_path, work)
    assert (
        client.post("/api/cards/AB-1/feedback/submit").status_code == 409
    )  # no comments


@respx.mock
def test_submit_runs_the_agent_and_resolves_the_comments(client, env, ai):
    tmp_path, work = env
    ready(tmp_path, work)
    client.post("/api/cards/AB-1/feedback/comments", json={"text": "General note"})
    client.post(
        "/api/cards/AB-1/feedback/comments",
        json={"text": "Guard this", "file": "feature.txt", "line": 1, "code": "toggle"},
    )
    assert client.post("/api/cards/AB-1/feedback/submit").status_code == 202
    data = client.get("/api/cards/AB-1/feedback").json()
    assert data["run"]["state"] == "done", data["run"]["error"]
    assert [c["subject"] for c in data["run"]["commits"]] == [
        "AB-1: address feedback - tweak"
    ]
    assert {c["status"] for c in data["comments"]} == {"resolved"}
    assert {c["resolved_in"] for c in data["comments"]} == {1}
    assert sh(work, "git", "rev-parse", "--abbrev-ref", "HEAD") == BRANCH

    prompt = ai.ai_calls[0][ai.ai_calls[0].index("-p") + 1]
    assert prompt.startswith("Before doing anything else")
    for text in (
        "[general] General note",
        "[feature.txt, line 1] Guard this",
        "Code: `toggle`",
        "1. Do it",
    ):
        assert text in prompt
    assert "shell(git push)" in ai.ai_calls[0]
    # nothing pending now, so another submit is refused
    assert client.post("/api/cards/AB-1/feedback/submit").status_code == 409


@respx.mock
def test_failed_run_keeps_comments_pending(client, env, ai):
    tmp_path, work = env
    ready(tmp_path, work)
    ai.returncode, ai.stderr = 1, "boom"
    client.post("/api/cards/AB-1/feedback/comments", json={"text": "x"})
    client.post("/api/cards/AB-1/feedback/submit")
    data = client.get("/api/cards/AB-1/feedback").json()
    assert data["run"]["state"] == "failed" and "boom" in data["run"]["error"]
    assert [c["status"] for c in data["comments"]] == ["pending"]


@respx.mock
def test_submit_conflicts_when_busy(client, env):
    tmp_path, work = env
    ready(tmp_path, work)
    client.post("/api/cards/AB-1/feedback/comments", json={"text": "x"})
    implementer.ACTIVE_REPOS.add(str(work))
    assert client.post("/api/cards/AB-1/feedback/submit").status_code == 409
    implementer.ACTIVE_REPOS.clear()
    reviewer.ACTIVE.add("AB-1")
    assert client.post("/api/cards/AB-1/feedback/submit").status_code == 409
    reviewer.ACTIVE.clear()


def test_stale_running_run_is_marked_failed(client, env):
    tmp_path, work = env
    impl = make_impl(tmp_path, work)
    feedback.FeedbackStore(db()).create("AB-1", impl)
    run = client.get("/api/cards/AB-1/feedback").json()["run"]
    assert run["state"] == "failed" and "Interrupted" in run["error"]


# ---- run_feedback directly --------------------------------------------------


async def run_fb(tmp_path, work, impl, ai):
    store = feedback.FeedbackStore(db())
    store.add(
        "AB-1", feedback.CommentInput(text="old side", file="a.py", line=4, side="old")
    )
    run = store.create("AB-1", impl)
    feedback.ACTIVE.add("AB-1")
    implementer.ACTIVE_REPOS.add(str(work))
    await feedback.run_feedback(
        store, run, impl, make_card(), "1. Do it", str(work), "copilot", 60, ai
    )
    return store.latest("AB-1")


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"returncode": 1, "stderr": "boom"}, "boom"),
        ({"switch_branch": True}, "left the branch"),
    ],
)
async def test_failures_are_recorded(env, kwargs, message):
    tmp_path, work = env
    run = await run_fb(tmp_path, work, make_impl(tmp_path, work), FakeEditor(**kwargs))
    assert run.state == "failed" and message in run.error
    assert "AB-1" not in feedback.ACTIVE and str(work) not in implementer.ACTIVE_REPOS


async def test_dirty_repo_refused_and_leftovers_and_no_commits_noted(env):
    tmp_path, work = env
    impl = make_impl(tmp_path, work)
    (work / "dirty.txt").write_text("x")
    run = await run_fb(tmp_path, work, impl, FakeEditor())
    assert run.state == "failed" and "uncommitted" in run.error
    (work / "dirty.txt").unlink()
    run = await run_fb(tmp_path, work, impl, FakeEditor(commits=(), leave_dirty=True))
    assert run.state == "done"
    assert any("uncommitted" in n for n in run.notes)
    assert "The AI made no commits." in run.notes


def test_prompt_describes_old_side_lines():
    c = feedback.FeedbackComment(
        id="a", text="why removed?", file="a.py", line=4, side="old", created_at="t"
    )
    assert (
        feedback.format_comment(1, c)
        == "1. [a.py, deleted line in the old version 4] why removed?"
    )
