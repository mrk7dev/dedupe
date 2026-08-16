import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    root_paths TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    files_seen INTEGER NOT NULL DEFAULT 0,
    bytes_seen INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    ctime REAL,
    mimetype TEXT,
    partial_hash TEXT,
    full_hash TEXT,
    last_scan_id INTEGER REFERENCES scans(id),
    last_seen_at TEXT NOT NULL,
    staged_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_files_size ON files(size);
CREATE INDEX IF NOT EXISTS idx_files_partial_hash ON files(size, partial_hash);
CREATE INDEX IF NOT EXISTS idx_files_full_hash ON files(full_hash);
CREATE INDEX IF NOT EXISTS idx_files_last_scan ON files(last_scan_id);

CREATE TABLE IF NOT EXISTS image_hashes (
    file_id INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    phash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS compare_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_root TEXT NOT NULL,
    target_root TEXT NOT NULL,
    phase TEXT NOT NULL DEFAULT 'counting',
    files_total INTEGER NOT NULL DEFAULT 0,
    files_done INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error TEXT,
    copy_phase TEXT,
    copy_total INTEGER NOT NULL DEFAULT 0,
    copy_done INTEGER NOT NULL DEFAULT 0,
    copy_error TEXT
);

CREATE TABLE IF NOT EXISTS compare_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES compare_runs(id) ON DELETE CASCADE,
    side TEXT NOT NULL,
    dir TEXT NOT NULL,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    full_hash TEXT,
    category TEXT
);
CREATE INDEX IF NOT EXISTS idx_compare_files_run ON compare_files(run_id);
CREATE INDEX IF NOT EXISTS idx_compare_files_run_category ON compare_files(run_id, category);

CREATE TABLE IF NOT EXISTS hash_cache (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    partial_hash TEXT,
    full_hash TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS copy_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES compare_runs(id) ON DELETE CASCADE,
    compare_file_id INTEGER NOT NULL REFERENCES compare_files(id),
    dest_path TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    copied_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_copy_actions_run ON copy_actions(run_id);
"""


def get_connection() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # Negative value = size in KB; ~128MB page cache, cheap given available RAM.
    conn.execute("PRAGMA cache_size=-131072")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def connection():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
