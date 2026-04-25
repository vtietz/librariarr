from __future__ import annotations

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
