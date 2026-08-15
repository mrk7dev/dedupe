from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config, db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _assert_writable(root: Path) -> None:
    if not any(root == w or w in root.parents for w in config.WRITABLE_ROOTS):
        raise PermissionError(f"{root} is outside the configured writable roots")


def _unique_dest(dest: Path) -> Path:
    """Never overwrite an existing target file — auto-rename the incoming copy instead."""
    if not dest.exists():
        return dest
    n = 1
    candidate = dest.with_name(f"{dest.stem}.copy{dest.suffix}")
    while candidate.exists():
        n += 1
        candidate = dest.with_name(f"{dest.stem}.copy{n}{dest.suffix}")
    return candidate


def copy_selected(run_id: int, compare_file_ids: list[int]) -> None:
    """Copy the given source_only compare_files into the run's target root.

    Additive only: creates new files, never touches anything already on
    target. Writes are confined to inside the target root even if the
    underlying mount grants broader access. A single file's copy failing
    (permissions, disk full, vanished mid-run) is logged on that row and
    doesn't stop the rest of the batch.
    """
    with db.connection() as conn:
        run = conn.execute("SELECT * FROM compare_runs WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            raise FileNotFoundError(f"no compare run {run_id}")

        source_root = Path(run["source_root"]).resolve()
        target_root = Path(run["target_root"]).resolve()
        _assert_writable(target_root)

        placeholders = ",".join("?" * len(compare_file_ids))
        rows = conn.execute(
            f"""
            SELECT * FROM compare_files
            WHERE run_id = ? AND category = 'source_only' AND id IN ({placeholders})
            """,
            (run_id, *compare_file_ids),
        ).fetchall()

        conn.execute(
            "UPDATE compare_runs SET copy_phase = 'running', copy_total = ?, copy_done = 0, copy_error = NULL WHERE id = ?",
            (len(rows), run_id),
        )
        conn.commit()

    done = 0
    try:
        with db.connection() as conn:
            for row in rows:
                _copy_one(conn, source_root, target_root, row)
                done += 1
                conn.execute("UPDATE compare_runs SET copy_done = ? WHERE id = ?", (done, run_id))
                conn.commit()

        with db.connection() as conn:
            conn.execute("UPDATE compare_runs SET copy_phase = 'done' WHERE id = ?", (run_id,))
            conn.commit()
    except Exception as exc:
        # Only a path-safety violation (target escape) or DB error reaches
        # here — per-file I/O errors are caught in _copy_one and logged
        # instead, so the batch keeps going.
        with db.connection() as conn:
            conn.execute(
                "UPDATE compare_runs SET copy_phase = 'error', copy_error = ? WHERE id = ?",
                (str(exc), run_id),
            )
            conn.commit()
        raise


def _copy_one(conn: sqlite3.Connection, source_root: Path, target_root: Path, row: sqlite3.Row) -> None:
    src = Path(row["path"])
    rel = src.relative_to(source_root)
    dest = _unique_dest(target_root / rel)

    dest_resolved = dest.parent.resolve() / dest.name
    if dest_resolved != target_root and target_root not in dest_resolved.parents:
        raise PermissionError(f"refusing to write outside target root: {dest}")

    action_id = conn.execute(
        "INSERT INTO copy_actions (run_id, compare_file_id, dest_path, status) VALUES (?, ?, ?, 'pending')",
        (row["run_id"], row["id"], str(dest)),
    ).lastrowid

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    except OSError as exc:
        conn.execute("UPDATE copy_actions SET status = 'error', error = ? WHERE id = ?", (str(exc), action_id))
        conn.commit()
        return

    conn.execute("UPDATE copy_actions SET status = 'done', copied_at = ? WHERE id = ?", (_now(), action_id))
    conn.execute("UPDATE compare_files SET category = 'matched' WHERE id = ?", (row["id"],))
    conn.commit()
