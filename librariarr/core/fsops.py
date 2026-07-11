"""Filesystem primitives for inode-based reconcile.

All mutating helpers are idempotent and respect ``dry_run`` by recording the
action without touching the filesystem.
"""

from __future__ import annotations

import fnmatch
import logging
import os
from collections.abc import Iterable
from pathlib import Path

LOG = logging.getLogger(__name__)

TRASH_DIR_NAME = ".deletedByLibrariarr"


def is_video_file(path: Path, video_extensions: Iterable[str]) -> bool:
    suffix = path.suffix.lower()
    return any(suffix == ext.lower() for ext in video_extensions)


def matches_extras_allowlist(name: str, allowlist: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(name.lower(), pattern.lower()) for pattern in allowlist)


def is_excluded(path: Path, patterns: Iterable[str]) -> bool:
    """Match a path against exclude patterns.

    - ``name/`` patterns exclude any path containing that directory segment
    - absolute patterns exclude that subtree
    - other patterns are fnmatch globs against the file/folder name
    """
    parts_lower = [part.lower() for part in path.parts]
    for pattern in patterns:
        pattern = pattern.strip()
        if not pattern:
            continue
        if pattern.endswith("/"):
            if pattern.rstrip("/").lower() in parts_lower:
                return True
        elif pattern.startswith("/"):
            if is_within(path, Path(pattern)):
                return True
        elif fnmatch.fnmatch(path.name.lower(), pattern.lower()):
            return True
    return False


def inode_of(path: Path) -> int | None:
    try:
        return path.stat().st_ino
    except OSError:
        return None


def iter_files(root: Path, *, skip_dir_names: frozenset[str] = frozenset({TRASH_DIR_NAME})):
    """Yield all regular files under root, skipping trash/hidden service dirs."""
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dir_names]
        for filename in filenames:
            yield Path(dirpath) / filename


def ensure_hardlink(source: Path, target: Path, *, dry_run: bool) -> bool:
    """Ensure target is a hardlink of source. Returns True when a change was made."""
    source_stat = source.stat()
    try:
        target_stat = target.stat()
    except FileNotFoundError:
        target_stat = None
    if target_stat is not None and target_stat.st_ino == source_stat.st_ino:
        return False
    if dry_run:
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    if target_stat is not None:
        target.unlink()
    os.link(source, target)
    return True


def move_to_trash(path: Path, managed_root: Path, *, dry_run: bool) -> Path:
    """Soft-delete: move path into managed_root/.deletedByLibrariarr, unique name."""
    relative = path.relative_to(managed_root)
    destination = managed_root / TRASH_DIR_NAME / relative
    counter = 1
    while destination.exists():
        destination = destination.with_name(f"{destination.stem}.{counter}{destination.suffix}")
        counter += 1
    if not dry_run:
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(path, destination)
    return destination


def remove_file(path: Path, *, dry_run: bool) -> None:
    if not dry_run:
        path.unlink(missing_ok=True)


def prune_empty_dirs(root: Path, *, dry_run: bool) -> int:
    """Remove empty directories below root (never root itself). Returns count removed."""
    removed = 0
    if not root.is_dir():
        return removed
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        directory = Path(dirpath)
        if directory == root:
            continue
        if directory.name == TRASH_DIR_NAME or TRASH_DIR_NAME in directory.parts:
            continue
        if dry_run:
            if not dirnames and not filenames:
                removed += 1
            continue
        try:
            directory.rmdir()
            removed += 1
        except OSError:
            pass
    return removed


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class RootFilesystemMismatch(ValueError):
    """Configured roots do not all live on one filesystem.

    Hardlinks (the only mechanism used to keep the managed tree and Arr's
    library/shadow roots in sync) cannot cross a filesystem boundary — a
    cross-device "move" silently becomes a copy there, breaking the
    inode-identity guarantee reconcile depends on. Better to fail loudly at
    startup than to discover it as a silently-duplicated file later.
    """


def check_single_filesystem(roots: Iterable[Path]) -> None:
    """Raise RootFilesystemMismatch if any two *existing* roots differ in st_dev.

    Roots that don't exist yet (e.g. not created before first run) are
    skipped rather than treated as an error.
    """
    by_device: dict[int, list[Path]] = {}
    for root in roots:
        try:
            device = root.stat().st_dev
        except OSError:
            continue
        by_device.setdefault(device, []).append(root)
    if len(by_device) <= 1:
        return
    groups = "; ".join(
        f"filesystem {device}: {', '.join(str(p) for p in paths)}"
        for device, paths in by_device.items()
    )
    raise RootFilesystemMismatch(
        "Configured roots span more than one filesystem, which hardlinks cannot "
        f"cross ({groups}). All managed/library/shadow roots must be on one "
        "filesystem/volume — see docs/architecture.md Requirements."
    )
