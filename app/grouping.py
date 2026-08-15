from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from . import config
from .bktree import BKTree


@dataclass
class DupFile:
    id: int
    path: str
    name: str
    size: int
    mtime: float
    staged: bool


@dataclass
class DupGroup:
    kind: str  # "exact" | "similar"
    files: list[DupFile]
    score: int | None = None  # max hamming distance within the group, for "similar" only


def group_reclaimable_bytes(group: DupGroup) -> int:
    # Space recovered by keeping the largest file in the group (the safest
    # single copy to keep) and staging the rest. For "exact" groups every
    # file is the same size, so this is equivalent to size * (n - 1).
    sizes = [f.size for f in group.files]
    return sum(sizes) - max(sizes)


def _row_to_file(row: sqlite3.Row) -> DupFile:
    return DupFile(row["id"], row["path"], row["name"], row["size"], row["mtime"], row["staged_at"] is not None)


def exact_duplicate_groups(conn: sqlite3.Connection) -> list[DupGroup]:
    rows = conn.execute(
        """
        SELECT id, path, name, size, mtime, full_hash, staged_at
        FROM files
        WHERE full_hash IS NOT NULL
        ORDER BY full_hash
        """
    ).fetchall()
    grouped: dict[str, list[DupFile]] = defaultdict(list)
    for row in rows:
        grouped[row["full_hash"]].append(_row_to_file(row))
    groups = [DupGroup("exact", files) for files in grouped.values() if len(files) > 1]
    groups.sort(key=group_reclaimable_bytes, reverse=True)
    return groups


def near_duplicate_groups(conn: sqlite3.Connection, threshold: int = config.PHASH_THRESHOLD) -> list[DupGroup]:
    rows = conn.execute(
        """
        SELECT f.id, f.path, f.name, f.size, f.mtime, f.staged_at, ih.phash
        FROM image_hashes ih
        JOIN files f ON f.id = ih.file_id
        """
    ).fetchall()

    tree = BKTree()
    by_id: dict[int, tuple[sqlite3.Row, int]] = {}
    for row in rows:
        value = int(row["phash"], 16)
        by_id[row["id"]] = (row, value)
        tree.add(row["id"], value)

    visited: set[int] = set()
    groups: list[DupGroup] = []
    for file_id, (row, value) in by_id.items():
        if file_id in visited:
            continue
        matches = [m for m in tree.query(value, threshold) if m[0] != file_id]
        if not matches:
            continue
        member_ids = {file_id, *(m[0] for m in matches)}
        if member_ids <= visited:
            continue
        visited |= member_ids
        files = [_row_to_file(by_id[i][0]) for i in member_ids]
        groups.append(DupGroup("similar", files, score=max(m[1] for m in matches)))

    groups.sort(key=group_reclaimable_bytes, reverse=True)
    return groups


def reclaimable_bytes(groups: list[DupGroup]) -> int:
    return sum(group_reclaimable_bytes(g) for g in groups)


# --- Size-based categorization, for report filtering ---

SIZE_BUCKETS: list[tuple[float, str]] = [
    (1024**2, "< 1 MB"),
    (10 * 1024**2, "1–10 MB"),
    (100 * 1024**2, "10–100 MB"),
    (1024**3, "100 MB – 1 GB"),
    (float("inf"), "> 1 GB"),
]


def size_bucket(size_bytes: float) -> str:
    for limit, label in SIZE_BUCKETS:
        if size_bytes < limit:
            return label
    return SIZE_BUCKETS[-1][1]


@dataclass
class CategoryStat:
    label: str
    slug: str
    groups: list[DupGroup]
    group_count: int
    file_count: int
    extra_count: int
    bytes_reclaimable: int
    pct_of_total: float = 0.0


def categorize_by_size(
    groups: list[DupGroup], bucket_key=lambda g: g.files[0].size
) -> list[CategoryStat]:
    """Bucket duplicate groups by file size, in the fixed SIZE_BUCKETS order.

    `bucket_key` picks the representative size for a group — for "exact"
    groups every file is identical in size, so the default (first file)
    works; near-duplicate groups can vary in size, so callers typically pass
    `lambda g: max(f.size for f in g.files)` there instead.
    """
    buckets: dict[str, list[DupGroup]] = defaultdict(list)
    for g in groups:
        buckets[size_bucket(bucket_key(g))].append(g)

    stats: list[CategoryStat] = []
    for _, label in SIZE_BUCKETS:
        members = buckets.get(label, [])
        if not members:
            continue
        stats.append(
            CategoryStat(
                label=label,
                slug=label.lower().replace(" ", "-").replace("–", "-"),
                groups=members,
                group_count=len(members),
                file_count=sum(len(g.files) for g in members),
                extra_count=sum(len(g.files) - 1 for g in members),
                bytes_reclaimable=sum(group_reclaimable_bytes(g) for g in members),
            )
        )

    total = sum(c.bytes_reclaimable for c in stats) or 1
    for c in stats:
        c.pct_of_total = round(100 * c.bytes_reclaimable / total, 1)
    return stats
