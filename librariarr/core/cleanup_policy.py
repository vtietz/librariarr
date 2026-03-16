from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CleanupTask:
    kind: str
    incremental_mode: bool
    affected_targets: set[Path]
    matched_item_ids: set[int]


def build_cleanup_tasks(
    *,
    remove_orphaned_links: bool,
    radarr_enabled: bool,
    sonarr_enabled: bool,
    movie_incremental_mode: bool,
    series_incremental_mode: bool,
    movie_affected_targets: set[Path],
    series_affected_targets: set[Path],
    matched_movie_ids: set[int],
    matched_series_ids: set[int],
) -> list[CleanupTask]:
    if not remove_orphaned_links:
        return []

    tasks: list[CleanupTask] = []
    if radarr_enabled:
        tasks.append(
            CleanupTask(
                kind="radarr",
                incremental_mode=movie_incremental_mode,
                affected_targets=movie_affected_targets,
                matched_item_ids=matched_movie_ids,
            )
        )
    if sonarr_enabled:
        tasks.append(
            CleanupTask(
                kind="sonarr",
                incremental_mode=series_incremental_mode,
                affected_targets=series_affected_targets,
                matched_item_ids=matched_series_ids,
            )
        )
    return tasks
