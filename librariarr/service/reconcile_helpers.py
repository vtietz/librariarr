from __future__ import annotations

import os
from pathlib import Path


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

    return sorted(
        folder
        for folder in discovered_folders
        if folder.resolve(strict=False) not in existing_paths
        and folder_matches_affected_paths(folder, affected_paths)
    )


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


def is_projected_shadow_folder(source_folder: Path, destination_folder: Path) -> bool:
    """Return True when source already mirrors destination via hardlinks."""
    if not source_folder.exists() or not source_folder.is_dir():
        return False
    if not destination_folder.exists() or not destination_folder.is_dir():
        return False

    source_files = folder_file_signature_map(source_folder)
    destination_files = folder_file_signature_map(destination_folder)
    if not source_files or not destination_files:
        return False
    if source_files.keys() != destination_files.keys():
        return False

    for relative_path, source_signature in source_files.items():
        destination_signature = destination_files.get(relative_path)
        if destination_signature is None:
            return False
        if source_signature != destination_signature:
            return False
    return True


def folder_file_signature_map(folder: Path) -> dict[str, tuple[int, int, int]]:
    signatures: dict[str, tuple[int, int, int]] = {}
    for current, _dirs, files in os.walk(folder):
        current_path = Path(current)
        for filename in files:
            file_path = current_path / filename
            if file_path.is_symlink():
                return {}
            try:
                stat_result = file_path.stat()
            except OSError:
                return {}
            relative = file_path.relative_to(folder).as_posix()
            signatures[relative] = (
                int(stat_result.st_dev),
                int(stat_result.st_ino),
                int(stat_result.st_size),
            )
    return signatures


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


def library_equivalent_path(path_raw: str, mappings: list[tuple[Path, Path]]) -> Path | None:
    path = Path(path_raw)
    for managed_root, library_root in mappings:
        try:
            relative = path.relative_to(managed_root)
        except ValueError:
            pass
        else:
            return library_root / relative

        try:
            relative = path.relative_to(library_root)
        except ValueError:
            continue
        return library_root / relative
    return None
