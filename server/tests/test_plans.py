import httpx
import pytest
import respx
from dbutil import db
from fastapi.testclient import TestClient

from app import planner
from app.ai_config import AiConfig, load_ai_config, save_ai_config
from app.jira import adf_to_text
from app.main import app, get_runner

BASE = "https://example.atlassian.net"
REPO_KEY = "AB"


def issue(key="AB-1", status="DEV In Progress", description=None):
    return {
        "key": key,
        "fields": {
            "summary": f"Summary {key}",
            "status": {"name": status},
            "priority": {"name": "High"},
            "description": description,
        },
    }


class FakeRunner:
    def __init__(self, stdout="## Plan\n1. Do it", returncode=0, stderr="", exc=None):
        self.result = planner.CommandResult(returncode, stdout, stderr)
        self.exc = exc
        self.calls: list[tuple[list[str], str, float]] = []

    async def __call__(self, args, cwd, timeout):
        self.calls.append((args, cwd, timeout))
        if self.exc:
            raise self.exc
        return self.result


@pytest.fixture
def env(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("JIRA_BASE_URL", BASE)
    monkeypatch.setenv("JIRA_EMAIL", "me@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok")
    monkeypatch.setenv("JIRA_CREDENTIALS_FILE", str(tmp_path / "jira.json"))
    monkeypatch.setenv("AI_CONFIG_FILE", str(tmp_path / "ai.json"))
    monkeypatch.setenv("PLANS_DIR", str(tmp_path / "plans"))
    monkeypatch.chdir(tmp_path)  # keep any real server/.env out of the test
    save_ai_config(tmp_path / "ai.json", AiConfig(project_repos={REPO_KEY: str(repo)}))
    planner.ACTIVE.clear()
    return tmp_path, repo


@pytest.fixture
def runner():
    r = FakeRunner()
    app.dependency_overrides[get_runner] = lambda: r
    yield r
    app.dependency_overrides.clear()


@pytest.fixture
def client(env, runner):
    with TestClient(app) as c:
        yield c


def jira_comment(text, author="Ann", created="2026-01-02T10:00:00.000+0000"):
    return {
        "author": {"displayName": author},
        "created": created,
        "body": {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": text}]}
            ],
        },
    }


def status_change(from_s, to_s, created, author="Ann"):
    return {
        "created": created,
        "author": {"displayName": author},
        "items": [
            {"field": "status", "fromString": from_s, "toString": to_s},
            {"field": "assignee", "fromString": "x", "toString": "y"},
        ],
    }


def mock_issue(comments=(), history=(), **kwargs):
    key = kwargs.get("key", "AB-1")
    respx.get(f"{BASE}/rest/api/3/issue/{key}/changelog").respond(
        json={"values": list(history), "total": len(history), "isLast": True}
    )
    respx.get(f"{BASE}/rest/api/3/issue/{key}/comment").respond(
        json={"comments": list(comments), "total": len(comments)}
    )
    return respx.get(f"{BASE}/rest/api/3/issue/{key}").respond(json=issue(**kwargs))


# ---- ADF conversion -------------------------------------------------------


def test_adf_to_text():
    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Hello"}]},
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "one"}],
                            }
                        ],
                    },
                ],
            },
        ],
    }
    assert adf_to_text(doc).strip() == "Hello\n\n- one"
    assert adf_to_text(None) == ""


# ---- AI config -------------------------------------------------------------


def test_eligibility_is_case_insensitive_and_excludes_testing():
    config = AiConfig()
    assert config.is_eligible("dev in progress")
    assert config.is_eligible(" Backlog ")
    assert config.is_eligible("Merge Requested")
    assert not config.is_eligible("Testing")
    assert not config.is_eligible("Ready for UAT")


def test_config_validation():
    with pytest.raises(ValueError):
        AiConfig(project_repos={"AB": "relative/path"})
    with pytest.raises(ValueError):
        AiConfig(eligible_statuses=["  "])
    assert AiConfig(project_repos={" ab ": "/x"}).repo_for("AB") == "/x"


def test_load_missing_or_corrupt_config_gives_defaults(tmp_path):
    assert load_ai_config(tmp_path / "none.json") == AiConfig()
    bad = tmp_path / "bad.json"
    bad.write_text("nope")
    assert load_ai_config(bad) == AiConfig()


def test_ai_config_endpoints_roundtrip(client, env):
    body = {"eligible_statuses": ["Backlog"], "project_repos": {"xy": "/tmp"}}
    assert client.put("/api/ai-config", json=body).status_code == 200
    assert client.get("/api/ai-config").json() == {
        "eligible_statuses": ["Backlog"],
        "project_repos": {"XY": "/tmp"},
        "project_names": {},
    }
    named = {**body, "project_names": {"xy": "Xy app"}}
    assert client.put("/api/ai-config", json=named).status_code == 200
    assert client.get("/api/ai-config").json()["project_names"] == {"XY": "Xy app"}
    assert client.put("/api/ai-config", json=body).status_code == 200
    assert client.get("/api/ai-config").json()["project_names"] == {"XY": "Xy app"}
    gone = {**body, "project_repos": {}}
    client.put("/api/ai-config", json=gone)
    assert client.get("/api/ai-config").json()["project_names"] == {}
    bad = client.put("/api/ai-config", json={"project_repos": {"A": "rel"}})
    assert bad.status_code == 422


# ---- prompt / args ----------------------------------------------------------


def _card(**kw):
    from app.jira import Card

    base = {
        "key": "AB-1",
        "summary": "Do thing",
        "status": "Backlog",
        "priority": None,
        "url": "u",
        "project": "AB",
        "description": "Details here",
        "comments": [],
    }
    return Card(**{**base, **kw})


def test_prompt_includes_card_and_feedback():
    prev = planner.Plan(
        card_key="AB-1",
        version=1,
        state="rejected",
        jira_status="Backlog",
        plan="OLD PLAN",
        created_at="t",
        updated_at="t",
    )
    prompt = planner.build_prompt(_card(), prev, "Too vague")
    for text in ("AB-1", "Do thing", "Details here", "OLD PLAN", "Too vague"):
        assert text in prompt
    assert "OLD PLAN" not in planner.build_prompt(_card(), prev, None)


def _comments():
    from app.jira import Comment

    return [
        Comment(author="Ann", created="d1", body="Button is the wrong color"),
        Comment(author="Bob", created="d2", body="Also fix the label"),
    ]


def test_prompt_includes_comments_in_order():
    prompt = planner.build_prompt(_card(comments=_comments()), None, None)
    assert prompt.index("Button is the wrong color") < prompt.index(
        "Also fix the label"
    )
    assert "Ann (d1)" in prompt and "Bob (d2)" in prompt


def test_prompt_notes_when_there_are_no_comments():
    assert "(no comments)" in planner.build_prompt(_card(), None, None)


def test_reopened_uses_comment_focused_skill_mode():
    prompt = planner.build_prompt(
        _card(status="Reopened", comments=_comments()), None, None
    )
    assert "COMMENTS are the source of truth" in prompt
    assert "Plan the work from scratch" not in prompt
    assert "name: card-planner" not in prompt  # frontmatter is stripped


def test_other_statuses_use_from_scratch_mode():
    for status in ("Backlog", "DEV In Progress", "Merge Requested"):
        prompt = planner.build_prompt(_card(status=status), None, None)
        assert "Plan the work from scratch" in prompt
        assert "COMMENTS are the source of truth" not in prompt


def test_reopened_detection_is_case_and_hyphen_insensitive():
    assert planner.is_reopened(" re-opened ") and planner.is_reopened("REOPENED")
    assert not planner.is_reopened("In Progress")


def test_previously_reopened_card_in_other_status_uses_rework_mode():
    card = _card(status="Merge Requested", reopened=True, comments=_comments())
    prompt = planner.build_prompt(card, None, None)
    assert "COMMENTS are the source of truth" in prompt
    assert "Plan the work from scratch" not in prompt


def test_rework_prompt_marks_new_comments_and_lists_history():
    from app.jira import StatusChange

    comments = _comments()
    comments[1].after_reopen = True
    history = [
        StatusChange(
            from_status="Done", to_status="Reopened", when="2026-01-01", author="Ann"
        )
    ]
    card = _card(
        status="In Progress", reopened=True, comments=comments, status_history=history
    )
    prompt = planner.build_prompt(card, None, None)
    assert "Done -> Reopened" in prompt
    comments_block = prompt.split("Comments (oldest first):")[1]
    assert comments_block.count("[AFTER LATEST REOPEN]") == 1
    assert comments_block.index("Also fix the label") > comments_block.index(
        "[AFTER LATEST REOPEN]"
    )


def test_never_reopened_card_has_no_history_or_markers():
    comments = _comments()
    comments[0].after_reopen = True
    prompt = planner.build_prompt(_card(comments=comments), None, None)
    assert "AFTER LATEST REOPEN" not in prompt.split("Comments (oldest first):")[1]
    assert "This card has been Reopened" not in prompt


def test_missing_or_incomplete_skill_raises(tmp_path):
    with pytest.raises(planner.SkillError):
        planner.load_skill(False, tmp_path / "nope.md")
    partial = tmp_path / "s.md"
    partial.write_text("intro\n## Mode: default\nbody")
    assert "body" in planner.load_skill(False, partial)
    with pytest.raises(planner.SkillError):
        planner.load_skill(True, partial)


@respx.mock
def test_card_detail_includes_comments_and_pages_through_them(client):
    respx.get(f"{BASE}/rest/api/3/issue/AB-1").respond(json=issue())
    respx.get(f"{BASE}/rest/api/3/issue/AB-1/changelog").respond(
        json={"values": [], "total": 0, "isLast": True}
    )
    route = respx.get(f"{BASE}/rest/api/3/issue/AB-1/comment")
    route.side_effect = [
        httpx.Response(200, json={"comments": [jira_comment("one")], "total": 2}),
        httpx.Response(
            200, json={"comments": [jira_comment("two", "Bob")], "total": 2}
        ),
    ]
    body = client.get("/api/cards/AB-1").json()
    assert [(c["author"], c["body"]) for c in body["comments"]] == [
        ("Ann", "one"),
        ("Bob", "two"),
    ]
    assert route.call_count == 2


@respx.mock
def test_history_detects_past_reopen_and_marks_newer_comments(client):
    mock_issue(
        status="Merge Requested",
        comments=[
            jira_comment("before", created="2026-01-01T09:00:00.000+0000"),
            jira_comment("after", created="2026-01-03T09:00:00.000+0000"),
        ],
        history=[
            status_change("Done", "Reopened", "2026-01-02T09:00:00.000+0000"),
            status_change("Reopened", "In Progress", "2026-01-02T12:00:00.000+0000"),
            status_change(
                "In Progress", "Merge Requested", "2026-01-04T09:00:00.000+0000"
            ),
        ],
    )
    body = client.get("/api/cards/AB-1").json()
    assert body["reopened"] is True
    assert body["last_reopened_at"] == "2026-01-02T09:00:00.000+0000"
    assert [c["after_reopen"] for c in body["comments"]] == [False, True]
    assert [(h["from_status"], h["to_status"]) for h in body["status_history"]] == [
        ("Done", "Reopened"),
        ("Reopened", "In Progress"),
        ("In Progress", "Merge Requested"),
    ]


@respx.mock
def test_never_reopened_card_is_not_flagged(client):
    mock_issue(
        history=[status_change("To Do", "In Progress", "2026-01-02T09:00:00.000+0000")]
    )
    body = client.get("/api/cards/AB-1").json()
    assert body["reopened"] is False and body["last_reopened_at"] is None


@respx.mock
def test_currently_reopened_card_is_flagged_even_without_history(client):
    mock_issue(status="Reopened")
    assert client.get("/api/cards/AB-1").json()["reopened"] is True


@respx.mock
def test_changelog_is_paged(client):
    respx.get(f"{BASE}/rest/api/3/issue/AB-1").respond(json=issue())
    respx.get(f"{BASE}/rest/api/3/issue/AB-1/comment").respond(
        json={"comments": [], "total": 0}
    )
    route = respx.get(f"{BASE}/rest/api/3/issue/AB-1/changelog")
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "values": [status_change("A", "B", "2026-01-01T00:00:00.000+0000")],
                "total": 2,
                "isLast": False,
            },
        ),
        httpx.Response(
            200,
            json={
                "values": [
                    status_change("B", "Reopened", "2026-01-02T00:00:00.000+0000")
                ],
                "total": 2,
                "isLast": True,
            },
        ),
    ]
    assert client.get("/api/cards/AB-1").json()["reopened"] is True
    assert route.call_count == 2


@respx.mock
def test_reopened_card_prompt_sent_to_ai_contains_comments(client, runner):
    mock_issue(status="Reopened", comments=[jira_comment("Please fix X")])
    assert client.post("/api/cards/AB-1/plan").status_code == 202
    prompt = runner.calls[0][0][runner.calls[0][0].index("-p") + 1]
    assert "Please fix X" in prompt and "COMMENTS are the source of truth" in prompt


def test_args_are_read_only_and_shell_free():
    args = planner.build_args("copilot", "p")
    assert args[:4] == ["copilot", "-s", "-p", "p"]
    assert "--available-tools" in args
    tools = args[args.index("--available-tools") + 1 : args.index("--allow-tool")]
    assert tools == ["view", "grep", "glob"]
    assert "shell" not in args and "write" not in args


# ---- endpoints ---------------------------------------------------------------


@respx.mock
def test_card_detail_reports_eligibility_and_repo(client):
    mock_issue(status="Testing")
    body = client.get("/api/cards/AB-1").json()
    assert body["eligible"] is False
    assert body["repo_configured"] is True
    assert body["project"] == "AB"


@respx.mock
def test_card_not_found_and_bad_key(client):
    respx.get(f"{BASE}/rest/api/3/issue/AB-9").respond(404)
    assert client.get("/api/cards/AB-9").status_code == 404
    assert client.get("/api/cards/not-a-key").status_code == 404
    assert client.get("/api/cards/..%2Fetc").status_code == 404


@respx.mock
def test_create_plan_runs_ai_and_stores_result(client, runner, env):
    _, repo = env
    mock_issue(description={"type": "doc", "content": []})
    response = client.post("/api/cards/AB-1/plan")
    assert response.status_code == 202
    assert response.json()["state"] == "running"

    plan = client.get("/api/cards/AB-1/plan").json()
    assert plan["state"] == "ready"
    assert plan["plan"] == "## Plan\n1. Do it"
    assert plan["version"] == 1
    assert plan["jira_status"] == "DEV In Progress"
    _args, cwd, _timeout = runner.calls[0]
    assert cwd == str(repo)
    assert planner.PlanStore(db()).latest("AB-1").version == 1
    assert planner.ACTIVE == set()


@respx.mock
@pytest.mark.parametrize("status", ["Testing", "Ready for UAT", "Ready for Prod"])
def test_ineligible_status_is_rejected(client, runner, status):
    mock_issue(status=status)
    response = client.post("/api/cards/AB-1/plan")
    assert response.status_code == 409
    assert status in response.json()["detail"]
    assert runner.calls == []
    assert client.get("/api/cards/AB-1/plan").status_code == 404


@respx.mock
@pytest.mark.parametrize("status", ["Backlog", "Ready to Play", "Merge Requested"])
def test_eligible_statuses_accepted(client, status):
    mock_issue(status=status)
    assert client.post("/api/cards/AB-1/plan").status_code == 202


@respx.mock
def test_missing_repo_mapping(client, runner):
    mock_issue(key="ZZ-1")
    response = client.post("/api/cards/ZZ-1/plan")
    assert response.status_code == 422
    assert "ZZ" in response.json()["detail"]
    assert runner.calls == []


@respx.mock
def test_repo_path_must_exist(client, env):
    tmp_path, _ = env
    save_ai_config(
        tmp_path / "ai.json", AiConfig(project_repos={"AB": str(tmp_path / "gone")})
    )
    mock_issue()
    assert client.post("/api/cards/AB-1/plan").status_code == 422


@respx.mock
@pytest.mark.parametrize(
    "runner_kwargs, expected",
    [
        ({"returncode": 1, "stdout": "", "stderr": "boom"}, "boom"),
        ({"stdout": "   "}, "no output"),
        ({"exc": planner.CommandTimeout()}, "Timed out"),
        ({"exc": planner.CommandNotFound("copilot")}, "not found"),
        ({"exc": RuntimeError("kaput")}, "kaput"),
    ],
)
def test_failures_are_recorded(client, runner, runner_kwargs, expected):
    runner.__init__(**runner_kwargs)
    mock_issue()
    client.post("/api/cards/AB-1/plan")
    plan = client.get("/api/cards/AB-1/plan").json()
    assert plan["state"] == "failed"
    assert expected in plan["error"]
    assert planner.ACTIVE == set()


@respx.mock
def test_conflict_while_running(client, runner, env):
    mock_issue()
    planner.ACTIVE.add("AB-1")
    assert client.post("/api/cards/AB-1/plan").status_code == 409
    assert runner.calls == []


@respx.mock
def test_stale_running_plan_is_recovered(client, env):
    store = planner.PlanStore(db())
    store.create("AB-1", "Backlog", None)  # 'running' but nothing is active
    plan = client.get("/api/cards/AB-1/plan").json()
    assert plan["state"] == "failed"
    assert "Interrupted" in plan["error"]
    mock_issue()
    assert client.post("/api/cards/AB-1/plan").status_code == 202


@respx.mock
def test_approve_and_reject_flow(client):
    mock_issue()
    client.post("/api/cards/AB-1/plan")
    assert client.post("/api/cards/AB-1/plan/approve").json()["state"] == "approved"
    assert client.post("/api/cards/AB-1/plan/reject").status_code == 409

    client.post("/api/cards/AB-1/plan")  # regenerate -> version 2
    assert client.post("/api/cards/AB-1/plan/reject").json()["state"] == "rejected"
    assert client.get("/api/cards/AB-1/plan").json()["version"] == 2


def test_decide_without_plan(client):
    assert client.post("/api/cards/AB-1/plan/approve").status_code == 404


@respx.mock
def test_regenerate_with_feedback_passes_it_to_the_ai(client, runner):
    mock_issue()
    client.post("/api/cards/AB-1/plan")
    client.post("/api/cards/AB-1/plan/reject")
    response = client.post(
        "/api/cards/AB-1/plan", json={"feedback": "  Split into two steps  "}
    )
    assert response.json()["feedback"] == "Split into two steps"
    prompt = runner.calls[-1][0][3]
    assert "Split into two steps" in prompt
    assert "## Plan" in prompt  # previous plan included


@respx.mock
def test_blank_feedback_is_ignored(client):
    mock_issue()
    response = client.post("/api/cards/AB-1/plan", json={"feedback": "   "})
    assert response.json()["feedback"] is None


@respx.mock
def test_plan_states_listing(client):
    mock_issue()
    client.post("/api/cards/AB-1/plan")
    assert client.get("/api/plans").json() == {"AB-1": "ready"}


def test_plans_listing_empty(client):
    assert client.get("/api/plans").json() == {}


def test_plan_requires_jira(client, monkeypatch):
    monkeypatch.delenv("JIRA_API_TOKEN")
    assert client.post("/api/cards/AB-1/plan").status_code == 503


def test_store_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError):
        planner.PlanStore(db()).latest("../evil")
