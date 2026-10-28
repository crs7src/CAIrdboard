# ruff: noqa: F401, F811 - pytest fixtures imported from test_implementation
import itertools
from pathlib import Path

import pytest
import respx
from fastapi.testclient import TestClient
from test_feedback import ready
from test_implementation import (
    FakeAI,
    approve_plan,
    commit_file,
    env,
    make_card,
    mock_jira,
    repos,
)

from app import deps
from app.core.ai_config import AiConfig, load_ai_config, save_ai_config
from app.main import app, get_runner
from app.stages.planner import CommandResult


class FakeAgentProvider:
    id = "anthropic"
    label = "Anthropic"
    counter = itertools.count(1)

    def __init__(self):
        self.modes = []

    async def run(self, prompt, cwd, timeout, mode="plan"):
        self.modes.append(mode)
        if mode == "summary":
            return CommandResult(0, "add dark mode", "")
        n = next(self.counter)
        commit_file(Path(cwd), f"api{n}.txt", f"AB-1: step {n} - via api")
        return CommandResult(0, "report", "")


@pytest.fixture
def anthropic_project(env):
    tmp_path, work = env
    save_ai_config(
        tmp_path / "ai.json",
        AiConfig(
            project_repos={"AB": str(work)},
            project_providers={"AB": "anthropic"},
            auto_review=False,
        ),
    )
    return env


@pytest.fixture
def client(anthropic_project):
    app.dependency_overrides[get_runner] = lambda: FakeAI()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@respx.mock
def test_missing_key_is_503_for_every_agent_stage(
    client, anthropic_project, monkeypatch
):
    tmp_path, work = anthropic_project
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    mock_jira()
    approve_plan(tmp_path)
    assert client.post("/api/cards/AB-1/implementation").status_code == 503

    from test_review import make_impl

    make_impl(tmp_path, work)
    assert client.post("/api/cards/AB-1/review").status_code == 503
    client.post("/api/cards/AB-1/feedback/comments", json={"text": "fix"})
    assert client.post("/api/cards/AB-1/feedback/submit").status_code == 503


@respx.mock
def test_implementation_runs_on_the_project_provider(
    client, anthropic_project, monkeypatch
):
    tmp_path, _ = anthropic_project
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake = FakeAgentProvider()
    monkeypatch.setattr(deps, "make_provider", lambda *a, **k: fake)
    mock_jira()
    approve_plan(tmp_path)

    assert client.post("/api/cards/AB-1/implementation").status_code == 202
    body = client.get("/api/cards/AB-1/implementation").json()
    assert body["state"] == "completed", body["error"]
    assert body["provider"] == "anthropic"
    assert fake.modes == ["summary", "agent"]


@respx.mock
def test_review_and_feedback_use_the_project_provider(
    client, anthropic_project, monkeypatch
):
    tmp_path, work = anthropic_project
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake = FakeAgentProvider()
    monkeypatch.setattr(deps, "make_provider", lambda *a, **k: fake)
    ready(tmp_path, work)

    assert client.post("/api/cards/AB-1/review").status_code == 202
    review = client.get("/api/cards/AB-1/review").json()
    assert review["state"] == "fixed" and review["provider"] == "anthropic"

    client.post("/api/cards/AB-1/feedback/comments", json={"text": "rename"})
    assert client.post("/api/cards/AB-1/feedback/submit").status_code == 202
    run = client.get("/api/cards/AB-1/feedback").json()["run"]
    assert run["state"] == "done", run["error"]
    assert run["provider"] == "anthropic"
    assert fake.modes == ["agent", "agent"]
