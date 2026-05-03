from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.cleanup_policy import build_cleanup_tasks
from ..projection.planner import classify_file

LOG = logging.getLogger(__name__)


class AffectedPathMatcher:
    def __init__(self, affected_paths: set[Path] | None) -> None:
        self._affected_resolved = (
            {path.resolve(strict=False) for path in affected_paths} if affected_paths else set()
        )
        self._match_cache: dict[Path, bool] = {}

    @property
    def enabled(self) -> bool:
        return bool(self._affected_resolved)

    def matches(self, folder: Path) -> bool:
        if not self._affected_resolved:
            return True

        folder_resolved = folder.resolve(strict=False)
        cached = self._match_cache.get(folder_resolved)
        if cached is not None:
            return cached

        for candidate_resolved in self._affected_resolved:
            if folder_resolved == candidate_resolved:
                self._match_cache[folder_resolved] = True
                return True
            if candidate_resolved in folder_resolved.parents:
                self._match_cache[folder_resolved] = True
                return True
            if folder_resolved in candidate_resolved.parents:
                self._match_cache[folder_resolved] = True
                return True

        self._match_cache[folder_resolved] = False
        return False


def discover_unmatched_folders(
    *,
    mappings: list[tuple[Path, Path]],
    existing_paths: set[Path],
    affected_paths: set[Path] | None,
    matcher: AffectedPathMatcher | None = None,
    discover_fn,
    video_exts: set[str],
    scan_exclude_paths: set[Path],
) -> list[Path]:
    resolved_matcher = matcher or AffectedPathMatcher(affected_paths)
    discovered_folders: set[Path] = set()
    for managed_root, library_root in mappings:
        if resolved_matcher.enabled and not (
            resolved_matcher.matches(managed_root) or resolved_matcher.matches(library_root)
        ):
            continue
        discovered_folders.update(discover_fn(managed_root, video_exts, scan_exclude_paths))

    return sorted(
        folder
        for folder in discovered_folders
        if not _folder_matches_existing(folder, existing_paths)
        and folder_matches_affected_paths(folder, affected_paths, matcher=resolved_matcher)
    )


def _folder_matches_existing(
    folder: Path,
    existing_paths: set[Path],
) -> bool:
    resolved = folder.resolve(strict=False)
    return resolved in existing_paths


def folder_matches_affected_paths(
    folder: Path,
    affected_paths: set[Path] | None,
    matcher: AffectedPathMatcher | None = None,
) -> bool:
    resolved_matcher = matcher or AffectedPathMatcher(affected_paths)
    return resolved_matcher.matches(folder)


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


def resolve_cleanup_targets(
    *,
    affected_paths: set[Path] | None,
    mappings: list[tuple[Path, Path]],
) -> set[Path]:
    """Map affected managed/library paths to library-target cleanup scope."""
    if not affected_paths:
        return set()

    targets: set[Path] = set()
    for affected in affected_paths:
        resolved = affected.resolve(strict=False)
        for managed_root, library_root in mappings:
            try:
                relative = resolved.relative_to(managed_root)
            except ValueError:
                pass
            else:
                targets.add((library_root / relative).resolve(strict=False))
                targets.add(library_root.resolve(strict=False))
                continue

            try:
                resolved.relative_to(library_root)
            except ValueError:
                continue
            targets.add(resolved)
            targets.add(library_root.resolve(strict=False))

    return targets


def run_stale_shadow_cleanup(
    *,
    remove_orphaned_links: bool,
    reconcile_mode: str,
    affected_paths: set[Path] | None,
    movie_root_mappings: list[tuple[Path, Path]],
    series_root_mappings: list[tuple[Path, Path]],
    movie_projection_metrics: dict[str, Any],
    series_projection_metrics: dict[str, Any],
    radarr_enabled: bool,
    sonarr_enabled: bool,
    movie_projection,
    sonarr_projection,
) -> int:
    if not remove_orphaned_links:
        return 0

    movie_affected_targets = resolve_cleanup_targets(
        affected_paths=affected_paths,
        mappings=movie_root_mappings,
    )
    series_affected_targets = resolve_cleanup_targets(
        affected_paths=affected_paths,
        mappings=series_root_mappings,
    )

    matched_movie_ids = set(movie_projection_metrics.get("matched_movie_ids") or set())
    matched_series_ids = set(series_projection_metrics.get("matched_series_ids") or set())

    tasks = build_cleanup_tasks(
        remove_orphaned_links=remove_orphaned_links,
        radarr_enabled=radarr_enabled,
        sonarr_enabled=sonarr_enabled,
        movie_incremental_mode=(reconcile_mode == "incremental"),
        series_incremental_mode=(reconcile_mode == "incremental"),
        movie_affected_targets=movie_affected_targets,
        series_affected_targets=series_affected_targets,
        matched_movie_ids=matched_movie_ids,
        matched_series_ids=matched_series_ids,
    )

    removed_orphans = 0
    for task in tasks:
        if not task.matched_item_ids:
            continue
        cleanup_targets = (
            None
            if task.incremental_mode
            else (set(task.affected_targets) if task.affected_targets else None)
        )
        if task.kind == "radarr":
            if movie_projection is None:
                continue
            cleanup_result = movie_projection.cleanup_stale_shadow(
                candidate_ids=set(task.matched_item_ids),
                affected_targets=cleanup_targets,
            )
        else:
            if sonarr_projection is None:
                continue
            cleanup_result = sonarr_projection.cleanup_stale_shadow(
                candidate_ids=set(task.matched_item_ids),
                affected_targets=cleanup_targets,
            )
        removed_orphans += int(cleanup_result.get("removed_files") or 0)

    if removed_orphans > 0:
        LOG.info("Stale shadow cleanup removed %s orphaned managed file(s)", removed_orphans)
    return removed_orphans


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
