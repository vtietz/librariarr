from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .common import LOG
from .reconcile_helpers import folder_matches_affected_paths, library_equivalent_path


def normalize_radarr_paths_to_library_roots(
    *,
    radarr: Any,
    movie_root_mappings: list[tuple[Path, Path]],
    affected_paths: set[Path] | None,
    log_sync_config_hint: Callable[[Exception], None],
) -> set[int]:
    try:
        movies = radarr.get_movies()
    except Exception as exc:
        log_sync_config_hint(exc)
        LOG.warning(
            "Skipping Radarr path normalization because movie inventory fetch failed: %s",
            exc,
        )
        return set()

    normalized_movie_ids: set[int] = set()
    for movie in movies:
        movie_id = movie.get("id")
        movie_path_raw = str(movie.get("path") or "").strip()
        if not isinstance(movie_id, int) or not movie_path_raw:
            continue

        current_path = Path(movie_path_raw)
        if not folder_matches_affected_paths(current_path, affected_paths):
            continue

        target_path = library_equivalent_path(movie_path_raw, movie_root_mappings)
        if target_path is None:
            continue
        if current_path.resolve(strict=False) == target_path.resolve(strict=False):
            continue

        target_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            radarr.update_movie_path(movie, str(target_path))
        except Exception as exc:
            log_sync_config_hint(exc)
            LOG.warning(
                "Failed to normalize Radarr movie path to library root: "
                "movie_id=%s source=%s target=%s error=%s",
                movie_id,
                current_path,
                target_path,
                exc,
            )
            continue

        normalized_movie_ids.add(movie_id)
        LOG.info(
            "Normalized Radarr movie path to library root: movie_id=%s source=%s target=%s",
            movie_id,
            current_path,
            target_path,
        )

    return normalized_movie_ids
