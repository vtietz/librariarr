from __future__ import annotations

import logging
import os
from pathlib import Path

from ..clients.sonarr import SonarrClient
from ..config import AppConfig
from .bootstrap import probe_movie_root_mappings
from .executor import MovieProjectionExecutor
from .models import MovieProjectionMapping
from .provenance import ProjectionStateStore
from .sonarr_planner import build_series_projection_plans


class SonarrProjectionOrchestrator:
    def __init__(self, *, config: AppConfig, sonarr: SonarrClient, logger: logging.Logger) -> None:
        self.config = config
        self.sonarr = sonarr
        self.log = logger
        self.mappings = [
            MovieProjectionMapping(
                managed_root=Path(item.nested_root),
                library_root=Path(item.shadow_root),
            )
            for item in config.paths.root_mappings
        ]
        state_db_path = _sonarr_projection_state_db_path()
        self.state_store = ProjectionStateStore(state_db_path)
        self.executor = MovieProjectionExecutor(
            state_store=self.state_store,
            preserve_unknown_files=config.sonarr.projection.preserve_unknown_files,
        )

    def reconcile(self, scoped_series_ids: set[int] | None) -> dict[str, int]:
        series_items = self.sonarr.get_series()
        plans = build_series_projection_plans(
            config=self.config,
            series_items=series_items,
            mappings=self.mappings,
            scoped_series_ids=scoped_series_ids,
        )
        probes = probe_movie_root_mappings(self.mappings)
        scoped_count = (
            len(scoped_series_ids) if scoped_series_ids is not None else len(series_items)
        )
        metrics = self.executor.apply(
            plans=plans,
            probes=probes,
            scoped_movie_count=scoped_count,
        )
        self.log.info(
            "Sonarr projection reconcile: scoped_series=%s planned_series=%s skipped_series=%s "
            "projected_files=%s unchanged_files=%s skipped_files=%s",
            metrics.scoped_movie_count,
            metrics.planned_movies,
            metrics.skipped_movies,
            metrics.projected_files,
            metrics.unchanged_files,
            metrics.skipped_files,
        )
        return {
            "scoped_series_count": metrics.scoped_movie_count,
            "planned_series": metrics.planned_movies,
            "skipped_series": metrics.skipped_movies,
            "projected_files": metrics.projected_files,
            "unchanged_files": metrics.unchanged_files,
            "skipped_files": metrics.skipped_files,
        }


def _sonarr_projection_state_db_path() -> Path:
    configured = str(os.getenv("LIBRARIARR_SONARR_PROJECTION_STATE_PATH", "")).strip()
    if configured:
        return Path(configured)
    return Path("librariarr-sonarr-state.db")
