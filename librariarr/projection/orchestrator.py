from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from ..clients.radarr import RadarrClient
from ..config import AppConfig
from .bootstrap import probe_movie_root_mappings
from .executor import MovieProjectionExecutor
from .models import MovieProjectionMapping
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

    def reconcile(self, scoped_movie_ids: set[int] | None) -> dict[str, Any]:
        if scoped_movie_ids is None:
            movies = self.radarr.get_movies()
        else:
            movies = self.radarr.get_movies_by_ids(scoped_movie_ids)
        plans = build_movie_projection_plans(
            config=self.config,
            movies=movies,
            mappings=self.mappings,
            scoped_movie_ids=scoped_movie_ids,
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
        return result


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
