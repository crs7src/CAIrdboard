import pytest


@pytest.fixture(autouse=True)
def skills_dir(tmp_path_factory, monkeypatch):
    """Keep tests away from the user's real custom skills."""
    path = tmp_path_factory.mktemp("skills")
    monkeypatch.setenv("SKILLS_DIR", str(path))
    return path


@pytest.fixture(autouse=True)
def db_file(tmp_path_factory, monkeypatch):
    """Every test gets its own empty database."""
    path = tmp_path_factory.mktemp("db") / "cairdboard.db"
    monkeypatch.setenv("DB_FILE", str(path))
    return path


@pytest.fixture(autouse=True)
def ai_credentials_file(tmp_path_factory, monkeypatch):
    """Never read or write the user's real AI API keys."""
    path = tmp_path_factory.mktemp("aicreds") / "ai_credentials.json"
    monkeypatch.setenv("AI_CREDENTIALS_FILE", str(path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return path


@pytest.fixture(autouse=True)
def no_jira_warm_up(monkeypatch):
    """The startup warm-up must never call Jira from tests."""
    import app.main

    async def skip():
        return None

    monkeypatch.setattr(app.main, "warm_jira_projects", skip)
