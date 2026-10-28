from fastapi.testclient import TestClient

from app.main import app


def test_archive_add_list_and_remove_are_idempotent():
    with TestClient(app) as client:
        assert client.get("/api/archive").json() == []
        assert client.put("/api/cards/AB-2/archive").status_code == 204
        assert client.put("/api/cards/AB-1/archive").status_code == 204
        assert client.put("/api/cards/AB-1/archive").status_code == 204
        assert client.get("/api/archive").json() == ["AB-1", "AB-2"]
        assert client.delete("/api/cards/AB-1/archive").status_code == 204
        assert client.delete("/api/cards/AB-1/archive").status_code == 204
        assert client.get("/api/archive").json() == ["AB-2"]


def test_archive_rejects_an_invalid_key():
    with TestClient(app) as client:
        assert client.put("/api/cards/bad/archive").status_code == 404
        assert client.delete("/api/cards/bad/archive").status_code == 404
