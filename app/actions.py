import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config


def stage_file(conn: sqlite3.Connection, file_id: int) -> Path:
    """Move a file into the staging folder instead of deleting it.

    Nothing this app does ever removes a file outright — staging is a
    reversible move so a bad grouping decision costs a `mv` back, not
    lost data.
    """
    row = conn.execute("SELECT path FROM files WHERE id = ?", (file_id,)).fetchone()
    if row is None:
        raise FileNotFoundError(f"no file with id {file_id}")

    src = Path(row["path"])
    rel: Path | None = None
    for root in config.SCAN_ROOTS:
        try:
            rel = src.relative_to(root)
            break
        except ValueError:
            continue
    rel = rel if rel is not None else Path(src.name)

    dest = config.STAGING_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest = dest.with_name(f"{dest.stem}.{file_id}{dest.suffix}")

    shutil.move(str(src), str(dest))
    conn.execute(
        "UPDATE files SET path = ?, staged_at = ? WHERE id = ?",
        (str(dest), datetime.now(timezone.utc).isoformat(timespec="seconds"), file_id),
    )
    conn.commit()
    return dest
