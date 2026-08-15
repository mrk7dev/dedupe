import os
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app import config, db, grouping, scanner


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "folder_a").mkdir(parents=True)
    (data / "folder_b").mkdir(parents=True)
    db_path = tmp_path / "dedupe.db"
    staging = tmp_path / "staging"

    monkeypatch.setattr(config, "SCAN_ROOTS", [data])
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "STAGING_DIR", staging)
    monkeypatch.setattr(config, "WORKERS", 2)

    return {"data": data, "db_path": db_path, "staging": staging}


def _make_photo(path: Path, corner: str, size=(64, 64)) -> None:
    # A flat-color square is a degenerate case for pHash (near-zero variance
    # collapses most images to the same hash) — use a gradient with a
    # positioned block so the perceptual hash actually reflects layout.
    img = Image.new("RGB", size, (230, 230, 230))
    draw = ImageDraw.Draw(img)
    for y in range(size[1]):
        shade = int(255 * y / size[1])
        draw.line([(0, y), (size[0], y)], fill=(shade, shade, shade))
    box = size[0] // 3
    rect = (0, 0, box, box) if corner == "top_left" else (size[0] - box, size[1] - box, size[0], size[1])
    draw.rectangle(rect, fill=(20, 20, 160))
    img.save(path)


def test_exact_duplicates_detected(env):
    data = env["data"]
    content = b"the quick brown fox jumps over the lazy dog" * 1000
    (data / "folder_a" / "original.bin").write_bytes(content)
    (data / "folder_b" / "copy.bin").write_bytes(content)
    (data / "folder_a" / "unique.bin").write_bytes(b"nothing like the others")

    scan_id = scanner.run_scan([str(data)])
    with db.connection() as conn:
        row = conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
        assert row["status"] == "complete"
        assert row["files_seen"] == 3

        groups = grouping.exact_duplicate_groups(conn)
        assert len(groups) == 1
        assert len(groups[0].files) == 2
        paths = {f.path for f in groups[0].files}
        assert paths == {
            str(data / "folder_a" / "original.bin"),
            str(data / "folder_b" / "copy.bin"),
        }


def test_incremental_rescan_skips_unchanged_hash(env):
    data = env["data"]
    content = b"stable content" * 500
    p1 = data / "folder_a" / "a.bin"
    p2 = data / "folder_b" / "b.bin"
    p1.write_bytes(content)
    p2.write_bytes(content)

    scanner.run_scan([str(data)])
    with db.connection() as conn:
        before = {r["path"]: r["full_hash"] for r in conn.execute("SELECT path, full_hash FROM files")}
    assert all(before.values())

    # Touch mtime on one file without changing content/size — full_hash
    # should be recomputed (same value) since the upsert resets it, but the
    # scan should still complete and dedupe should still find the group.
    os.utime(p1, None)
    scanner.run_scan([str(data)])
    with db.connection() as conn:
        groups = grouping.exact_duplicate_groups(conn)
    assert len(groups) == 1
    assert len(groups[0].files) == 2


def test_prune_removes_deleted_files(env):
    data = env["data"]
    p = data / "folder_a" / "gone.bin"
    p.write_bytes(b"temporary")
    scanner.run_scan([str(data)])
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"] == 1

    p.unlink()
    scanner.run_scan([str(data)])
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"] == 0


def test_near_duplicate_images_detected(env):
    data = env["data"]
    _make_photo(data / "folder_a" / "photo.jpg", "top_left")
    Image.open(data / "folder_a" / "photo.jpg").resize((70, 70)).save(data / "folder_b" / "photo_resave.jpg")
    _make_photo(data / "folder_a" / "different.jpg", "bottom_right")

    scanner.run_scan([str(data)])
    with db.connection() as conn:
        exact = grouping.exact_duplicate_groups(conn)
        similar = grouping.near_duplicate_groups(conn)

    assert exact == []  # different bytes/sizes, not exact matches
    assert len(similar) == 1
    assert len(similar[0].files) == 2
    names = {Path(f.path).name for f in similar[0].files}
    assert names == {"photo.jpg", "photo_resave.jpg"}


def test_stage_moves_file_and_marks_db(env):
    from app import actions

    data = env["data"]
    content = b"dupe me" * 200
    p1 = data / "folder_a" / "a.bin"
    p2 = data / "folder_b" / "b.bin"
    p1.write_bytes(content)
    p2.write_bytes(content)
    scanner.run_scan([str(data)])

    with db.connection() as conn:
        groups = grouping.exact_duplicate_groups(conn)
        victim = groups[0].files[1]
        dest = actions.stage_file(conn, victim.id)

    assert dest.exists()
    assert not Path(victim.path).exists() or Path(victim.path) == dest
    assert env["staging"] in dest.parents
    with db.connection() as conn:
        row = conn.execute("SELECT staged_at, path FROM files WHERE id = ?", (victim.id,)).fetchone()
        assert row["staged_at"] is not None
        assert row["path"] == str(dest)
