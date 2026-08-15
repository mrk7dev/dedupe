from pathlib import Path

import pytest

from app import compare, compare_copy, config, db


@pytest.fixture
def env(tmp_path, monkeypatch):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    db_path = tmp_path / "dedupe.db"

    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "WORKERS", 2)
    monkeypatch.setattr(config, "BROWSE_ROOTS", [source.resolve(), target.resolve()])

    return {"source": source, "target": target}


def _run(source: Path, target: Path) -> int:
    db.init_db()
    run_id = compare.create_run(str(source), str(target))
    compare.run_compare(run_id, str(source), str(target))
    return run_id


def test_matched_source_only_target_only_categorized(env):
    source, target = env["source"], env["target"]

    shared = b"identical content" * 500
    (source / "shared.bin").write_bytes(shared)
    (target / "shared_renamed.bin").write_bytes(shared)  # same content, different name/path

    (source / "missing.bin").write_bytes(b"only on source" * 100)
    (target / "extra.bin").write_bytes(b"only on target" * 100)

    run_id = _run(source, target)

    with db.connection() as conn:
        run = conn.execute("SELECT * FROM compare_runs WHERE id = ?", (run_id,)).fetchone()
        assert run["phase"] == "ready"
        assert run["error"] is None

        results = compare.get_results(conn, run_id)

    by_name = {r["name"]: r for r in results}
    assert by_name["shared.bin"]["category"] == "matched"
    assert by_name["missing.bin"]["category"] == "source_only"
    assert by_name["extra.bin"]["category"] == "target_only"
    # matched content shows once (source side), not duplicated for the target copy
    assert "shared_renamed.bin" not in by_name


def test_same_size_different_content_not_matched(env):
    source, target = env["source"], env["target"]
    (source / "a.bin").write_bytes(b"AAAA" * 100)
    (target / "b.bin").write_bytes(b"BBBB" * 100)  # same size, different bytes

    run_id = _run(source, target)
    with db.connection() as conn:
        results = compare.get_results(conn, run_id)

    by_name = {r["name"]: r for r in results}
    assert by_name["a.bin"]["category"] == "source_only"
    assert by_name["b.bin"]["category"] == "target_only"


def test_copy_selected_writes_additively_and_renames_on_conflict(env):
    source, target = env["source"], env["target"]
    (source / "a.bin").write_bytes(b"payload" * 100)
    (target / "a.bin").write_bytes(b"unrelated existing target file")  # name collides, content differs

    run_id = _run(source, target)
    with db.connection() as conn:
        row = conn.execute(
            "SELECT id FROM compare_files WHERE run_id = ? AND category = 'source_only'", (run_id,)
        ).fetchone()
        assert row is not None
        file_id = row["id"]

    original_target_content = (target / "a.bin").read_bytes()

    compare_copy.copy_selected(run_id, [file_id])

    # existing target file untouched
    assert (target / "a.bin").read_bytes() == original_target_content
    # incoming copy auto-renamed rather than overwriting
    renamed = target / "a.copy.bin"
    assert renamed.exists()
    assert renamed.read_bytes() == b"payload" * 100

    with db.connection() as conn:
        run = conn.execute("SELECT * FROM compare_runs WHERE id = ?", (run_id,)).fetchone()
        assert run["copy_phase"] == "done"
        assert run["copy_done"] == 1
        assert run["copy_total"] == 1

        updated = conn.execute("SELECT category FROM compare_files WHERE id = ?", (file_id,)).fetchone()
        assert updated["category"] == "matched"

        action = conn.execute("SELECT * FROM copy_actions WHERE run_id = ?", (run_id,)).fetchone()
        assert action["status"] == "done"
        assert action["dest_path"] == str(renamed)


def test_copy_refuses_when_target_not_writable(env):
    source, target = env["source"], env["target"]
    (source / "a.bin").write_bytes(b"payload")

    run_id = _run(source, target)
    with db.connection() as conn:
        row = conn.execute(
            "SELECT id FROM compare_files WHERE run_id = ? AND category = 'source_only'", (run_id,)
        ).fetchone()
        file_id = row["id"]

    # Simulates a real Docker `:ro` mount — writability is now driven by the
    # actual OS permission bit, not a separate allowlist.
    target.chmod(0o555)
    try:
        with pytest.raises(PermissionError):
            compare_copy.copy_selected(run_id, [file_id])
        assert not (target / "a.bin").exists()

        # Regression: writability is checked *after* copy_phase is set to
        # 'running', so a refusal here still reports 'error' with a message
        # rather than leaving copy_phase stuck at its initial null forever
        # (a poller watching /compare/{id}/copy/status would hang).
        with db.connection() as conn:
            run = conn.execute("SELECT copy_phase, copy_error FROM compare_runs WHERE id = ?", (run_id,)).fetchone()
        assert run["copy_phase"] == "error"
        assert run["copy_error"] is not None
    finally:
        target.chmod(0o755)  # restore so pytest's tmp_path cleanup can remove it


def test_copy_refuses_when_target_outside_browse_roots(env, monkeypatch, tmp_path):
    source, target = env["source"], env["target"]
    (source / "a.bin").write_bytes(b"payload")

    run_id = _run(source, target)
    with db.connection() as conn:
        row = conn.execute(
            "SELECT id FROM compare_files WHERE run_id = ? AND category = 'source_only'", (run_id,)
        ).fetchone()
        file_id = row["id"]

    # target is still OS-writable but no longer a recognized browse root —
    # exercises the containment check independent of the os.access check.
    monkeypatch.setattr(config, "BROWSE_ROOTS", [source.resolve()])

    with pytest.raises(PermissionError):
        compare_copy.copy_selected(run_id, [file_id])

    assert not (target / "a.bin").exists()
