from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import config


@dataclass
class Entry:
    path: str
    name: str
    kind: str | None = None  # 'internal' | 'external' — set on top-level mounts only
    has_children: bool = False  # whether this directory has any (visible) subdirectories


def _mount_kind(root: Path) -> str:
    return "external" if "usb" in str(root).lower() else "internal"


def _has_subdirs(path: Path) -> bool:
    """Cheap existence check, not a full listing — stops at the first match."""
    try:
        with os.scandir(path) as it:
            for e in it:
                if e.name in config.EXCLUDE_DIRS or e.name.startswith("."):
                    continue
                if e.is_dir(follow_symlinks=False):
                    return True
    except OSError:
        pass
    return False


def list_roots() -> list[Entry]:
    return [
        Entry(path=str(root), name=root.name or str(root), kind=_mount_kind(root), has_children=_has_subdirs(root))
        for root in config.BROWSE_ROOTS
        if root.is_dir()
    ]


def _is_under_browse_roots(path: Path) -> bool:
    return any(path == root or root in path.parents for root in config.BROWSE_ROOTS)


def list_children(path: str | None) -> list[Entry]:
    """List immediate subdirectories of `path`, or the configured mount roots if `path` is None.

    Scoped to BROWSE_ROOTS so the picker can't be pointed outside the
    configured mounts via a crafted path. Each entry reports whether it has
    subdirectories of its own, so the frontend tree can show an accurate
    expand affordance without a round trip per node.
    """
    if path is None:
        return list_roots()

    target = Path(path)
    if not _is_under_browse_roots(target):
        raise PermissionError(f"{path} is outside the configured browse roots")
    if not target.is_dir():
        raise NotADirectoryError(path)

    entries: list[Entry] = []
    with os.scandir(target) as it:
        for e in it:
            if e.name in config.EXCLUDE_DIRS or e.name.startswith("."):
                continue
            if not e.is_dir(follow_symlinks=False):
                continue
            child = target / e.name
            entries.append(Entry(path=str(child), name=e.name, has_children=_has_subdirs(child)))
    entries.sort(key=lambda e: e.name.lower())
    return entries
