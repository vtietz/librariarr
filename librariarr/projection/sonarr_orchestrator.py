from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..clients.sonarr import SonarrClient
from ..config import AppConfig
from .bootstrap import probe_movie_root_mappings
from .executor import MovieProjectionExecutor
from .models import MovieProjectionMapping, MovieProjectionPlan
from .provenance import ProjectionStateStore
from .sonarr_planner import build_series_projection_plans, repair_unmatched_series_folders


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
            for item in config.paths.series_root_mappings
        ]
        state_db_path = _sonarr_projection_state_db_path()
        self.state_store = ProjectionStateStore(state_db_path)
        self.executor = MovieProjectionExecutor(
            state_store=self.state_store,
            preserve_unknown_files=config.sonarr.projection.preserve_unknown_files,
        )

    def reconcile(
        self,
        scoped_series_ids: set[int] | None,
        inventory: list[dict[str, Any]] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
        planning_progress_callback: Callable[[int, int], None] | None = None,
    ) -> dict[str, Any]:
        if inventory is not None:
            series_items = inventory
        elif scoped_series_ids is None:
            series_items = self.sonarr.get_series()
        elif len(scoped_series_ids) > self.config.runtime.scoped_fetch_threshold:
            series_items = self.sonarr.get_series()
        else:
            series_items = self.sonarr.get_series_by_ids(scoped_series_ids)

        if scoped_series_ids is None:
            self._repair_managed_folder_mappings(series_items)

        plans = build_series_projection_plans(
            config=self.config,
            series_items=series_items,
            mappings=self.mappings,
            scoped_series_ids=scoped_series_ids,
            planning_progress_callback=planning_progress_callback,
            provenance_folders=self.state_store.get_managed_folders_by_series_ids(),
        )
        normalized = self._normalize_arr_paths(series_items, plans)
        if normalized:
            self.log.info(
                "Normalized %s Sonarr series path(s) to flat library structure", normalized
            )
        probes = probe_movie_root_mappings(self.mappings)
        scoped_count = (
            len(scoped_series_ids) if scoped_series_ids is not None else len(series_items)
        )
        metrics = self.executor.apply(
            plans=plans,
            probes=probes,
            scoped_movie_count=scoped_count,
            progress_callback=progress_callback,
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
            "per_root": metrics.per_root_list(),
            "normalized_paths": normalized,
        }

    def _repair_managed_folder_mappings(self, series_items: list[dict[str, Any]]) -> None:
        """Discover managed folders for unmatched series and store mappings."""
        known_folders = self.state_store.get_managed_folders_by_series_ids()
        repairs = repair_unmatched_series_folders(
            series_items=series_items,
            mappings=self.mappings,
            known_folders=known_folders,
        )
        if repairs:
            for series_id, managed_folder in repairs:
                known_folders[series_id] = managed_folder

        provenance_repairs = self._repair_from_projection_provenance(
            series_items=series_items,
            known_folders=known_folders,
        )
        if provenance_repairs:
            repairs.extend(provenance_repairs)

        if repairs:
            self.state_store.set_managed_series_folders_bulk(repairs)
            self.log.info(
                "Repaired %s managed folder mapping(s) for previously-unmatched series",
                len(repairs),
            )

    def _repair_from_projection_provenance(
        self,
        *,
        series_items: list[dict[str, Any]],
        known_folders: dict[int, Path],
    ) -> list[tuple[int, Path]]:
        """Backfill series mappings from recorded projection source paths.

        This is a strict provenance-based repair path and does not rely on name matching.
        """
        managed_roots = [mapping.managed_root for mapping in self.mappings]
        repairs: list[tuple[int, Path]] = []

        for series in series_items:
            series_id = series.get("id")
            if not isinstance(series_id, int):
                continue

            existing = known_folders.get(series_id)
            if (
                existing
                and existing.exists()
                and existing.is_dir()
                and any(existing == root or root in existing.parents for root in managed_roots)
            ):
                continue

            entries = self.state_store.get_managed_entries_for_movie(series_id)
            if not entries:
                continue

            for _dest_path, source_path_raw in entries:
                if not source_path_raw:
                    continue
                source_path = Path(source_path_raw)
                for managed_root in managed_roots:
                    try:
                        relative = source_path.relative_to(managed_root)
                    except ValueError:
                        continue
                    if len(relative.parts) < 2:
                        continue
                    inferred_series_folder = managed_root / relative.parts[0]
                    if inferred_series_folder.exists() and inferred_series_folder.is_dir():
                        repairs.append((series_id, inferred_series_folder))
                        known_folders[series_id] = inferred_series_folder
                        break
                if series_id in known_folders:
                    break

        return repairs

    def _normalize_arr_paths(
        self,
        series_items: list[dict[str, Any]],
        plans: list[MovieProjectionPlan],
    ) -> int:
        """Update Sonarr series paths nested under a library root to flat canonical form."""
        plans_by_id = {p.movie_id: p for p in plans if not p.skip_reason}
        library_roots = {str(m.library_root) for m in self.mappings}
        normalized = 0
        for series in series_items:
            series_id = series.get("id")
            if not isinstance(series_id, int) or series_id not in plans_by_id:
                continue
            current_path = str(series.get("path") or "").strip()
            if not current_path:
                continue
            if not any(current_path.startswith(lr) for lr in library_roots):
                continue
            plan = plans_by_id[series_id]
            expected_path = str(plan.library_folder)
            if current_path == expected_path:
                continue
            try:
                if self.sonarr.update_series_path(series, expected_path):
                    normalized += 1
            except Exception as exc:
                self.log.warning(
                    "Failed to normalize Sonarr path for series_id=%s from=%s to=%s: %s",
                    series_id,
                    current_path,
                    expected_path,
                    exc,
                )
        return normalized


def _sonarr_projection_state_db_path() -> Path:
    configured = str(os.getenv("LIBRARIARR_SONARR_PROJECTION_STATE_PATH", "")).strip()
    if configured:
        return Path(configured)

    config_dir = Path("/config")
    if config_dir.is_dir() and os.access(config_dir, os.W_OK | os.X_OK):
        return config_dir / "librariarr-sonarr-state.db"

    cwd = Path.cwd()
    if os.access(cwd, os.W_OK | os.X_OK):
        return cwd / "librariarr-sonarr-state.db"

    return Path("/tmp") / "librariarr-sonarr-state.db"
