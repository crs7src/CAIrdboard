import json
import stat

import pytest
from fastapi.testclient import TestClient

from app.ai.errors import ProviderError
from app.core.ai_config import AiConfig, load_ai_config, save_ai_config
from app.main import app

SECRET = "sk-ant-very-secret"


@pytest.fixture
def ai_env(tmp_path, monkeypatch, ai_credentials_file):
    monkeypatch.setenv("AI_CONFIG_FILE", str(tmp_path / "ai.json"))
    monkeypatch.chdir(tmp_path)  # keep any real server/.env out of the test
    return tmp_path


@pytest.fixture
def verify(monkeypatch):
    calls = []

    async def fake(provider_id, key, model):
        calls.append((provider_id, key, model))
        if key == "bad":
            raise ProviderError("Anthropic did not accept the API key.")

    monkeypatch.setattr("app.routes.ai_providers.verify_key", fake)
    return calls


@pytest.fixture
def client(ai_env, verify):
    with TestClient(app) as c:
        yield c


def by_id(client):
    return {p["id"]: p for p in client.get("/api/ai/providers").json()}


def test_lists_providers_with_copilot_configured(client):
    providers = by_id(client)
    assert set(providers) == {"copilot", "anthropic", "gemini"}
    assert providers["copilot"]["configured"] is True
    assert providers["copilot"]["supports_agent"] is True
    assert [p["is_default"] for p in providers.values()] == [True, False, False]
    assert providers["anthropic"]["configured"] is False
    assert providers["anthropic"]["model"]


def test_save_key_verifies_stores_0600_and_never_returns_it(
    client, ai_credentials_file
):
    r = client.put("/api/ai/providers/anthropic/credentials", json={"api_key": SECRET})
    assert r.status_code == 200
    assert r.json()["configured"] is True
    assert SECRET not in r.text
    assert SECRET not in client.get("/api/ai/providers").text
    assert json.loads(ai_credentials_file.read_text()) == {"anthropic_api_key": SECRET}
    assert stat.S_IMODE(ai_credentials_file.stat().st_mode) == 0o600
    assert by_id(client)["anthropic"]["configured"] is True


def test_failed_verification_saves_nothing(client, ai_credentials_file):
    r = client.put("/api/ai/providers/anthropic/credentials", json={"api_key": "bad"})
    assert r.status_code == 400
    assert not ai_credentials_file.exists()
    assert by_id(client)["anthropic"]["configured"] is False


def test_model_only_update_keeps_key_and_is_verified_with_it(client, verify, ai_env):
    client.put("/api/ai/providers/gemini/credentials", json={"api_key": "g-key"})
    r = client.put("/api/ai/providers/gemini/credentials", json={"model": "gemini-x"})
    assert r.status_code == 200
    assert r.json()["model"] == "gemini-x"
    assert r.json()["configured"] is True
    assert verify[-1] == ("gemini", "g-key", "gemini-x")
    assert load_ai_config(ai_env / "ai.json").provider_models == {"gemini": "gemini-x"}


def test_model_only_without_key_is_saved_unverified(client, verify):
    r = client.put("/api/ai/providers/gemini/credentials", json={"model": "m"})
    assert r.status_code == 200 and r.json()["configured"] is False
    assert verify == []


def test_copilot_model_is_saved_listed_and_reset(client, ai_env, verify):
    copilot = by_id(client)["copilot"]
    assert copilot["models"] and copilot["model"] is None
    r = client.put("/api/ai/providers/copilot/credentials", json={"model": "gpt-5"})
    assert r.status_code == 200 and r.json()["model"] == "gpt-5"
    assert load_ai_config(ai_env / "ai.json").provider_models == {"copilot": "gpt-5"}
    assert verify == []
    r = client.put("/api/ai/providers/copilot/credentials", json={"model": ""})
    assert r.json()["model"] is None
    assert load_ai_config(ai_env / "ai.json").provider_models == {}


async def test_runner_adds_model_flag_for_copilot_only():
    from app.ai import with_model
    from app.stages.planner import CommandResult

    seen = []

    async def base(args, cwd, timeout):
        seen.append(args)
        return CommandResult(0, "", "")

    await with_model(base, "copilot", "gpt-5")(["copilot", "-s"], ".", 1)
    await with_model(base, "copilot", "gpt-5")(["git", "log"], ".", 1)
    assert with_model(base, "copilot", None) is base
    assert seen == [["copilot", "--model", "gpt-5", "-s"], ["git", "log"]]


@pytest.mark.parametrize(
    ("pid", "body"),
    [
        ("nope", {"api_key": "k"}),
        ("copilot", {"api_key": "k"}),
        ("anthropic", {}),
        ("anthropic", {"api_key": "  "}),
    ],
)
def test_invalid_credentials_input_is_422(client, pid, body):
    assert (
        client.put(f"/api/ai/providers/{pid}/credentials", json=body).status_code == 422
    )


def test_delete_removes_saved_key_only(client, ai_credentials_file):
    client.put("/api/ai/providers/anthropic/credentials", json={"api_key": SECRET})
    client.put("/api/ai/providers/gemini/credentials", json={"api_key": "g-key"})
    r = client.delete("/api/ai/providers/anthropic/credentials")
    assert r.status_code == 200 and r.json()["configured"] is False
    assert json.loads(ai_credentials_file.read_text()) == {"gemini_api_key": "g-key"}


def test_env_key_counts_as_configured_and_survives_delete(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert by_id(client)["gemini"]["configured"] is True
    assert client.delete("/api/ai/providers/gemini/credentials").json()["configured"]


def test_check_503_when_unconfigured_502_on_failure_ok_otherwise(client, monkeypatch):
    assert client.get("/api/ai/providers/anthropic/check").status_code == 503
    client.put("/api/ai/providers/anthropic/credentials", json={"api_key": SECRET})
    assert client.get("/api/ai/providers/anthropic/check").json() == {"ok": True}

    async def boom(*_):
        raise ProviderError("Anthropic is having problems (HTTP 500).")

    monkeypatch.setattr("app.routes.ai_providers.verify_key", boom)
    r = client.get("/api/ai/providers/anthropic/check")
    assert r.status_code == 502
    assert SECRET not in r.text


def test_default_provider_and_ai_config_preserves_provider_fields(client, ai_env):
    assert client.put("/api/ai/default", json={"provider": "gemini"}).status_code == 200
    assert client.put("/api/ai/default", json={"provider": "x"}).status_code == 422
    save_ai_config(
        ai_env / "ai.json",
        AiConfig(
            project_repos={"AB": "/tmp"},
            default_provider="gemini",
            project_providers={"AB": "anthropic"},
            provider_models={"gemini": "m"},
        ),
    )
    # An older client sends only the old fields: the provider settings stay.
    body = {"eligible_statuses": ["Backlog"], "project_repos": {"ab": "/tmp"}}
    assert client.put("/api/ai-config", json=body).status_code == 200
    saved = load_ai_config(ai_env / "ai.json")
    assert saved.default_provider == "gemini"
    assert saved.project_providers == {"AB": "anthropic"}
    assert saved.provider_models == {"gemini": "m"}
    # Removing a project drops its provider.
    client.put("/api/ai-config", json={**body, "project_repos": {}})
    assert load_ai_config(ai_env / "ai.json").project_providers == {}


def test_ai_config_validation_rejects_unknown_ids():
    with pytest.raises(ValueError):
        AiConfig(default_provider="x")
    with pytest.raises(ValueError):
        AiConfig(project_providers={"AB": "x"})
    assert AiConfig(project_providers={"ab": "Gemini"}).project_providers == {
        "AB": "gemini"
    }
