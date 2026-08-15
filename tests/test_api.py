import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.api import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "dedupe.db")
    monkeypatch.setattr(config, "BROWSE_ROOTS", [source.resolve(), target.resolve()])
    db.init_db()

    return TestClient(app), {"source": source, "target": target, "tmp_path": tmp_path}


def test_compare_start_succeeds_when_both_roots_in_browse_roots(client):
    c, paths = client
    res = c.post(
        "/compare/start",
        json={"source_root": str(paths["source"]), "target_root": str(paths["target"])},
    )
    assert res.status_code == 200
    assert "run_id" in res.json()


def test_compare_start_rejects_root_outside_browse_roots(client):
    c, paths = client
    outside = paths["tmp_path"] / "not-mounted"
    outside.mkdir()
    res = c.post(
        "/compare/start",
        json={"source_root": str(outside), "target_root": str(paths["target"])},
    )
    assert res.status_code == 403


def test_compare_start_rejects_nonexistent_root(client):
    c, paths = client
    missing = paths["tmp_path"] / "does-not-exist"
    res = c.post(
        "/compare/start",
        json={"source_root": str(missing), "target_root": str(paths["target"])},
    )
    assert res.status_code == 400
