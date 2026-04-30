from __future__ import annotations

import fnmatch
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..config import AppConfig
from ..sync.naming import safe_path_component
from .models import MovieProjectionMapping, MovieProjectionPlan, PlannedProjectionFile


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
    _emit_planning_progress(planning_progress_callback, 0, total_targets)

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
            mapping, relative_series_folder, path_mode = _resolve_mapping_for_series_path(
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

            library_folder = _resolve_library_folder(
                series=series,
                relative_series_folder=relative_series_folder,
                mapping=mapping,
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
                    library_folder = _resolve_library_folder(
                        series=series,
                        relative_series_folder=relative_series_folder,
                        mapping=mapping,
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

            files = _collect_projection_files(
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
            _emit_planning_progress(planning_progress_callback, processed_count, total_targets)

    return plans


def repair_unmatched_series_folders(
    *,
    series_items: list[dict[str, Any]],
    mappings: list[MovieProjectionMapping],
    known_folders: dict[int, Path],
) -> list[tuple[int, Path]]:
    """Store managed folder mappings for series whose path resolves directly."""
    sorted_mappings = sorted(mappings, key=lambda item: len(item.managed_root.parts), reverse=True)
    repairs: list[tuple[int, Path]] = []
    managed_roots = {m.managed_root for m in mappings}

    for series in series_items:
        series_id = series.get("id")
        if not isinstance(series_id, int):
            continue

        existing = known_folders.get(series_id)
        if (
            existing
            and existing.exists()
            and existing.is_dir()
            and any(existing == mr or mr in existing.parents for mr in managed_roots)
        ):
            continue

        series_path_raw = str(series.get("path") or "").strip()
        if not series_path_raw:
            continue

        series_path = Path(series_path_raw)
        mapping, relative_series_folder, path_mode = _resolve_mapping_for_series_path(
            series_path,
            sorted_mappings,
        )
        if mapping is None or relative_series_folder is None:
            continue

        if path_mode == "managed":
            if series_path.exists() and series_path.is_dir():
                repairs.append((series_id, series_path))
        else:
            direct = mapping.managed_root / relative_series_folder
            if direct.exists() and direct.is_dir():
                repairs.append((series_id, direct))

    return repairs


def _resolve_mapping_for_series_path(
    series_path: Path,
    mappings: list[MovieProjectionMapping],
) -> tuple[MovieProjectionMapping | None, Path | None, str | None]:
    for mapping in mappings:
        try:
            relative = series_path.relative_to(mapping.managed_root)
        except ValueError:
            pass
        else:
            return mapping, relative, "managed"

        try:
            relative = series_path.relative_to(mapping.library_root)
        except ValueError:
            continue
        return mapping, relative, "library"
    return None, None, None


def _resolve_library_folder(
    *,
    series: dict[str, Any],
    relative_series_folder: Path,
    mapping: MovieProjectionMapping,
) -> Path:
    title = str(series.get("title") or "").strip()
    year = series.get("year")
    if title and isinstance(year, int):
        return mapping.library_root / safe_path_component(f"{title} ({year})")
    if title:
        return mapping.library_root / safe_path_component(title)

    fallback_name = relative_series_folder.name or f"series-{series.get('id')}"
    return mapping.library_root / safe_path_component(fallback_name)


def _collect_projection_files(
    *,
    managed_folder: Path,
    library_folder: Path,
    managed_video_extensions: set[str],
    extras_allowlist: list[str],
) -> list[PlannedProjectionFile]:
    planned_files: list[PlannedProjectionFile] = []
    for current, _dirs, files in os.walk(managed_folder):
        current_path = Path(current)
        for filename in sorted(files):
            source_path = current_path / filename
            relative_path = source_path.relative_to(managed_folder).as_posix()
            file_kind = _classify_file(
                relative_path=relative_path,
                source_path=source_path,
                managed_video_extensions=managed_video_extensions,
                extras_allowlist=extras_allowlist,
            )
            if file_kind is None:
                continue
            planned_files.append(
                PlannedProjectionFile(
                    relative_path=relative_path,
                    source_path=source_path,
                    dest_path=library_folder / relative_path,
                    kind=file_kind,
                )
            )
    return planned_files


def _classify_file(
    *,
    relative_path: str,
    source_path: Path,
    managed_video_extensions: set[str],
    extras_allowlist: list[str],
) -> str | None:
    suffix = source_path.suffix.lower()
    if suffix in managed_video_extensions:
        return "video"

    relative_lower = relative_path.lower()
    name_lower = source_path.name.lower()
    for pattern in extras_allowlist:
        normalized_pattern = str(pattern).strip().lower()
        if not normalized_pattern:
            continue
        if fnmatch.fnmatch(name_lower, normalized_pattern):
            return "extra"
        if fnmatch.fnmatch(relative_lower, normalized_pattern):
            return "extra"

    return None


def _emit_planning_progress(
    callback: Callable[[int, int], None] | None,
    processed: int,
    total: int,
) -> None:
    if callback is not None:
        callback(processed, total)
