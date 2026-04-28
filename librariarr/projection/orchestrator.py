from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from ..clients.radarr import RadarrClient
from ..config import AppConfig
from .bootstrap import probe_movie_root_mappings
from .executor import MovieProjectionExecutor
from .models import MovieProjectionMapping, MovieProjectionPlan
from .planner import build_movie_projection_plans
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
    ) -> dict[str, Any]:
        if inventory is not None:
            movies = inventory
        elif scoped_movie_ids is None:
            movies = self.radarr.get_movies()
        elif len(scoped_movie_ids) > self.config.runtime.scoped_fetch_threshold:
            movies = self.radarr.get_movies()
        else:
            movies = self.radarr.get_movies_by_ids(scoped_movie_ids)
        plans = build_movie_projection_plans(
            config=self.config,
            movies=movies,
            mappings=self.mappings,
            scoped_movie_ids=scoped_movie_ids,
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
        result = metrics.as_dict()
        result["per_root"] = metrics.per_root_list()
        result["normalized_paths"] = normalized
        return result

    def _normalize_arr_paths(
        self,
        movies: list[dict[str, Any]],
        plans: list[MovieProjectionPlan],
    ) -> int:
        """Update Radarr movie paths nested under a library root to flat canonical form."""
        plans_by_id = {p.movie_id: p for p in plans if not p.skip_reason}
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
            if current_path == expected_path:
                continue
            try:
                if self.radarr.update_movie_path(movie, expected_path):
                    normalized += 1
            except Exception as exc:
                self.log.warning(
                    "Failed to normalize Radarr path for movie_id=%s from=%s to=%s: %s",
                    movie_id,
                    current_path,
                    expected_path,
                    exc,
                )
        return normalized


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
