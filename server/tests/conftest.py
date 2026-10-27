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
