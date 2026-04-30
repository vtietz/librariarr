from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..config import AppConfig
from ..sync.naming import safe_path_component
from .models import MovieProjectionMapping, MovieProjectionPlan
from .planner_common import (
    collect_projection_files,
    emit_planning_progress,
    repair_unmatched_managed_folders_generic,
    resolve_library_folder,
    resolve_mapping_for_path,
)


def build_series_projection_plans(
    *,
    config: AppConfig,
    series_items: list[dict[str, Any]],
    mappings: list[MovieProjectionMapping],
    scoped_series_ids: set[int] | None,
    planning_progress_callback: Callable[[int, int], None] | None = None,
    provenance_folders: dict[int, Path] | None = None,
) -> list[MovieProjectionPlan]:
    plans: list[MovieProjectionPlan] = []
    sorted_mappings = sorted(mappings, key=lambda item: len(item.managed_root.parts), reverse=True)

    target_series = [
        series
        for series in series_items
        if isinstance(series.get("id"), int)
        and (scoped_series_ids is None or int(series.get("id")) in scoped_series_ids)
    ]
    total_targets = len(target_series)
    emit_planning_progress(planning_progress_callback, 0, total_targets)

    for processed_count, series in enumerate(target_series, start=1):
        try:
            series_id = series.get("id")
            if not isinstance(series_id, int):
                continue

            series_path_raw = str(series.get("path") or "").strip()
            title = str(series.get("title") or f"series-{series_id}")
            if not series_path_raw:
                plans.append(
                    MovieProjectionPlan(
                        movie_id=series_id,
                        title=title,
                        managed_folder=Path("."),
                        library_folder=Path("."),
                        mapping=None,
                        skip_reason="missing_series_path",
                    )
                )
                continue

            series_path = Path(series_path_raw)
            mapping, relative_series_folder, path_mode = resolve_mapping_for_path(
                series_path,
                sorted_mappings,
            )
            if mapping is None or relative_series_folder is None or path_mode is None:
                plans.append(
                    MovieProjectionPlan(
                        movie_id=series_id,
                        title=title,
                        managed_folder=series_path,
                        library_folder=Path("."),
                        mapping=None,
                        skip_reason="no_matching_series_managed_root",
                    )
                )
                continue

            library_folder = resolve_library_folder(
                item=series,
                relative_folder=relative_series_folder,
                mapping=mapping,
                path_component_sanitizer=safe_path_component,
                fallback_prefix="series",
            )
            if path_mode == "managed":
                managed_folder = series_path
            else:
                managed_folder = mapping.managed_root / relative_series_folder

            if not managed_folder.exists() or not managed_folder.is_dir():
                stored_folder = provenance_folders.get(series_id) if provenance_folders else None
                if (
                    stored_folder
                    and stored_folder.exists()
                    and stored_folder.is_dir()
                    and any(
                        stored_folder == m.managed_root or m.managed_root in stored_folder.parents
                        for m in sorted_mappings
                    )
                ):
                    managed_folder = stored_folder
                    for candidate_mapping in sorted_mappings:
                        try:
                            stored_folder.relative_to(candidate_mapping.managed_root)
                            mapping = candidate_mapping
                            break
                        except ValueError:
                            continue
                    library_folder = resolve_library_folder(
                        item=series,
                        relative_folder=relative_series_folder,
                        mapping=mapping,
                        path_component_sanitizer=safe_path_component,
                        fallback_prefix="series",
                    )

            if not managed_folder.exists() or not managed_folder.is_dir():
                plans.append(
                    MovieProjectionPlan(
                        movie_id=series_id,
                        title=title,
                        managed_folder=managed_folder,
                        library_folder=library_folder,
                        mapping=mapping,
                        skip_reason="managed_series_folder_missing",
                    )
                )
                continue

            files = collect_projection_files(
                managed_folder=managed_folder,
                library_folder=library_folder,
                managed_video_extensions=set(config.sonarr.projection.managed_video_extensions),
                extras_allowlist=config.sonarr.projection.managed_extras_allowlist,
            )
            plans.append(
                MovieProjectionPlan(
                    movie_id=series_id,
                    title=title,
                    managed_folder=managed_folder,
                    library_folder=library_folder,
                    mapping=mapping,
                    files=files,
                )
            )
        finally:
            emit_planning_progress(planning_progress_callback, processed_count, total_targets)

    return plans


def repair_unmatched_series_folders(
    *,
    series_items: list[dict[str, Any]],
    mappings: list[MovieProjectionMapping],
    known_folders: dict[int, Path],
) -> list[tuple[int, Path]]:
    """Store managed folder mappings for series whose path resolves directly."""
    return repair_unmatched_managed_folders_generic(
        items=series_items,
        mappings=mappings,
        known_folders=known_folders,
    )
