from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_lists_only_visible_folders_with_git_flag(tmp_path):
    (tmp_path / "beta").mkdir()
    (tmp_path / "Alpha" / ".git").mkdir(parents=True)
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "file.txt").write_text("x")

    body = client.get("/api/fs/dirs", params={"path": str(tmp_path)}).json()

    assert body["path"] == str(tmp_path.resolve())
    assert body["parent"] == str(tmp_path.resolve().parent)
    assert body["dirs"] == [
        {"name": "Alpha", "is_git": True},
        {"name": "beta", "is_git": False},
    ]


def test_defaults_to_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    body = client.get("/api/fs/dirs").json()
    assert body["path"] == str(tmp_path.resolve())


def test_root_has_no_parent():
    assert client.get("/api/fs/dirs", params={"path": "/"}).json()["parent"] is None


def test_missing_path_or_file_or_relative_is_404(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("x")
    for p in (str(tmp_path / "nope"), str(f), "relative/dir"):
        assert client.get("/api/fs/dirs", params={"path": p}).status_code == 404
