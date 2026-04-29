from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from ..projection.planner import classify_file
from ..sync.naming import canonical_name_from_folder

LOG = logging.getLogger(__name__)


def discover_unmatched_folders(
    *,
    mappings: list[tuple[Path, Path]],
    existing_paths: set[Path],
    affected_paths: set[Path] | None,
    discover_fn,
    video_exts: set[str],
    scan_exclude_paths: set[Path],
) -> list[Path]:
    discovered_folders: set[Path] = set()
    for managed_root, _library_root in mappings:
        discovered_folders.update(discover_fn(managed_root, video_exts, scan_exclude_paths))

    # Build a set of canonical leaf names from existing paths for fuzzy matching.
    # This handles managed folders with non-canonical names (e.g. "Title (Year) FSK6")
    # that map to canonical library paths ("Title (Year)") in Radarr.
    existing_canonical_parents: dict[Path, set[str]] = {}
    for ep in existing_paths:
        parent = ep.parent
        canonical_leaf = canonical_name_from_folder(ep.name).strip().lower()
        existing_canonical_parents.setdefault(parent, set()).add(canonical_leaf)

    return sorted(
        folder
        for folder in discovered_folders
        if not _folder_matches_existing(folder, existing_paths, existing_canonical_parents)
        and folder_matches_affected_paths(folder, affected_paths)
    )


def _folder_matches_existing(
    folder: Path,
    existing_paths: set[Path],
    existing_canonical_parents: dict[Path, set[str]],
) -> bool:
    resolved = folder.resolve(strict=False)
    if resolved in existing_paths:
        return True
    # Check if folder's canonical name matches an existing canonical name under same parent
    parent = resolved.parent
    canonical_leaf = canonical_name_from_folder(resolved.name).strip().lower()
    parent_set = existing_canonical_parents.get(parent)
    if parent_set and canonical_leaf in parent_set:
        return True
    return False


def folder_matches_affected_paths(
    folder: Path,
    affected_paths: set[Path] | None,
) -> bool:
    if not affected_paths:
        return True

    folder_resolved = folder.resolve(strict=False)
    for candidate in affected_paths:
        candidate_resolved = candidate.resolve(strict=False)
        if folder_resolved == candidate_resolved:
            return True
        if candidate_resolved in folder_resolved.parents:
            return True
        if folder_resolved in candidate_resolved.parents:
            return True
    return False


def resolve_managed_root_for_folder(
    folder: Path,
    mappings: list[tuple[Path, Path]],
) -> Path | None:
    sorted_mappings = sorted(mappings, key=lambda item: len(item[0].parts), reverse=True)
    for managed_root, _library_root in sorted_mappings:
        try:
            folder.relative_to(managed_root)
        except ValueError:
            continue
        return managed_root
    return None


def current_reconcile_source(runtime_status_tracker) -> str:
    if runtime_status_tracker is None:
        return "direct"

    try:
        snapshot = runtime_status_tracker.snapshot()
    except Exception:
        return "direct"

    if not isinstance(snapshot, dict):
        return "direct"

    current_task = snapshot.get("current_task")
    if not isinstance(current_task, dict):
        return "direct"

    trigger_source = current_task.get("trigger_source")
    if isinstance(trigger_source, str) and trigger_source.strip():
        return trigger_source

    return "direct"


def managed_equivalent_path(path_raw: str, mappings: list[tuple[Path, Path]]) -> Path | None:
    path = Path(path_raw)
    for managed_root, library_root in mappings:
        try:
            relative = path.relative_to(managed_root)
        except ValueError:
            pass
        else:
            return managed_root / relative

        try:
            relative = path.relative_to(library_root)
        except ValueError:
            continue
        return managed_root / relative
    return None


@dataclass(frozen=True)
class FileIngestResult:
    ingested_count: int
    failed_count: int


def ingest_files_from_library_folder(
    *,
    library_folder: Path,
    managed_folder: Path,
    managed_video_extensions: set[str],
    extras_allowlist: list[str],
) -> FileIngestResult:
    """Move files from library_folder into managed_folder when they differ by inode."""
    ingested = 0
    failed = 0

    for current, _dirs, files in os.walk(library_folder):
        current_path = Path(current)
        for filename in sorted(files):
            lib_file = current_path / filename
            relative_path = lib_file.relative_to(library_folder).as_posix()

            kind = classify_file(
                relative_path=relative_path,
                source_path=lib_file,
                managed_video_extensions=managed_video_extensions,
                extras_allowlist=extras_allowlist,
            )
            if kind is None:
                continue

            managed_file = managed_folder / relative_path
            result = _ingest_single_file(lib_file, managed_file)
            if result == "ingested":
                ingested += 1
            elif result == "failed":
                failed += 1

    return FileIngestResult(ingested_count=ingested, failed_count=failed)


def _ingest_single_file(lib_file: Path, managed_file: Path) -> str:
    """Move a single file from library root to managed root if inodes differ.

    Returns 'ingested', 'skipped', or 'failed'.
    """
    if not managed_file.exists():
        managed_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            lib_file.rename(managed_file)
        except OSError as exc:
            LOG.warning(
                "Ingest file move failed: src=%s dest=%s error=%s",
                lib_file,
                managed_file,
                exc,
            )
            return "failed"
        LOG.info(
            "FS MOVE file: source=%s destination=%s reason=managed_missing",
            lib_file,
            managed_file,
        )
        return "ingested"

    try:
        lib_stat = lib_file.stat()
        managed_stat = managed_file.stat()
    except OSError as exc:
        LOG.warning("Ingest stat failed: lib=%s managed=%s error=%s", lib_file, managed_file, exc)
        return "failed"

    if lib_stat.st_dev == managed_stat.st_dev and lib_stat.st_ino == managed_stat.st_ino:
        LOG.debug("FS SKIP file (same inode): source=%s destination=%s", lib_file, managed_file)
        return "skipped"

    backup_path = managed_file.with_suffix(managed_file.suffix + ".librariarr-ingest-tmp")
    try:
        managed_file.rename(backup_path)
    except OSError as exc:
        LOG.warning(
            "Cannot backup managed file for ingest, skipping: file=%s error=%s",
            managed_file,
            exc,
        )
        return "failed"
    LOG.info(
        "FS RENAME file: source=%s destination=%s reason=backup_before_replace",
        managed_file,
        backup_path,
    )

    try:
        lib_file.rename(managed_file)
    except OSError as exc:
        try:
            backup_path.rename(managed_file)
        except OSError as restore_exc:
            LOG.error(
                "Ingest move failed AND could not restore backup: dest=%s backup=%s error=%s",
                managed_file,
                backup_path,
                restore_exc,
            )
        else:
            LOG.warning(
                "FS RESTORE file after failed move: source=%s destination=%s error=%s",
                lib_file,
                managed_file,
                exc,
            )
        return "failed"

    backup_path.unlink(missing_ok=True)
    LOG.info(
        "FS MOVE file: source=%s destination=%s reason=replace_different_inode",
        lib_file,
        managed_file,
    )
    LOG.info("FS DELETE file: path=%s reason=cleanup_backup_after_replace", backup_path)
    return "ingested"
