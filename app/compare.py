from __future__ import annotations

import logging
import os
import sqlite3
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone

from . import config, db, hashing

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


CACHE_UPSERT_SQL = """
INSERT INTO hash_cache (path, size, mtime, partial_hash, full_hash, updated_at)
VALUES (:path, :size, :mtime, :partial_hash, :full_hash, :updated_at)
ON CONFLICT(path) DO UPDATE SET
    size = excluded.size,
    mtime = excluded.mtime,
    partial_hash = CASE
        WHEN excluded.partial_hash IS NOT NULL THEN excluded.partial_hash
        WHEN hash_cache.size = excluded.size AND hash_cache.mtime = excluded.mtime THEN hash_cache.partial_hash
        ELSE NULL END,
    full_hash = CASE
        WHEN excluded.full_hash IS NOT NULL THEN excluded.full_hash
        WHEN hash_cache.size = excluded.size AND hash_cache.mtime = excluded.mtime THEN hash_cache.full_hash
        ELSE NULL END,
    updated_at = excluded.updated_at
"""


def _load_hash_cache(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows = conn.execute("SELECT path, size, mtime, partial_hash, full_hash FROM hash_cache").fetchall()
    return {r["path"]: r for r in rows}


def check_readable(root: str) -> None:
    """os.walk silently skips any directory it can't scandir — including the
    root itself — instead of raising. Without this check, a target root the
    container's user lacks read permission on walks as 0 files and every
    source file is then (wrongly, silently) reported as missing from target.
    """
    try:
        with os.scandir(root):
            pass
    except OSError as exc:
        raise PermissionError(f"cannot read directory {root}: {exc.strerror or exc}") from exc


def _log_walk_error(exc: OSError) -> None:
    """os.walk's default onerror=None silently drops unreadable subdirectories
    mid-walk too — log them so a partial scan is at least visible in the
    container logs instead of just quietly under-counting.
    """
    logger.warning("skipping unreadable path during compare walk: %s", exc)


@dataclass
class WalkedFile:
    side: str
    dir: str
    name: str
    path: str
    size: int
    mtime: float


def _count_files(root: str) -> int:
    total = 0
    for dirpath, dirnames, filenames in os.walk(root, onerror=_log_walk_error, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in config.EXCLUDE_DIRS]
        total += len(filenames)
    return total


def _walk_side(root: str, side: str) -> list[WalkedFile]:
    found: list[WalkedFile] = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=_log_walk_error, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in config.EXCLUDE_DIRS]
        for name in filenames:
            full_path = os.path.join(dirpath, name)
            try:
                st = os.stat(full_path)
            except OSError:
                continue
            found.append(WalkedFile(side, dirpath, name, full_path, st.st_size, st.st_mtime))
    return found


def _set_progress(conn: sqlite3.Connection, run_id: int, **fields) -> None:
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE compare_runs SET {cols} WHERE id = ?", [*fields.values(), run_id])
    conn.commit()


def _partial_hash_task(args: tuple[int, str, int]) -> tuple[int, str | None]:
    row_id, path, size = args
    return row_id, hashing.partial_hash(path, size)


def _full_hash_task(args: tuple[int, str]) -> tuple[int, str | None]:
    row_id, path = args
    return row_id, hashing.full_hash(path)


def create_run(source_root: str, target_root: str) -> int:
    with db.connection() as conn:
        cur = conn.execute(
            "INSERT INTO compare_runs (source_root, target_root, phase, started_at) VALUES (?, ?, 'counting', ?)",
            (source_root, target_root, _now()),
        )
        return cur.lastrowid


def run_compare(run_id: int, source_root: str, target_root: str, ignore_cache: bool = False) -> None:
    try:
        check_readable(source_root)
        check_readable(target_root)
        total = _count_files(source_root) + _count_files(target_root)
        with db.connection() as conn:
            _set_progress(conn, run_id, phase="scanning", files_total=total, files_done=0)

        walked: list[WalkedFile] = []
        for root, side in ((source_root, "source"), (target_root, "target")):
            side_files = _walk_side(root, side)
            walked.extend(side_files)
            with db.connection() as conn:
                _set_progress(conn, run_id, files_done=len(walked))

        with db.connection() as conn:
            conn.executemany(
                """
                INSERT INTO compare_files (run_id, side, dir, name, path, size, mtime)
                VALUES (:run_id, :side, :dir, :name, :path, :size, :mtime)
                """,
                [
                    {
                        "run_id": run_id, "side": w.side, "dir": w.dir, "name": w.name,
                        "path": w.path, "size": w.size, "mtime": w.mtime,
                    }
                    for w in walked
                ],
            )
            conn.commit()

        with db.connection() as conn:
            _set_progress(conn, run_id, phase="hashing", files_total=len(walked), files_done=0)
            _hash_and_categorize(conn, run_id, ignore_cache=ignore_cache)
            _set_progress(conn, run_id, phase="ready", files_done=len(walked))
            conn.execute("UPDATE compare_runs SET finished_at = ? WHERE id = ?", (_now(), run_id))
            conn.commit()
    except Exception as exc:
        with db.connection() as conn:
            _set_progress(conn, run_id, phase="error", error=str(exc))
            conn.execute("UPDATE compare_runs SET finished_at = ? WHERE id = ?", (_now(), run_id))
            conn.commit()
        raise


def _hash_and_categorize(conn: sqlite3.Connection, run_id: int, ignore_cache: bool = False) -> None:
    """Staged size -> partial-hash -> full-hash matching, mirroring the
    single-volume pipeline: only files whose size (then partial hash) is
    ambiguous across sides need the next, more expensive stage.
    """
    rows = conn.execute(
        "SELECT id, side, path, size, mtime FROM compare_files WHERE run_id = ?", (run_id,)
    ).fetchall()
    if not rows:
        return
    rows_by_id = {r["id"]: r for r in rows}

    resolved: dict[int, str] = {}
    done = 0

    def _resolve_singleton_side(group: list[sqlite3.Row]) -> None:
        for r in group:
            resolved[r["id"]] = "source_only" if r["side"] == "source" else "target_only"

    by_size: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        by_size[r["size"]].append(r)

    ambiguous: list[sqlite3.Row] = []
    for group in by_size.values():
        if len({r["side"] for r in group}) < 2:
            _resolve_singleton_side(group)
        else:
            ambiguous.extend(group)

    done = len(rows) - len(ambiguous)
    if done:
        _set_progress(conn, run_id, files_done=done)

    def _run_pool(task_fn, tasks, hash_field: str) -> dict[int, str | None]:
        nonlocal done
        results: dict[int, str | None] = {}
        pending: list[dict] = []
        with ProcessPoolExecutor(max_workers=config.WORKERS) as pool:
            for row_id, value in pool.map(task_fn, tasks, chunksize=32):
                results[row_id] = value
                done += 1
                if value is not None:
                    r = rows_by_id[row_id]
                    pending.append(
                        {
                            "path": r["path"], "size": r["size"], "mtime": r["mtime"],
                            "partial_hash": value if hash_field == "partial_hash" else None,
                            "full_hash": value if hash_field == "full_hash" else None,
                            "updated_at": _now(),
                        }
                    )
                if done % 50 == 0:
                    _set_progress(conn, run_id, files_done=done)
                    if pending:
                        conn.executemany(CACHE_UPSERT_SQL, pending)
                        conn.commit()
                        pending = []
        if pending:
            conn.executemany(CACHE_UPSERT_SQL, pending)
            conn.commit()
        return results

    if ambiguous:
        cache = {} if ignore_cache else _load_hash_cache(conn)

        def _cache_hit(r: sqlite3.Row, field: str) -> str | None:
            c = cache.get(r["path"])
            if c is not None and c["size"] == r["size"] and c["mtime"] == r["mtime"] and c[field] is not None:
                return c[field]
            return None

        partial_by_id: dict[int, str | None] = {}
        need_partial: list[sqlite3.Row] = []
        for r in ambiguous:
            hit = _cache_hit(r, "partial_hash")
            if hit is not None:
                partial_by_id[r["id"]] = hit
            else:
                need_partial.append(r)
        cache_hits = len(ambiguous) - len(need_partial)
        if cache_hits:
            done += cache_hits
            _set_progress(conn, run_id, files_done=done)
        if need_partial:
            partial_by_id.update(
                _run_pool(_partial_hash_task, [(r["id"], r["path"], r["size"]) for r in need_partial], "partial_hash")
            )

        by_size_partial: dict[tuple[int, str], list[sqlite3.Row]] = defaultdict(list)
        for r in ambiguous:
            partial = partial_by_id.get(r["id"])
            if partial is None:
                _resolve_singleton_side([r])
                continue
            by_size_partial[(r["size"], partial)].append(r)

        need_full: list[sqlite3.Row] = []
        for group in by_size_partial.values():
            if len({r["side"] for r in group}) < 2:
                _resolve_singleton_side(group)
            else:
                need_full.extend(group)

        if need_full:
            full_by_id: dict[int, str | None] = {}
            need_full_compute: list[sqlite3.Row] = []
            for r in need_full:
                hit = _cache_hit(r, "full_hash")
                if hit is not None:
                    full_by_id[r["id"]] = hit
                else:
                    need_full_compute.append(r)
            full_cache_hits = len(need_full) - len(need_full_compute)
            if full_cache_hits:
                done += full_cache_hits
                _set_progress(conn, run_id, files_done=done)
            if need_full_compute:
                full_by_id.update(
                    _run_pool(_full_hash_task, [(r["id"], r["path"]) for r in need_full_compute], "full_hash")
                )

            by_size_full: dict[tuple[int, str], list[sqlite3.Row]] = defaultdict(list)
            for r in need_full:
                full = full_by_id.get(r["id"])
                if full is None:
                    _resolve_singleton_side([r])
                    continue
                conn.execute("UPDATE compare_files SET full_hash = ? WHERE id = ?", (full, r["id"]))
                by_size_full[(r["size"], full)].append(r)

            for group in by_size_full.values():
                if len({r["side"] for r in group}) < 2:
                    _resolve_singleton_side(group)
                else:
                    for r in group:
                        resolved[r["id"]] = "matched"

    conn.executemany(
        "UPDATE compare_files SET category = ? WHERE id = ?",
        [(cat, row_id) for row_id, cat in resolved.items()],
    )
    conn.commit()


def get_results(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, side, dir, name, path, size, category
        FROM compare_files
        WHERE run_id = ? AND category IS NOT NULL
        """,
        (run_id,),
    ).fetchall()

    results = []
    for r in rows:
        # A "matched" pair has a row on each side; only surface the source
        # side so the UI shows one entry per piece of content, not two.
        if r["category"] == "matched" and r["side"] == "target":
            continue
        results.append(
            {
                "id": str(r["id"]),
                "dir": r["dir"],
                "path": r["path"],
                "name": r["name"],
                "sizeBytes": r["size"],
                "category": r["category"],
            }
        )
    return results
