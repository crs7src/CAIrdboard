import subprocess
from pathlib import Path

import pytest
import respx
from dbutil import db
from fastapi.testclient import TestClient

from app.core.ai_config import AiConfig, save_ai_config
from app.integrations.jira import Card
from app.main import app, get_runner
from app.stages import implementer, planner
from app.stages.planner import CommandResult, run_command

BASE = "https://example.atlassian.net"
SUMMARY_MARKER = "suitable for a git branch name"


def sh(cwd: Path, *args: str) -> str:
    return subprocess.run(
        args, cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit_file(cwd: Path, name: str, message: str) -> None:
    (cwd / name).write_text(message)
    sh(cwd, "git", "add", name)
    sh(cwd, "git", "commit", "-q", "-m", message)


@pytest.fixture
def repos(tmp_path):
    """A bare 'origin' and a clone of it on main, with an initial commit."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    sh(tmp_path, "git", "init", "-q", "--bare", "-b", "main", str(origin))
    sh(tmp_path, "git", "clone", "-q", str(origin), str(work))
    for cfg in (("user.email", "t@example.com"), ("user.name", "Test")):
        sh(work, "git", "config", *cfg)
    sh(work, "git", "checkout", "-q", "-b", "main")
    commit_file(work, "a.txt", "initial")
    sh(work, "git", "push", "-q", "-u", "origin", "main")
    return origin, work


class FakeAI:
    """Real git, fake copilot: the 'implementation' makes commits in the repo."""

    def __init__(
        self,
        commits=("step 1", "step 2"),
        summary="Add Dark Mode!",
        report="## Summary\nDone",
        returncode=0,
        stderr="",
        leave_dirty=False,
        switch_branch=False,
    ):
        self.commits = commits
        self.summary = summary
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
        prompt = args[args.index("-p") + 1]
        if SUMMARY_MARKER in prompt:
            if self.summary is None:
                return CommandResult(1, "", "boom")
            return CommandResult(0, self.summary, "")
        cwd_path = Path(cwd)
        for i, message in enumerate(self.commits, 1):
            commit_file(cwd_path, f"f{i}.txt", f"AB-1: step {i} - {message}")
        if self.leave_dirty:
            (cwd_path / "dirty.txt").write_text("x")
        if self.switch_branch:
            sh(cwd_path, "git", "checkout", "-q", "main")
        return CommandResult(self.returncode, self.report, self.stderr)

    @property
    def implement_call(self):
        return self.ai_calls[-1]


def make_card(**kw):
    base = {
        "key": "AB-1",
        "summary": "Add a dark mode toggle",
        "status": "DEV In Progress",
        "priority": None,
        "url": "u",
        "project": "AB",
        "description": "Details here",
    }
    return Card(**{**base, **kw})


async def run_impl(tmp_path, work, ai, card=None, plan_text="1. Do it\n2. Test it"):
    store = implementer.ImplementationStore(db())
    run = store.create("AB-1", 1)
    implementer.ACTIVE.add("AB-1")
    implementer.ACTIVE_REPOS.add(str(work))
    await implementer.run_implementation(
        store, run, card or make_card(), plan_text, str(work), "copilot", 60, ai
    )
    return store.latest("AB-1")


# ---- helpers ---------------------------------------------------------------


def test_slugify_and_branch_name():
    assert implementer.slugify("Add Dark Mode!") == "add_dark_mode"
    assert implementer.slugify("  weird -- chars/../x ") == "weird_chars_x"
    assert implementer.slugify("!!!") == ""
    assert len(implementer.slugify("word " * 50)) <= 40
    assert implementer.branch_name("AB-1", "add_dark_mode") == "AB-1_add_dark_mode"
    assert implementer.branch_name("AB-1", "") == "AB-1"


def test_args_allow_tools_but_deny_destructive_and_forbid_questions():
    args = implementer.build_args("copilot", "p")
    assert args[:4] == ["copilot", "-s", "-p", "p"]
    assert "--allow-all-tools" in args and "--no-ask-user" in args
    denied = args[args.index("--deny-tool") + 1 :]
    for tool in (
        "shell(git push)",
        "shell(git reset --hard)",
        "shell(rm -rf)",
    ):
        assert tool in denied
    assert "shell(git checkout)" not in denied
    assert "shell(git switch)" not in denied


def test_prompt_has_skill_plan_branch_and_comments():
    from app.integrations.jira import Comment

    card = make_card(comments=[Comment(author="Ann", created="d", body="Fix label")])
    prompt = implementer.build_prompt(card, "THE PLAN", "AB-1_x", "abc123")
    for text in (
        "never ask",
        "THE PLAN",
        "AB-1_x",
        "abc123",
        "Fix label",
        "AB-1 - Add a dark",
    ):
        assert text.lower() in prompt.lower()
    assert "name: card-implementer" not in prompt


def test_skill_covers_required_rules():
    skill = implementer.load_skill()
    for text in (
        "step <N>",
        "review your own work against the original plan",
        "Never push",
        "unit tests",
        "Co-authored-by",
    ):
        assert text in skill


def test_missing_skill_raises(tmp_path):
    with pytest.raises(implementer.SkillError):
        implementer.load_skill(tmp_path / "nope.md")


# ---- run_implementation ----------------------------------------------------


@pytest.fixture(autouse=True)
def clean_active():
    implementer.ACTIVE.clear()
    implementer.ACTIVE_REPOS.clear()
    yield
    implementer.ACTIVE.clear()
    implementer.ACTIVE_REPOS.clear()


async def test_creates_branch_from_updated_main_and_records_commits(tmp_path, repos):
    origin, work = repos
    # Someone else pushed to origin/main after our clone.
    other = tmp_path / "other"
    sh(tmp_path, "git", "clone", "-q", str(origin), str(other))
    for cfg in (("user.email", "o@example.com"), ("user.name", "O")):
        sh(other, "git", "config", *cfg)
    commit_file(other, "upstream.txt", "upstream change")
    sh(other, "git", "push", "-q", "origin", "main")
    sh(work, "git", "checkout", "-q", "-b", "somewhere-else")

    run = await run_impl(tmp_path, work, FakeAI())

    assert run.state == "completed", run.error
    assert run.branch == "AB-1_add_dark_mode"
    assert run.base_branch == "main"
    assert sh(work, "git", "rev-parse", "--abbrev-ref", "HEAD") == "AB-1_add_dark_mode"
    assert (work / "upstream.txt").exists()  # pulled before branching
    assert [c.subject for c in run.commits] == [
        "AB-1: step 1 - step 1",
        "AB-1: step 2 - step 2",
    ]
    assert run.report == "## Summary\nDone"
    assert run.stage == "done"
    assert (
        "AB-1" not in implementer.ACTIVE and str(work) not in implementer.ACTIVE_REPOS
    )


async def test_branch_name_falls_back_to_card_summary_when_ai_summary_fails(
    tmp_path, repos
):
    _, work = repos
    run = await run_impl(tmp_path, work, FakeAI(summary=None))
    assert run.branch == "AB-1_add_a_dark_mode_toggle"


async def test_uncommitted_changes_are_refused_before_anything_happens(tmp_path, repos):
    _, work = repos
    (work / "a.txt").write_text("edited")
    ai = FakeAI()
    run = await run_impl(tmp_path, work, ai)
    assert run.state == "failed" and "uncommitted changes" in run.error
    assert ai.ai_calls == []
    assert sh(work, "git", "branch", "--list", "AB-1*") == ""


async def test_existing_card_branch_is_reused(tmp_path, repos):
    _, work = repos
    sh(work, "git", "checkout", "-q", "-b", "AB-1_earlier_work")
    commit_file(work, "earlier.txt", "earlier commit")
    sh(work, "git", "checkout", "-q", "main")
    ai = FakeAI()

    run = await run_impl(tmp_path, work, ai)

    assert run.state == "completed", run.error
    assert run.branch == "AB-1_earlier_work"
    assert any("existing branch" in n for n in run.notes)
    assert len(ai.ai_calls) == 1  # no branch-name summary call
    assert next(c.subject for c in run.commits).startswith("AB-1: step 1")


async def test_repo_without_origin_branches_from_local_main_with_note(tmp_path):
    work = tmp_path / "solo"
    work.mkdir()
    sh(work, "git", "init", "-q", "-b", "main")
    for cfg in (("user.email", "t@example.com"), ("user.name", "T")):
        sh(work, "git", "config", *cfg)
    commit_file(work, "a.txt", "initial")
    run = await run_impl(tmp_path, work, FakeAI())
    assert run.state == "completed", run.error
    assert any("No 'origin' remote" in n for n in run.notes)


async def test_master_is_used_when_there_is_no_main(tmp_path):
    work = tmp_path / "old"
    work.mkdir()
    sh(work, "git", "init", "-q", "-b", "master")
    for cfg in (("user.email", "t@example.com"), ("user.name", "T")):
        sh(work, "git", "config", *cfg)
    commit_file(work, "a.txt", "initial")
    run = await run_impl(tmp_path, work, FakeAI())
    assert run.base_branch == "master"


async def test_non_git_directory_fails_clearly(tmp_path):
    folder = tmp_path / "plain"
    folder.mkdir()
    run = await run_impl(tmp_path, folder, FakeAI())
    assert run.state == "failed" and "not a git repository" in run.error


async def test_failure_when_ai_makes_no_commits(tmp_path, repos):
    _, work = repos
    run = await run_impl(tmp_path, work, FakeAI(commits=()))
    assert run.state == "failed" and "without making any commits" in run.error


async def test_failure_when_ai_exits_with_error_keeps_commits(tmp_path, repos):
    _, work = repos
    run = await run_impl(tmp_path, work, FakeAI(returncode=1, stderr="model exploded"))
    assert run.state == "failed" and "model exploded" in run.error
    assert len(run.commits) == 2


async def test_failure_when_ai_leaves_the_branch(tmp_path, repos):
    _, work = repos
    run = await run_impl(tmp_path, work, FakeAI(switch_branch=True))
    assert run.state == "failed" and "left the branch" in run.error


async def test_leftover_uncommitted_changes_add_a_note(tmp_path, repos):
    _, work = repos
    run = await run_impl(tmp_path, work, FakeAI(leave_dirty=True))
    assert run.state == "completed"
    assert any("uncommitted" in n for n in run.notes)


async def test_ai_timeout_and_missing_command_are_recorded(tmp_path, repos):
    _, work = repos

    class Boom(FakeAI):
        def __init__(self, exc):
            super().__init__()
            self.exc = exc

        async def __call__(self, args, cwd, timeout):
            prompt = args[args.index("-p") + 1] if "-p" in args else ""
            if args[0] != "git" and SUMMARY_MARKER not in prompt:
                raise self.exc
            return await super().__call__(args, cwd, timeout)

    run = await run_impl(tmp_path, work, Boom(planner.CommandTimeout()))
    assert run.state == "failed" and "Timed out" in run.error
    sh(work, "git", "checkout", "-q", "main")
    sh(work, "git", "branch", "-q", "-D", "AB-1_add_dark_mode")
    run = await run_impl(tmp_path, work, Boom(planner.CommandNotFound("copilot")))
    assert run.state == "failed" and "Command not found" in run.error


async def test_implementation_prompt_given_to_ai_has_plan_and_rules(tmp_path, repos):
    _, work = repos
    ai = FakeAI()
    await run_impl(tmp_path, work, ai, plan_text="UNIQUE PLAN TEXT")
    prompt = ai.implement_call[ai.implement_call.index("-p") + 1]
    assert "UNIQUE PLAN TEXT" in prompt and "AB-1_add_dark_mode" in prompt
    assert "--no-ask-user" in ai.implement_call


# ---- endpoints -------------------------------------------------------------


@pytest.fixture
def env(tmp_path, monkeypatch, repos):
    _, work = repos
    monkeypatch.setenv("JIRA_BASE_URL", BASE)
    monkeypatch.setenv("JIRA_EMAIL", "me@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok")
    monkeypatch.setenv("JIRA_CREDENTIALS_FILE", str(tmp_path / "jira.json"))
    monkeypatch.setenv("AI_CONFIG_FILE", str(tmp_path / "ai.json"))
    monkeypatch.setenv("PLANS_DIR", str(tmp_path / "plans"))
    monkeypatch.setenv("IMPLEMENTATIONS_DIR", str(tmp_path / "impls"))
    monkeypatch.chdir(tmp_path)
    save_ai_config(tmp_path / "ai.json", AiConfig(project_repos={"AB": str(work)}))
    return tmp_path, work


@pytest.fixture
def ai():
    fake = FakeAI()
    app.dependency_overrides[get_runner] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client(env, ai):
    with TestClient(app) as c:
        yield c


def approve_plan(tmp_path, state="approved", text="1. Do it"):
    store = planner.PlanStore(db())
    plan = store.create("AB-1", "DEV In Progress", None)
    plan.state, plan.plan = state, text
    store.save(plan)


def mock_jira():
    respx.get(f"{BASE}/rest/api/3/issue/AB-1/comment").respond(
        json={"comments": [], "total": 0}
    )
    respx.get(f"{BASE}/rest/api/3/issue/AB-1/changelog").respond(
        json={"values": [], "total": 0, "isLast": True}
    )
    respx.get(f"{BASE}/rest/api/3/issue/AB-1").respond(
        json={
            "key": "AB-1",
            "fields": {
                "summary": "Add a dark mode toggle",
                "status": {"name": "DEV In Progress"},
                "priority": None,
                "description": None,
            },
        }
    )


@respx.mock
def test_start_requires_an_approved_plan(client, env):
    tmp_path, _ = env
    mock_jira()
    assert client.post("/api/cards/AB-1/implementation").status_code == 409
    approve_plan(tmp_path, state="ready")
    assert client.post("/api/cards/AB-1/implementation").status_code == 409


@respx.mock
def test_start_runs_implementation_and_get_returns_it(client, env, ai):
    tmp_path, work = env
    mock_jira()
    approve_plan(tmp_path)

    response = client.post("/api/cards/AB-1/implementation")
    assert response.status_code == 202

    body = client.get("/api/cards/AB-1/implementation").json()
    assert body["state"] == "completed", body["error"]
    assert body["branch"] == "AB-1_add_dark_mode"
    assert body["plan_version"] == 1
    assert [c["subject"] for c in body["commits"]] == [
        "AB-1: step 1 - step 1",
        "AB-1: step 2 - step 2",
    ]
    assert sh(work, "git", "rev-parse", "--abbrev-ref", "HEAD") == "AB-1_add_dark_mode"


def test_get_without_implementation_is_404(client):
    assert client.get("/api/cards/AB-1/implementation").status_code == 404
    assert client.get("/api/cards/bad_key/implementation").status_code == 404


@respx.mock
def test_start_conflicts_when_card_or_repo_is_busy(client, env):
    tmp_path, work = env
    mock_jira()
    approve_plan(tmp_path)
    implementer.ACTIVE_REPOS.add(str(work))
    assert client.post("/api/cards/AB-1/implementation").status_code == 409
    implementer.ACTIVE_REPOS.clear()
    implementer.ACTIVE.add("AB-1")
    assert client.post("/api/cards/AB-1/implementation").status_code == 409


@respx.mock
def test_start_without_a_valid_repo_is_422(client, env):
    tmp_path, _ = env
    mock_jira()
    approve_plan(tmp_path)
    save_ai_config(tmp_path / "ai.json", AiConfig(project_repos={}))
    assert client.post("/api/cards/AB-1/implementation").status_code == 422


def test_stale_running_implementation_is_marked_failed(client, env):
    store = implementer.ImplementationStore(db())
    store.create("AB-1", 1)
    body = client.get("/api/cards/AB-1/implementation").json()
    assert body["state"] == "failed" and "Interrupted" in body["error"]


def test_implementations_listing(env, client):
    assert client.get("/api/implementations").json() == {}
    store = implementer.ImplementationStore(db())
    run = store.create("AB-1", 1)
    run.state = "completed"
    store.save(run)
    assert client.get("/api/implementations").json() == {"AB-1": "completed"}


# ---- automatic review ------------------------------------------------------


def set_auto_review(tmp_path, work, value):
    save_ai_config(
        tmp_path / "ai.json",
        AiConfig(project_repos={"AB": str(work)}, auto_review=value),
    )


@respx.mock
def test_completed_implementation_starts_a_review(client, env):
    from app.stages import reviewer

    tmp_path, _ = env
    mock_jira()
    approve_plan(tmp_path)

    # Only the implementation makes commits; the review finds nothing to fix.
    class OnceAI(FakeAI):
        async def __call__(self, args, cwd, timeout):
            result = await super().__call__(args, cwd, timeout)
            if args[0] != "git" and SUMMARY_MARKER not in args[args.index("-p") + 1]:
                self.commits = ()
            return result

    app.dependency_overrides[get_runner] = lambda: OnceAI()
    assert client.post("/api/cards/AB-1/implementation").status_code == 202
    review = reviewer.ReviewStore(db()).latest("AB-1")
    assert review is not None and review.state == "clean"
    assert implementer.ACTIVE_REPOS == set() and reviewer.ACTIVE == set()


@respx.mock
def test_no_review_when_auto_review_is_off(client, env):
    from app.stages import reviewer

    tmp_path, work = env
    set_auto_review(tmp_path, work, False)
    mock_jira()
    approve_plan(tmp_path)
    assert client.post("/api/cards/AB-1/implementation").status_code == 202
    assert client.get("/api/cards/AB-1/implementation").json()["state"] == "completed"
    assert reviewer.ReviewStore(db()).latest("AB-1") is None


@respx.mock
def test_no_review_after_a_failed_implementation(client, env, ai):
    from app.stages import reviewer

    tmp_path, _ = env
    ai.returncode = 1
    mock_jira()
    approve_plan(tmp_path)
    assert client.post("/api/cards/AB-1/implementation").status_code == 202
    assert client.get("/api/cards/AB-1/implementation").json()["state"] == "failed"
    assert reviewer.ReviewStore(db()).latest("AB-1") is None


@respx.mock
def test_refused_auto_review_keeps_the_implementation_completed(
    client, env, monkeypatch
):
    from fastapi import HTTPException

    from app.routes import implementations
    from app.stages import reviewer

    tmp_path, _ = env

    async def refuse(*args, **kwargs):
        raise HTTPException(409, "busy")

    monkeypatch.setattr(implementations, "_prepare_review", refuse)
    mock_jira()
    approve_plan(tmp_path)
    assert client.post("/api/cards/AB-1/implementation").status_code == 202
    assert client.get("/api/cards/AB-1/implementation").json()["state"] == "completed"
    assert reviewer.ReviewStore(db()).latest("AB-1") is None
