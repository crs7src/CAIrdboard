import pytest
import respx
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


def mock_issue(**kwargs):
    key = kwargs.get("key", "AB-1")
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
    }
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
    tmp_path, repo = env
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
    assert (tmp_path / "plans" / "AB-1" / "1.json").exists()
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
    tmp_path, _ = env
    store = planner.PlanStore(tmp_path / "plans")
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
        planner.PlanStore(tmp_path).latest("../evil")
