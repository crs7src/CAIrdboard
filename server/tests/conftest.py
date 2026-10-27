import pytest


@pytest.fixture(autouse=True)
def skills_dir(tmp_path_factory, monkeypatch):
    """Keep tests away from the user's real custom skills."""
    path = tmp_path_factory.mktemp("skills")
    monkeypatch.setenv("SKILLS_DIR", str(path))
    return path
