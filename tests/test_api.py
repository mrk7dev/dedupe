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
        json={"source_roots": [str(paths["source"])], "target_roots": [str(paths["target"])]},
    )
    assert res.status_code == 200
    assert "run_id" in res.json()


def test_compare_start_rejects_root_outside_browse_roots(client):
    c, paths = client
    outside = paths["tmp_path"] / "not-mounted"
    outside.mkdir()
    res = c.post(
        "/compare/start",
        json={"source_roots": [str(outside)], "target_roots": [str(paths["target"])]},
    )
    assert res.status_code == 403


def test_compare_start_rejects_unreadable_target(client):
    # Regression: an unreadable target mount previously passed all the
    # /compare/start checks (is_dir() only needs execute on the parent, not
    # read on the target itself) and only failed silently deep inside the
    # background walk, reporting every source file as "missing" instead of
    # a clear permission error.
    c, paths = client
    paths["target"].chmod(0o000)
    try:
        res = c.post(
            "/compare/start",
            json={"source_roots": [str(paths["source"])], "target_roots": [str(paths["target"])]},
        )
        assert res.status_code == 403
        assert str(paths["target"]) in res.json()["detail"]
    finally:
        paths["target"].chmod(0o755)


def test_compare_start_forwards_ignore_cache(client, monkeypatch):
    import app.api as api_module

    calls = []

    def fake_run_compare_background(run_id, source_roots, target_roots, ignore_cache=False):
        calls.append(ignore_cache)
        api_module._compare_running = None  # mirrors the real function's finally block

    monkeypatch.setattr(api_module, "_run_compare_background", fake_run_compare_background)

    c, paths = client
    body = {"source_roots": [str(paths["source"])], "target_roots": [str(paths["target"])]}

    res = c.post("/compare/start", json={**body, "ignore_cache": True})
    assert res.status_code == 200

    res = c.post("/compare/start", json=body)  # omitted — should default to False
    assert res.status_code == 200

    assert calls == [True, False]


def test_compare_start_rejects_nonexistent_root(client):
    c, paths = client
    missing = paths["tmp_path"] / "does-not-exist"
    res = c.post(
        "/compare/start",
        json={"source_roots": [str(missing)], "target_roots": [str(paths["target"])]},
    )
    assert res.status_code == 400


def test_compare_start_accepts_multiple_roots_per_side(client):
    c, paths = client
    source_a = paths["source"] / "a"
    source_b = paths["source"] / "b"
    source_a.mkdir()
    source_b.mkdir()
    res = c.post(
        "/compare/start",
        json={
            "source_roots": [str(source_a), str(source_b)],
            "target_roots": [str(paths["target"])],
        },
    )
    assert res.status_code == 200
    assert "run_id" in res.json()


def test_compare_start_rejects_overlapping_source_roots(client):
    c, paths = client
    nested = paths["source"] / "nested"
    nested.mkdir()
    res = c.post(
        "/compare/start",
        json={
            "source_roots": [str(paths["source"]), str(nested)],
            "target_roots": [str(paths["target"])],
        },
    )
    assert res.status_code == 400
    assert "overlap" in res.json()["detail"]


def test_compare_start_rejects_empty_root_list(client):
    c, paths = client
    res = c.post(
        "/compare/start",
        json={"source_roots": [], "target_roots": [str(paths["target"])]},
    )
    assert res.status_code == 422
