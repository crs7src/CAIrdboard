from app.ai_config import AiConfig, load_ai_config, save_ai_config


def test_names_default_empty_and_old_files_load(tmp_path):
    path = tmp_path / "ai.json"
    path.write_text('{"project_repos": {"ab": "/x"}}')
    config = load_ai_config(path)
    assert config.project_names == {} and config.project_repos == {"AB": "/x"}


def test_names_are_cleaned_and_round_trip(tmp_path):
    path = tmp_path / "ai.json"
    config = AiConfig(project_names={" ab ": " My App ", "cd": "  ", "": "x"})
    assert config.project_names == {"AB": "My App"}
    save_ai_config(path, config)
    assert load_ai_config(path).project_names == {"AB": "My App"}


def test_auto_review_defaults_on_and_old_files_load(tmp_path):
    assert AiConfig().auto_review is True
    path = tmp_path / "ai.json"
    path.write_text('{"project_repos": {"ab": "/x"}}')
    assert load_ai_config(path).auto_review is True


def test_put_ai_config_round_trips_and_keeps_auto_review(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("AI_CONFIG_FILE", str(tmp_path / "ai.json"))
    with TestClient(app) as client:
        statuses = ["Backlog"]
        r = client.put(
            "/api/ai-config",
            json={"eligible_statuses": statuses, "auto_review": False},
        )
        assert r.status_code == 200 and r.json()["auto_review"] is False
        r = client.put("/api/ai-config", json={"eligible_statuses": statuses})
        assert r.json()["auto_review"] is False
        assert client.get("/api/ai-config").json()["auto_review"] is False
        r = client.put(
            "/api/ai-config", json={"eligible_statuses": statuses, "auto_review": True}
        )
        assert r.json()["auto_review"] is True
