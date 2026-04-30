from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

from ..clients.radarr import RadarrClient
from ..config import AppConfig
from .bootstrap import probe_movie_root_mappings
from .executor import MovieProjectionExecutor
from .models import MovieProjectionMapping, MovieProjectionPlan
from .planner import build_movie_projection_plans, repair_unmatched_managed_folders
from .provenance import ProjectionStateStore


class MovieProjectionOrchestrator:
    def __init__(self, *, config: AppConfig, radarr: RadarrClient, logger: logging.Logger) -> None:
        self.config = config
        self.radarr = radarr
        self.log = logger
        self.mappings = [
            MovieProjectionMapping(
                managed_root=Path(item.managed_root),
                library_root=Path(item.library_root),
            )
            for item in config.paths.movie_root_mappings
        ]
        state_db_path = _projection_state_db_path()
        self.state_store = ProjectionStateStore(state_db_path)
        self.executor = MovieProjectionExecutor(
            state_store=self.state_store,
            preserve_unknown_files=config.radarr.projection.preserve_unknown_files,
        )

    def reconcile(
        self,
        scoped_movie_ids: set[int] | None,
        inventory: list[dict[str, Any]] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
        planning_progress_callback: Callable[[int, int], None] | None = None,
    ) -> dict[str, Any]:
        if inventory is not None:
            movies = inventory
        elif scoped_movie_ids is None:
            movies = self.radarr.get_movies()
        elif len(scoped_movie_ids) > self.config.runtime.scoped_fetch_threshold:
            movies = self.radarr.get_movies()
        else:
            movies = self.radarr.get_movies_by_ids(scoped_movie_ids)

        # On full reconcile, repair unmatched managed folder mappings
        if scoped_movie_ids is None:
            self._repair_managed_folder_mappings(movies)

        plans = build_movie_projection_plans(
            config=self.config,
            movies=movies,
            mappings=self.mappings,
            scoped_movie_ids=scoped_movie_ids,
            planning_progress_callback=planning_progress_callback,
            provenance_folders=self.state_store.get_managed_folders_by_movie_ids(),
        )
        normalized = self._normalize_arr_paths(movies, plans)
        if normalized:
            self.log.info(
                "Normalized %s Radarr movie path(s) to flat library structure",
                normalized,
            )
        probes = probe_movie_root_mappings(self.mappings)
        scoped_count = len(scoped_movie_ids) if scoped_movie_ids is not None else len(movies)
        metrics = self.executor.apply(
            plans=plans,
            probes=probes,
            scoped_movie_count=scoped_count,
            progress_callback=progress_callback,
        )
        self.log.info(
            "Movie projection reconcile: scoped_movies=%s planned_movies=%s skipped_movies=%s "
            "projected_files=%s unchanged_files=%s skipped_files=%s",
            metrics.scoped_movie_count,
            metrics.planned_movies,
            metrics.skipped_movies,
            metrics.projected_files,
            metrics.unchanged_files,
            metrics.skipped_files,
        )
        refreshed_movie_count = self._refresh_projected_movies(metrics.projected_movie_ids)
        result = metrics.as_dict()
        result["per_root"] = metrics.per_root_list()
        result["normalized_paths"] = normalized
        result["refreshed_movies"] = refreshed_movie_count
        return result

    def _refresh_projected_movies(self, movie_ids: set[int]) -> int:
        if not movie_ids:
            return 0

        # Batch refresh commands to avoid hammering Radarr on large first runs.
        try:
            if hasattr(self.radarr, "refresh_movies"):
                refreshed = int(self.radarr.refresh_movies(movie_ids))
            else:
                refreshed = 0
                for movie_id in sorted(movie_ids):
                    if self.radarr.refresh_movie(movie_id):
                        refreshed += 1
        except requests.RequestException as exc:
            self.log.warning(
                "Radarr refresh queue failed after projection for %s movie(s): %s",
                len(movie_ids),
                exc,
            )
            return 0

        if refreshed > 0:
            self.log.info("Queued Radarr refresh for %s movie(s) after projection", refreshed)
        return refreshed

    def _repair_managed_folder_mappings(self, movies: list[dict[str, Any]]) -> None:
        """Discover managed folders for unmatched movies and store mappings."""
        known_folders = self.state_store.get_managed_folders_by_movie_ids()
        repairs = repair_unmatched_managed_folders(
            movies=movies,
            mappings=self.mappings,
            known_folders=known_folders,
        )
        if repairs:
            self.state_store.set_managed_folders_bulk(repairs)
            self.log.info(
                "Repaired %s managed folder mapping(s) for previously-unmatched movies",
                len(repairs),
            )

    def _normalize_arr_paths(
        self,
        movies: list[dict[str, Any]],
        plans: list[MovieProjectionPlan],
    ) -> int:
        """Update Radarr movie paths nested under a library root to flat canonical form."""
        plans_by_id = {p.movie_id: p for p in plans}
        library_roots = {str(m.library_root) for m in self.mappings}
        normalized = 0
        for movie in movies:
            movie_id = movie.get("id")
            if not isinstance(movie_id, int) or movie_id not in plans_by_id:
                continue
            current_path = str(movie.get("path") or "").strip()
            if not current_path:
                continue
            if not any(current_path.startswith(lr) for lr in library_roots):
                continue
            plan = plans_by_id[movie_id]
            expected_path = str(plan.library_folder)
            if expected_path in {"", "."}:
                continue
            if current_path == expected_path:
                continue
            try:
                if self.radarr.update_movie_path(movie, expected_path):
                    normalized += 1
            except Exception as exc:
                if self._try_normalize_with_temporary_path(
                    movie=movie,
                    current_path=current_path,
                    expected_path=expected_path,
                    exc=exc,
                ):
                    normalized += 1
                    continue
                self.log.warning(
                    "Failed to normalize Radarr path for movie_id=%s from=%s to=%s: %s",
                    movie_id,
                    current_path,
                    expected_path,
                    exc,
                )
        return normalized

    def _try_normalize_with_temporary_path(
        self,
        *,
        movie: dict[str, Any],
        current_path: str,
        expected_path: str,
        exc: Exception,
    ) -> bool:
        if not _is_ancestor_path_update_conflict(current_path, expected_path, exc):
            return False

        temp_path = _temporary_normalization_path(expected_path, int(movie.get("id") or 0))
        Path(temp_path).mkdir(parents=True, exist_ok=True)

        try:
            self.radarr.update_movie_path(movie, temp_path)
            self.radarr.update_movie_path(movie, expected_path)
            self.log.info(
                "Normalized Radarr path via temporary hop: movie_id=%s from=%s temp=%s to=%s",
                movie.get("id"),
                current_path,
                temp_path,
                expected_path,
            )
            return True
        except Exception:
            return False


def _projection_state_db_path() -> Path:
    configured = str(os.getenv("LIBRARIARR_PROJECTION_STATE_PATH", "")).strip()
    if configured:
        return Path(configured)

    config_dir = Path("/config")
    if config_dir.is_dir() and os.access(config_dir, os.W_OK | os.X_OK):
        return config_dir / "librariarr-state.db"

    cwd = Path.cwd()
    if os.access(cwd, os.W_OK | os.X_OK):
        return cwd / "librariarr-state.db"

    return Path("/tmp") / "librariarr-state.db"


def _temporary_normalization_path(expected_path: str, movie_id: int) -> str:
    expected = Path(expected_path)
    suffix = f".__librariarr_path_tmp_{movie_id or 'movie'}"
    return str(expected.parent / f"{expected.name}{suffix}")


def _is_ancestor_path_update_conflict(
    current_path: str,
    expected_path: str,
    exc: Exception,
) -> bool:
    current = Path(current_path)
    expected = Path(expected_path)
    try:
        is_nested = current != expected and current.is_relative_to(expected)
    except ValueError:
        is_nested = False

    if not is_nested:
        return False

    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        try:
            payload = exc.response.json()
        except Exception:
            payload = None
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                if str(item.get("errorCode") or "") == "MovieAncestorValidator":
                    return True

        body = str(getattr(exc.response, "text", "") or "").lower()
        if "movieancestorvalidator" in body or "ancestor of an existing movie" in body:
            return True

    text = str(exc).lower()
    return "movieancestorvalidator" in text or "ancestor of an existing movie" in text
