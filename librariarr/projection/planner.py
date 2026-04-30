from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..config import AppConfig
from .models import MovieProjectionMapping, MovieProjectionPlan
from .planner_common import (
    classify_file as common_classify_file,
)
from .planner_common import (
    collect_projection_files,
    emit_planning_progress,
    repair_unmatched_managed_folders_generic,
    resolve_library_folder,
    resolve_mapping_for_path,
)

PATH_SEPARATOR_TRANSLATION = str.maketrans({"/": "-", "\\": "-"})


def safe_path_component(name: str) -> str:
    return name.translate(PATH_SEPARATOR_TRANSLATION).strip()


def build_movie_projection_plans(
    *,
    config: AppConfig,
    movies: list[dict[str, Any]],
    mappings: list[MovieProjectionMapping],
    scoped_movie_ids: set[int] | None,
    planning_progress_callback: Callable[[int, int], None] | None = None,
    provenance_folders: dict[int, Path] | None = None,
) -> list[MovieProjectionPlan]:
    plans: list[MovieProjectionPlan] = []
    sorted_mappings = sorted(mappings, key=lambda item: len(item.managed_root.parts), reverse=True)

    target_movies = [
        movie
        for movie in movies
        if isinstance(movie.get("id"), int)
        and (scoped_movie_ids is None or int(movie.get("id")) in scoped_movie_ids)
    ]
    total_targets = len(target_movies)
    emit_planning_progress(planning_progress_callback, 0, total_targets)

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
            mapping, relative_movie_folder, path_mode = resolve_mapping_for_path(
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

            library_folder = resolve_library_folder(
                item=movie,
                relative_folder=relative_movie_folder,
                mapping=mapping,
                path_component_sanitizer=safe_path_component,
                fallback_prefix="movie",
            )

            # Resolve managed folder: direct path first, then stored mapping
            if path_mode == "managed":
                managed_folder = movie_path
            else:
                managed_folder = mapping.managed_root / relative_movie_folder

            if not managed_folder.exists() or not managed_folder.is_dir():
                # Use stored managed folder mapping (set by auto-add or repair)
                stored_folder = provenance_folders.get(movie_id) if provenance_folders else None
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
                    # Re-resolve mapping for the stored folder
                    for candidate_mapping in sorted_mappings:
                        try:
                            stored_folder.relative_to(candidate_mapping.managed_root)
                            mapping = candidate_mapping
                            break
                        except ValueError:
                            continue
                    library_folder = resolve_library_folder(
                        item=movie,
                        relative_folder=relative_movie_folder,
                        mapping=mapping,
                        path_component_sanitizer=safe_path_component,
                        fallback_prefix="movie",
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

            files = collect_projection_files(
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
            emit_planning_progress(planning_progress_callback, processed_count, total_targets)

    return plans


def repair_unmatched_managed_folders(
    *,
    movies: list[dict[str, Any]],
    mappings: list[MovieProjectionMapping],
    known_folders: dict[int, Path],
) -> list[tuple[int, Path]]:
    """Store managed folder mappings for movies whose path resolves directly.

    Returns (movie_id, managed_folder) pairs to store in provenance.
    """
    return repair_unmatched_managed_folders_generic(
        items=movies,
        mappings=mappings,
        known_folders=known_folders,
    )


def classify_file(
    *,
    relative_path: str,
    source_path: Path,
    managed_video_extensions: set[str],
    extras_allowlist: list[str],
) -> str | None:
    return common_classify_file(
        relative_path=relative_path,
        source_path=source_path,
        managed_video_extensions=managed_video_extensions,
        extras_allowlist=extras_allowlist,
    )
