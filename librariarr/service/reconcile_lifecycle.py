from __future__ import annotations

import time
from pathlib import Path

from .common import LOG
from .reconcile_helpers import current_reconcile_source, run_stale_shadow_cleanup
from .reconcile_observability import first_path


class ServiceReconcileLifecycleMixin:
    def _build_reconcile_context(
        self,
        *,
        affected_paths: set[Path] | None,
        refresh_arr_root_availability: bool,
        force_full_scope: bool,
    ) -> dict:
        incremental_mode = bool(affected_paths) and not force_full_scope
        return {
            "started": time.time(),
            "incremental_mode": incremental_mode,
            "reconcile_mode": "incremental" if incremental_mode else "full",
            "affected_paths_count": len(affected_paths) if incremental_mode else "all",
            "affected_paths": affected_paths,
            "trigger_source": current_reconcile_source(
                getattr(self, "runtime_status_tracker", None)
            ),
            "trigger_path": first_path(affected_paths),
            "force_full_scope": force_full_scope,
            "refresh_arr_root_availability": (
                True if force_full_scope else refresh_arr_root_availability
            ),
        }

    def _log_reconcile_start(self, reconcile_ctx: dict) -> None:
        LOG.info(
            "Reconcile started: source=%s mode=%s affected_paths=%s trigger_path=%s",
            reconcile_ctx["trigger_source"],
            reconcile_ctx["reconcile_mode"],
            reconcile_ctx["affected_paths_count"],
            reconcile_ctx["trigger_path"],
        )
        if reconcile_ctx["force_full_scope"]:
            LOG.info(
                "======== Full Reconcile started (source=%s) ========",
                reconcile_ctx["trigger_source"],
            )

    def _refresh_arr_root_availability_if_needed(self, refresh_arr_root_availability: bool) -> None:
        if refresh_arr_root_availability:
            self._update_arr_root_folder_availability(
                force=self._arr_root_poll_interval is None,
            )

    def _finalize_reconcile(
        self,
        *,
        reconcile_ctx: dict,
        force_full_scope: bool,
        movie_projection_metrics: dict,
        series_projection_metrics: dict,
        removed_orphans: int,
        ingested_movie_ids: set[int],
        auto_added_movie_ids: set[int],
        auto_added_series_ids: set[int],
        queued_movie_ids: set[int],
        queued_series_ids: set[int],
    ) -> None:
        tracker = getattr(self, "runtime_status_tracker", None)
        movie_projected_files = int(movie_projection_metrics.get("projected_files") or 0)
        series_projected_files = int(series_projection_metrics.get("projected_files") or 0)
        total_projected_files = movie_projected_files + series_projected_files
        matched_movies = max(
            0,
            int(movie_projection_metrics.get("planned_movies") or 0)
            - int(movie_projection_metrics.get("skipped_movies") or 0),
        )
        unmatched_movies = int(movie_projection_metrics.get("skipped_movies") or 0)
        matched_series = max(
            0,
            int(series_projection_metrics.get("planned_series") or 0)
            - int(series_projection_metrics.get("skipped_series") or 0),
        )
        unmatched_series = int(series_projection_metrics.get("skipped_series") or 0)
        duration_seconds = round(time.time() - reconcile_ctx["started"], 2)
        outcome = "updated"
        if (
            total_projected_files == 0
            and matched_movies == 0
            and unmatched_movies == 0
            and matched_series == 0
            and unmatched_series == 0
        ):
            outcome = "no_changes"

        if tracker is not None:
            affected_paths_count = reconcile_ctx["affected_paths_count"]
            _apc = int(affected_paths_count) if isinstance(affected_paths_count, int) else None
            tracker.update_active_reconcile_metrics(
                {
                    "active_movie_root": None,
                    "active_series_root": None,
                    "movie_folders_seen": int(movie_projection_metrics.get("planned_movies") or 0),
                    "series_folders_seen": int(
                        series_projection_metrics.get("planned_series") or 0
                    ),
                    "existing_links": 0,
                    "created_links": total_projected_files,
                    "matched_movies": matched_movies,
                    "unmatched_movies": unmatched_movies,
                    "matched_series": matched_series,
                    "unmatched_series": unmatched_series,
                    "removed_orphans": removed_orphans,
                    "duration_seconds": duration_seconds,
                    "affected_paths_count": _apc,
                }
            )

        LOG.info(
            "Reconcile finished: source=%s mode=%s affected_paths=%s trigger_path=%s "
            "outcome=%s projected_files=%s matched_movies=%s matched_series=%s "
            "duration_seconds=%s",
            reconcile_ctx["trigger_source"],
            reconcile_ctx["reconcile_mode"],
            reconcile_ctx["affected_paths_count"],
            reconcile_ctx["trigger_path"],
            outcome,
            total_projected_files,
            matched_movies,
            matched_series,
            duration_seconds,
        )
        if tracker is not None:
            tracker.update_reconcile_phase("completed")
        if force_full_scope:
            if tracker is not None:
                tracker.update_active_reconcile_metrics(
                    {
                        "full_reconcile_stats": {
                            "outcome": outcome,
                            "duration_seconds": duration_seconds,
                            "matched_movies": matched_movies,
                            "unmatched_movies": unmatched_movies,
                            "matched_series": matched_series,
                            "unmatched_series": unmatched_series,
                            "total_projected_files": total_projected_files,
                            "auto_added_movies": len(auto_added_movie_ids),
                            "auto_added_series": len(auto_added_series_ids),
                            "ingested_movies": len(ingested_movie_ids),
                            "drained_movie_queue": len(queued_movie_ids),
                            "drained_series_queue": len(queued_series_ids),
                            "removed_orphans": removed_orphans,
                        }
                    }
                )
            LOG.info(
                "======== Full Reconcile finished: outcome=%s duration=%.1fs "
                "movies(matched/unmatched)=%s/%s series(matched/unmatched)=%s/%s "
                "projected_files=%s auto_added_movies=%s auto_added_series=%s "
                "ingested=%s drained_queue(movies/series)=%s/%s ========",
                outcome,
                duration_seconds,
                matched_movies,
                unmatched_movies,
                matched_series,
                unmatched_series,
                total_projected_files,
                len(auto_added_movie_ids),
                len(auto_added_series_ids),
                len(ingested_movie_ids),
                len(queued_movie_ids),
                len(queued_series_ids),
            )

    def _run_stale_shadow_cleanup(
        self,
        *,
        reconcile_ctx: dict,
        scope: dict,
        movie_projection_metrics: dict,
        series_projection_metrics: dict,
    ) -> int:
        _ = scope
        return run_stale_shadow_cleanup(
            remove_orphaned_links=self.config.cleanup.remove_orphaned_links,
            reconcile_mode=str(reconcile_ctx.get("reconcile_mode") or "full"),
            affected_paths=reconcile_ctx.get("affected_paths"),
            movie_root_mappings=self.movie_root_mappings,
            series_root_mappings=self.series_root_mappings,
            movie_projection_metrics=movie_projection_metrics,
            series_projection_metrics=series_projection_metrics,
            radarr_enabled=bool(self.radarr_enabled and self.movie_projection is not None),
            sonarr_enabled=bool(
                self.sonarr_enabled
                and self.sonarr_sync_enabled
                and self.sonarr_projection is not None
            ),
            movie_projection=self.movie_projection,
            sonarr_projection=self.sonarr_projection,
        )

    def _publish_inventory_snapshot(self, movies: list[dict] | None, series: list[dict] | None):
        store = getattr(self, "inventory_snapshot_store", None)
        if store is not None:
            store.update(movies=movies, series=series, timestamp=time.time())
        tracker = getattr(self, "runtime_status_tracker", None)
        if tracker is not None:
            tracker.update_reconcile_phase("inventory_fetched")
            tracker.update_active_reconcile_metrics(
                {
                    "movie_folders_seen": len(movies) if movies else 0,
                    "series_folders_seen": len(series) if series else 0,
                }
            )
