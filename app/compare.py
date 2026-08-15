from __future__ import annotations

import os
import sqlite3
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone

from . import config, db, hashing


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in config.EXCLUDE_DIRS]
        total += len(filenames)
    return total


def _walk_side(root: str, side: str) -> list[WalkedFile]:
    found: list[WalkedFile] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
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


def run_compare(run_id: int, source_root: str, target_root: str) -> None:
    try:
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
            _hash_and_categorize(conn, run_id)
            _set_progress(conn, run_id, phase="ready", files_done=len(walked))
            conn.execute("UPDATE compare_runs SET finished_at = ? WHERE id = ?", (_now(), run_id))
            conn.commit()
    except Exception as exc:
        with db.connection() as conn:
            _set_progress(conn, run_id, phase="error", error=str(exc))
            conn.execute("UPDATE compare_runs SET finished_at = ? WHERE id = ?", (_now(), run_id))
            conn.commit()
        raise


def _hash_and_categorize(conn: sqlite3.Connection, run_id: int) -> None:
    """Staged size -> partial-hash -> full-hash matching, mirroring the
    single-volume pipeline: only files whose size (then partial hash) is
    ambiguous across sides need the next, more expensive stage.
    """
    rows = conn.execute(
        "SELECT id, side, path, size FROM compare_files WHERE run_id = ?", (run_id,)
    ).fetchall()
    if not rows:
        return

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

    def _run_pool(task_fn, tasks) -> dict[int, str | None]:
        nonlocal done
        results: dict[int, str | None] = {}
        with ProcessPoolExecutor(max_workers=config.WORKERS) as pool:
            for row_id, value in pool.map(task_fn, tasks, chunksize=32):
                results[row_id] = value
                done += 1
                if done % 50 == 0:
                    _set_progress(conn, run_id, files_done=done)
        return results

    if ambiguous:
        partial_by_id = _run_pool(_partial_hash_task, [(r["id"], r["path"], r["size"]) for r in ambiguous])

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
            full_by_id = _run_pool(_full_hash_task, [(r["id"], r["path"]) for r in need_full])

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
