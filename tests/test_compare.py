import os
from pathlib import Path
from unittest import mock

import pytest

from app import compare, compare_copy, config, db, hashing


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


class FakeExecutor:
    """Runs pool.map's tasks synchronously in-process instead of spawning
    real workers. ProcessPoolExecutor's start method is `spawn` on macOS
    (this dev machine) vs `fork` on Linux (the Docker deploy target) —
    `spawn` re-imports modules fresh in worker processes, so monkeypatching
    hashing.partial_hash/full_hash in the test process would be invisible to
    real spawned workers. Patching compare.ProcessPoolExecutor to this fake
    keeps hashing calls in-process and therefore mockable/countable,
    regardless of platform.
    """

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def map(self, fn, tasks, chunksize=None):
        return map(fn, tasks)


@pytest.fixture
def no_pool(monkeypatch):
    monkeypatch.setattr(compare, "ProcessPoolExecutor", FakeExecutor)


def _run(source: Path, target: Path) -> int:
    db.init_db()
    run_id = compare.create_run([str(source)], [str(target)])
    compare.run_compare(run_id, [str(source)], [str(target)])
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


def test_repeat_run_skips_rehashing_unchanged_files(env, no_pool):
    source, target = env["source"], env["target"]
    shared = b"identical content" * 500
    (source / "shared.bin").write_bytes(shared)
    (target / "shared_renamed.bin").write_bytes(shared)

    run_id_1 = _run(source, target)
    with db.connection() as conn:
        results_1 = {r["name"]: r["category"] for r in compare.get_results(conn, run_id_1)}

    with mock.patch.object(hashing, "partial_hash", wraps=hashing.partial_hash) as partial_spy, mock.patch.object(
        hashing, "full_hash", wraps=hashing.full_hash
    ) as full_spy:
        run_id_2 = _run(source, target)

    assert partial_spy.call_count == 0
    assert full_spy.call_count == 0

    with db.connection() as conn:
        results_2 = {r["name"]: r["category"] for r in compare.get_results(conn, run_id_2)}
    assert results_1 == results_2


def test_ignore_cache_forces_rehash_but_still_refreshes_cache(env, no_pool):
    source, target = env["source"], env["target"]
    shared = b"identical content" * 500
    (source / "shared.bin").write_bytes(shared)
    (target / "shared_renamed.bin").write_bytes(shared)

    _run(source, target)
    with db.connection() as conn:
        cached_before = {row["path"]: row["updated_at"] for row in conn.execute("SELECT path, updated_at FROM hash_cache")}
    assert cached_before

    db.init_db()
    run_id_2 = compare.create_run([str(source)], [str(target)])
    with mock.patch.object(hashing, "partial_hash", wraps=hashing.partial_hash) as partial_spy:
        compare.run_compare(run_id_2, [str(source)], [str(target)], ignore_cache=True)

    # Cache was ignored on read: hashing ran again despite nothing changing.
    assert partial_spy.call_count > 0

    # But the cache was still refreshed (write-back happens regardless).
    with db.connection() as conn:
        cached_after = {row["path"]: row["updated_at"] for row in conn.execute("SELECT path, updated_at FROM hash_cache")}
        results = {r["name"]: r["category"] for r in compare.get_results(conn, run_id_2)}
    assert set(cached_after) == set(cached_before)
    assert results["shared.bin"] == "matched"


def test_mtime_touch_invalidates_cache_and_forces_rehash(env, no_pool):
    source, target = env["source"], env["target"]
    shared = b"identical content" * 500
    source_file = source / "shared.bin"
    source_file.write_bytes(shared)
    (target / "shared_renamed.bin").write_bytes(shared)

    _run(source, target)
    os.utime(source_file, None)

    with mock.patch.object(hashing, "partial_hash", wraps=hashing.partial_hash) as partial_spy:
        run_id_2 = _run(source, target)

    assert partial_spy.call_count > 0

    with db.connection() as conn:
        results = {r["name"]: r["category"] for r in compare.get_results(conn, run_id_2)}
    assert results["shared.bin"] == "matched"


def test_interrupted_run_persists_partial_progress_for_retry(env, no_pool):
    source, target = env["source"], env["target"]
    n = 130
    for i in range(n):
        content = f"file-{i}-".encode().ljust(1000, b"x")
        (source / f"s{i}.bin").write_bytes(content)
        (target / f"t{i}.bin").write_bytes(content)

    real_partial_hash = hashing.partial_hash
    call_count = {"n": 0}

    def flaky_partial_hash(path, size):
        call_count["n"] += 1
        if call_count["n"] > 60:
            raise RuntimeError("simulated crash")
        return real_partial_hash(path, size)

    db.init_db()
    run_id_1 = compare.create_run([str(source)], [str(target)])
    with mock.patch.object(hashing, "partial_hash", side_effect=flaky_partial_hash):
        with pytest.raises(RuntimeError):
            compare.run_compare(run_id_1, [str(source)], [str(target)])

    with db.connection() as conn:
        run = conn.execute("SELECT phase FROM compare_runs WHERE id = ?", (run_id_1,)).fetchone()
        assert run["phase"] == "error"
        cached_paths_after_crash = {row["path"] for row in conn.execute("SELECT path FROM hash_cache").fetchall()}

    # Partial progress persisted (via the periodic mid-run flush), but not everything.
    assert 0 < len(cached_paths_after_crash) < n

    # Retry with real hashing restored: paths already cached shouldn't be rehashed.
    with mock.patch.object(hashing, "partial_hash", wraps=real_partial_hash) as partial_spy:
        run_id_2 = compare.create_run([str(source)], [str(target)])
        compare.run_compare(run_id_2, [str(source)], [str(target)])

    rehashed_paths = {call.args[0] for call in partial_spy.call_args_list}
    assert cached_paths_after_crash.isdisjoint(rehashed_paths)

    with db.connection() as conn:
        run2 = conn.execute("SELECT phase FROM compare_runs WHERE id = ?", (run_id_2,)).fetchone()
    assert run2["phase"] == "ready"


def test_run_compare_errors_clearly_when_target_unreadable(env):
    # Regression: os.walk silently skips a directory it can't scandir —
    # including the root itself — instead of raising. Without an explicit
    # readability check, an unreadable target root walked as 0 files and
    # every source file was then (wrongly, silently) reported as missing
    # from target, instead of the run surfacing a clear permission error.
    source, target = env["source"], env["target"]
    (source / "a.bin").write_bytes(b"payload")
    (target / "a.bin").write_bytes(b"payload")

    target.chmod(0o000)
    try:
        db.init_db()
        run_id = compare.create_run([str(source)], [str(target)])
        with pytest.raises(PermissionError):
            compare.run_compare(run_id, [str(source)], [str(target)])

        with db.connection() as conn:
            run = conn.execute("SELECT phase, error FROM compare_runs WHERE id = ?", (run_id,)).fetchone()
        assert run["phase"] == "error"
        assert run["error"] is not None
        assert str(target) in run["error"]
    finally:
        target.chmod(0o755)  # restore so pytest's tmp_path cleanup can remove it


def test_multi_root_run_compares_across_all_selected_folders(env):
    source, target = env["source"], env["target"]
    source_extra = source.parent / "source_extra"
    source_extra.mkdir()

    shared = b"identical content" * 500
    (source / "shared.bin").write_bytes(shared)  # matches target
    (source_extra / "extra_missing.bin").write_bytes(b"only in second source root" * 100)
    (target / "shared.bin").write_bytes(shared)
    (target / "extra.bin").write_bytes(b"only on target" * 100)

    db.init_db()
    run_id = compare.create_run([str(source), str(source_extra)], [str(target)])
    compare.run_compare(run_id, [str(source), str(source_extra)], [str(target)])

    with db.connection() as conn:
        results = compare.get_results(conn, run_id)

    by_name = {r["name"]: r for r in results}
    assert by_name["shared.bin"]["category"] == "matched"
    assert by_name["extra_missing.bin"]["category"] == "source_only"
    assert by_name["extra.bin"]["category"] == "target_only"


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
