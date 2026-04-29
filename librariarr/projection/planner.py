from __future__ import annotations

import fnmatch
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..config import AppConfig
from ..sync.discovery import discover_movie_folders
from ..sync.naming import safe_path_component
from .models import MovieProjectionMapping, MovieProjectionPlan, PlannedProjectionFile


def build_movie_projection_plans(
    *,
    config: AppConfig,
    movies: list[dict[str, Any]],
    mappings: list[MovieProjectionMapping],
    scoped_movie_ids: set[int] | None,
    planning_progress_callback: Callable[[int, int], None] | None = None,
) -> list[MovieProjectionPlan]:
    plans: list[MovieProjectionPlan] = []
    sorted_mappings = sorted(mappings, key=lambda item: len(item.managed_root.parts), reverse=True)
    managed_lookup = _build_managed_folder_lookup(config=config, mappings=sorted_mappings)

    target_movies = [
        movie
        for movie in movies
        if isinstance(movie.get("id"), int)
        and (scoped_movie_ids is None or int(movie.get("id")) in scoped_movie_ids)
    ]
    total_targets = len(target_movies)
    _emit_planning_progress(planning_progress_callback, 0, total_targets)

    for processed_count, movie in enumerate(target_movies, start=1):
        try:
            movie_id = movie.get("id")
            if not isinstance(movie_id, int):
                continue

            movie_path_raw = str(movie.get("path") or "").strip()
            title = str(movie.get("title") or f"movie-{movie_id}")
            if not movie_path_raw:
                plans.append(
                    MovieProjectionPlan(
                        movie_id=movie_id,
                        title=title,
                        managed_folder=Path("."),
                        library_folder=Path("."),
                        mapping=None,
                        skip_reason="missing_movie_path",
                    )
                )
                continue

            movie_path = Path(movie_path_raw)
            mapping, relative_movie_folder, path_mode = _resolve_mapping_for_movie_path(
                movie_path,
                sorted_mappings,
            )
            if mapping is None or relative_movie_folder is None or path_mode is None:
                plans.append(
                    MovieProjectionPlan(
                        movie_id=movie_id,
                        title=title,
                        managed_folder=movie_path,
                        library_folder=Path("."),
                        mapping=None,
                        skip_reason="no_matching_managed_root",
                    )
                )
                continue

            library_folder = _resolve_library_folder(
                movie=movie,
                relative_movie_folder=relative_movie_folder,
                mapping=mapping,
            )
            if path_mode == "library":
                managed_folder = mapping.managed_root / relative_movie_folder
            else:
                managed_folder = movie_path

            if not managed_folder.exists() or not managed_folder.is_dir():
                fallback = _resolve_managed_fallback_folder(
                    movie=movie,
                    relative_movie_folder=relative_movie_folder,
                    default_mapping=mapping,
                    managed_lookup=managed_lookup,
                )
                if fallback is not None:
                    mapping, managed_folder = fallback
                    library_folder = _resolve_library_folder(
                        movie=movie,
                        relative_movie_folder=relative_movie_folder,
                        mapping=mapping,
                    )
                if not managed_folder.exists() or not managed_folder.is_dir():
                    plans.append(
                        MovieProjectionPlan(
                            movie_id=movie_id,
                            title=title,
                            managed_folder=managed_folder,
                            library_folder=library_folder,
                            mapping=mapping,
                            skip_reason="managed_folder_missing",
                        )
                    )
                    continue

            files = _collect_projection_files(
                managed_folder=managed_folder,
                library_folder=library_folder,
                managed_video_extensions=set(config.radarr.projection.managed_video_extensions),
                extras_allowlist=config.radarr.projection.managed_extras_allowlist,
            )
            plans.append(
                MovieProjectionPlan(
                    movie_id=movie_id,
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


def _resolve_mapping_for_movie_path(
    movie_path: Path,
    mappings: list[MovieProjectionMapping],
) -> tuple[MovieProjectionMapping | None, Path | None, str | None]:
    for mapping in mappings:
        try:
            relative = movie_path.relative_to(mapping.managed_root)
        except ValueError:
            pass
        else:
            return mapping, relative, "managed"

        try:
            relative = movie_path.relative_to(mapping.library_root)
        except ValueError:
            continue
        return mapping, relative, "library"
    return None, None, None


def _resolve_library_folder(
    *,
    movie: dict[str, Any],
    relative_movie_folder: Path,
    mapping: MovieProjectionMapping,
) -> Path:
    title = str(movie.get("title") or "").strip()
    year = movie.get("year")
    if title and isinstance(year, int):
        return mapping.library_root / safe_path_component(f"{title} ({year})")
    if title:
        return mapping.library_root / safe_path_component(title)

    fallback_name = relative_movie_folder.name or f"movie-{movie.get('id')}"
    return mapping.library_root / safe_path_component(fallback_name)


def _build_managed_folder_lookup(
    *,
    config: AppConfig,
    mappings: list[MovieProjectionMapping],
) -> dict[str, list[tuple[MovieProjectionMapping, Path]]]:
    lookup: dict[str, list[tuple[MovieProjectionMapping, Path]]] = {}
    video_exts = set(
        config.runtime.scan_video_extensions or config.radarr.projection.managed_video_extensions
    )
    exclude_patterns = list(config.paths.exclude_paths)

    for mapping in mappings:
        for folder in discover_movie_folders(mapping.managed_root, video_exts, exclude_patterns):
            key = folder.name.strip().lower()
            if not key:
                continue
            lookup.setdefault(key, []).append((mapping, folder))

    return lookup


def _resolve_managed_fallback_folder(
    *,
    movie: dict[str, Any],
    relative_movie_folder: Path,
    default_mapping: MovieProjectionMapping,
    managed_lookup: dict[str, list[tuple[MovieProjectionMapping, Path]]],
) -> tuple[MovieProjectionMapping, Path] | None:
    for key in _managed_lookup_keys(movie=movie, relative_movie_folder=relative_movie_folder):
        candidates = managed_lookup.get(key, [])
        if not candidates:
            continue

        # Prefer candidates from the same managed root mapping first.
        same_mapping = [item for item in candidates if item[0] == default_mapping]
        if len(same_mapping) == 1:
            return same_mapping[0]
        if len(candidates) == 1:
            return candidates[0]

    return None


def _managed_lookup_keys(*, movie: dict[str, Any], relative_movie_folder: Path) -> list[str]:
    keys: list[str] = []

    title = str(movie.get("title") or "").strip()
    year = movie.get("year")
    if title and isinstance(year, int):
        keys.append(safe_path_component(f"{title} ({year})").lower())
    if title:
        keys.append(safe_path_component(title).lower())

    leaf = relative_movie_folder.name.strip().lower()
    if leaf:
        keys.append(leaf)

    seen: set[str] = set()
    deduped: list[str] = []
    for key in keys:
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


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
            file_kind = classify_file(
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


def classify_file(
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
