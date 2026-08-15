from __future__ import annotations

import mimetypes
import os
import sqlite3
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone

from . import config, db, hashing, perceptual


@dataclass
class WalkedFile:
    path: str
    name: str
    size: int
    mtime: float
    ctime: float
    mimetype: str | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _guess_mimetype(name: str) -> str | None:
    mimetype, _ = mimetypes.guess_type(name)
    if mimetype:
        return mimetype
    ext = os.path.splitext(name)[1].lower()
    if ext in config.IMAGE_EXTENSIONS:
        return f"image/{ext.lstrip('.')}"
    return None


def walk_files(roots: list[str]) -> list[WalkedFile]:
    found: list[WalkedFile] = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in config.EXCLUDE_DIRS]
            for name in filenames:
                full_path = os.path.join(dirpath, name)
                try:
                    st = os.stat(full_path)
                except OSError:
                    continue
                found.append(
                    WalkedFile(
                        full_path, name, st.st_size, st.st_mtime, st.st_ctime,
                        _guess_mimetype(name),
                    )
                )
    return found


UPSERT_SQL = """
INSERT INTO files (path, name, size, mtime, ctime, mimetype, last_scan_id, last_seen_at)
VALUES (:path, :name, :size, :mtime, :ctime, :mimetype, :scan_id, :seen_at)
ON CONFLICT(path) DO UPDATE SET
    name = excluded.name,
    size = excluded.size,
    mtime = excluded.mtime,
    ctime = excluded.ctime,
    mimetype = excluded.mimetype,
    last_scan_id = excluded.last_scan_id,
    last_seen_at = excluded.last_seen_at,
    partial_hash = CASE WHEN files.size = excluded.size AND files.mtime = excluded.mtime
                         THEN files.partial_hash ELSE NULL END,
    full_hash = CASE WHEN files.size = excluded.size AND files.mtime = excluded.mtime
                      THEN files.full_hash ELSE NULL END
"""


def upsert_files(conn: sqlite3.Connection, walked: list[WalkedFile], scan_id: int) -> None:
    seen_at = _now()
    conn.executemany(
        UPSERT_SQL,
        [
            {
                "path": w.path, "name": w.name, "size": w.size, "mtime": w.mtime,
                "ctime": w.ctime, "mimetype": w.mimetype, "scan_id": scan_id, "seen_at": seen_at,
            }
            for w in walked
        ],
    )
    # A file whose content changed this scan had its full_hash reset above;
    # any stale perceptual hash for it needs to go too, it'll be recomputed.
    conn.execute("DELETE FROM image_hashes WHERE file_id IN (SELECT id FROM files WHERE full_hash IS NULL)")


def prune_missing(conn: sqlite3.Connection, scan_id: int, roots: list[str]) -> int:
    """Remove index rows for files that no longer exist under the scanned roots."""
    prefixes = [r.rstrip("/") + "/%" for r in roots]
    where = " OR ".join(["path LIKE ?"] * len(prefixes))
    rows = conn.execute(
        f"SELECT id FROM files WHERE last_scan_id != ? AND ({where})",
        [scan_id, *prefixes],
    ).fetchall()
    ids = [r["id"] for r in rows]
    if ids:
        conn.executemany("DELETE FROM files WHERE id = ?", [(i,) for i in ids])
    return len(ids)


# --- Process-pool worker functions (must stay top-level to be picklable) ---

def _partial_hash_task(args: tuple[int, str, int]) -> tuple[int, str | None]:
    file_id, path, size = args
    return file_id, hashing.partial_hash(path, size)


def _full_hash_task(args: tuple[int, str]) -> tuple[int, str | None]:
    file_id, path = args
    return file_id, hashing.full_hash(path)


def _phash_task(args: tuple[int, str]) -> tuple[int, str | None]:
    file_id, path = args
    return file_id, perceptual.compute_phash(path)


def run_partial_hash_stage(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT f.id, f.path, f.size FROM files f
        WHERE f.partial_hash IS NULL
        AND EXISTS (SELECT 1 FROM files f2 WHERE f2.size = f.size AND f2.id != f.id)
        """
    ).fetchall()
    if not rows:
        return 0
    tasks = [(r["id"], r["path"], r["size"]) for r in rows]
    updated = 0
    with ProcessPoolExecutor(max_workers=config.WORKERS) as pool:
        for file_id, value in pool.map(_partial_hash_task, tasks, chunksize=32):
            if value is not None:
                conn.execute("UPDATE files SET partial_hash = ? WHERE id = ?", (value, file_id))
                updated += 1
    conn.commit()
    return updated


def run_full_hash_stage(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT f.id, f.path FROM files f
        WHERE f.full_hash IS NULL AND f.partial_hash IS NOT NULL
        AND EXISTS (
            SELECT 1 FROM files f2
            WHERE f2.size = f.size AND f2.partial_hash = f.partial_hash AND f2.id != f.id
        )
        """
    ).fetchall()
    if not rows:
        return 0
    tasks = [(r["id"], r["path"]) for r in rows]
    updated = 0
    with ProcessPoolExecutor(max_workers=config.WORKERS) as pool:
        for file_id, value in pool.map(_full_hash_task, tasks, chunksize=16):
            if value is not None:
                conn.execute("UPDATE files SET full_hash = ? WHERE id = ?", (value, file_id))
                updated += 1
    conn.commit()
    return updated


def run_phash_stage(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT f.id, f.path FROM files f
        LEFT JOIN image_hashes ih ON ih.file_id = f.id
        WHERE ih.file_id IS NULL AND f.mimetype LIKE 'image/%'
        """
    ).fetchall()
    if not rows:
        return 0
    tasks = [(r["id"], r["path"]) for r in rows]
    updated = 0
    with ProcessPoolExecutor(max_workers=config.WORKERS) as pool:
        for file_id, value in pool.map(_phash_task, tasks, chunksize=16):
            if value is not None:
                conn.execute(
                    "INSERT OR REPLACE INTO image_hashes (file_id, phash) VALUES (?, ?)",
                    (file_id, value),
                )
                updated += 1
    conn.commit()
    return updated


def run_scan(roots: list[str] | None = None) -> int:
    roots = roots or [str(r) for r in config.SCAN_ROOTS]
    db.init_db()

    with db.connection() as conn:
        cur = conn.execute(
            "INSERT INTO scans (root_paths, started_at, status) VALUES (?, ?, 'running')",
            (",".join(roots), _now()),
        )
        scan_id = cur.lastrowid

    try:
        walked = walk_files(roots)

        with db.connection() as conn:
            upsert_files(conn, walked, scan_id)
            prune_missing(conn, scan_id, roots)

        with db.connection() as conn:
            run_partial_hash_stage(conn)
        with db.connection() as conn:
            run_full_hash_stage(conn)
        with db.connection() as conn:
            run_phash_stage(conn)

        bytes_seen = sum(w.size for w in walked)
        with db.connection() as conn:
            conn.execute(
                "UPDATE scans SET status='complete', finished_at=?, files_seen=?, bytes_seen=? WHERE id=?",
                (_now(), len(walked), bytes_seen, scan_id),
            )
    except Exception as exc:
        with db.connection() as conn:
            conn.execute(
                "UPDATE scans SET status='error', finished_at=?, error=? WHERE id=?",
                (_now(), str(exc), scan_id),
            )
        raise

    return scan_id
