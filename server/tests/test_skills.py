import pytest
from fastapi.testclient import TestClient

from app import feedback, implementer, planner, reviewer, skills, tester
from app.main import app

PLANNER_OK = "intro\n## Mode: default\nA\n## Mode: reopened\nB\n"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_defaults_are_used_when_nothing_is_customised(client):
    data = client.get("/api/skills").json()
    assert [s["step"] for s in data] == [
        "planner",
        "implementer",
        "reviewer",
        "feedback",
        "tester",
    ]
    for s in data:
        assert s["customized"] is False
        assert s["content"] == s["default_content"] != ""


def test_override_replaces_the_default_in_each_loader(client):
    client.put("/api/skills/planner", json={"content": PLANNER_OK})
    client.put(
        "/api/skills/implementer", json={"content": "---\nname: x\n---\nMY IMPL"}
    )
    client.put("/api/skills/reviewer", json={"content": "MY REVIEW"})
    client.put("/api/skills/feedback", json={"content": "MY FEEDBACK"})
    client.put("/api/skills/tester", json={"content": "MY TESTER"})
    assert "A" in planner.load_skill(False) and "intro" in planner.load_skill(False)
    assert planner.load_skill(True).endswith("B")
    assert implementer.load_skill() == "MY IMPL"
    assert reviewer.load_skill() == "MY REVIEW"
    assert feedback.load_skill() == "MY FEEDBACK"
    assert tester.load_skill() == "MY TESTER"
    assert all(s["customized"] for s in client.get("/api/skills").json())


def test_reset_restores_the_default(client):
    client.put("/api/skills/reviewer", json={"content": "MY REVIEW"})
    res = client.delete("/api/skills/reviewer")
    assert res.json()["customized"] is False
    assert reviewer.load_skill() != "MY REVIEW"
    assert client.delete("/api/skills/reviewer").status_code == 200


def test_invalid_overrides_are_rejected(client):
    assert (
        client.put("/api/skills/reviewer", json={"content": "  \n"}).status_code == 422
    )
    res = client.put("/api/skills/planner", json={"content": "## Mode: default\nonly"})
    assert res.status_code == 422
    assert "reopened" in res.json()["detail"]
    assert client.get("/api/skills").json()[0]["customized"] is False


def test_unknown_step_is_404(client):
    assert client.put("/api/skills/nope", json={"content": "x"}).status_code == 404
    assert client.delete("/api/skills/nope").status_code == 404


def test_prompts_always_start_with_the_agents_instructions(client):
    client.put("/api/skills/reviewer", json={"content": "MY REVIEW"})
    client.put("/api/skills/implementer", json={"content": "MY IMPL"})
    client.put("/api/skills/planner", json={"content": PLANNER_OK})
    client.put("/api/skills/feedback", json={"content": "MY FEEDBACK"})
    client.put("/api/skills/tester", json={"content": "MY TESTER"})
    from test_plans import _card

    card = _card()
    impl = implementer.Implementation(
        card_key="AB-1",
        version=1,
        plan_version=1,
        state="completed",
        branch="b",
        base_commit="abc",
        created_at="t",
        updated_at="t",
    )
    prompts = [
        feedback.build_prompt(card, "plan", impl, []),
        tester.build_prompt(card, "plan", impl),
        planner.build_prompt(card, None, None),
        implementer.build_prompt(card, "plan", "br", "abc"),
        reviewer.build_prompt(
            card,
            "plan",
            implementer.Implementation(
                card_key="AB-1",
                version=1,
                plan_version=1,
                state="completed",
                branch="b",
                base_commit="abc",
                created_at="t",
                updated_at="t",
            ),
        ),
    ]
    for prompt in prompts:
        assert prompt.startswith(skills.AGENTS_PREAMBLE)
        assert "AGENTS.md" in prompt and ".github/copilot-instructions.md" in prompt
