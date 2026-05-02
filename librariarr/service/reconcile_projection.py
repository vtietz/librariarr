from __future__ import annotations

from .common import LOG
from .reconcile_observability import log_projection_dispatch


class ServiceReconcileProjectionMixin:
    def _fetch_inventories(self) -> tuple[list[dict] | None, list[dict] | None]:
        movies_inventory: list[dict] | None = None
        series_inventory: list[dict] | None = None
        if self.radarr_enabled:
            try:
                movies_inventory = self.radarr.get_movies()
            except Exception as exc:
                self._log_sync_config_hint(exc)
                LOG.warning("Radarr inventory fetch failed: %s", exc)
        if self.sonarr_enabled and self.sonarr_sync_enabled:
            try:
                series_inventory = self.sonarr.get_series()
            except Exception as exc:
                self._log_sonarr_sync_config_hint(exc)
                LOG.warning("Sonarr inventory fetch failed: %s", exc)
        self._publish_inventory_snapshot(movies_inventory, series_inventory)
        return movies_inventory, series_inventory

    def _run_movie_projection(
        self,
        *,
        reconcile_ctx: dict,
        scope: dict,
        movies_inventory: list[dict] | None,
    ) -> tuple[dict, bool]:
        tracker = getattr(self, "runtime_status_tracker", None)
        metrics = dict.fromkeys(
            [
                "scoped_movie_count",
                "planned_movies",
                "skipped_movies",
                "projected_files",
                "unchanged_files",
                "skipped_files",
            ],
            0,
        )
        metrics["matched_movie_ids"] = set()
        if not self.radarr_enabled:
            return metrics, False

        if self.movie_projection is None:
            raise RuntimeError("MovieProjectionOrchestrator is required when Radarr is enabled")

        self.movie_projection.radarr = self.radarr
        log_projection_dispatch(
            arr="radarr",
            trigger_source=reconcile_ctx["trigger_source"],
            reconcile_mode=reconcile_ctx["reconcile_mode"],
            scope_kind=scope["movie_scope_kind"],
            full_scope_reason=scope["movie_full_scope_reason"],
            scoped_ids=scope["scoped_movie_ids"],
        )
        try:
            last_movie_planning_progress = -1

            def _movie_planning_progress(processed: int, total: int) -> None:
                nonlocal last_movie_planning_progress
                if tracker is None:
                    return
                if processed != total and processed - last_movie_planning_progress < 25:
                    return
                last_movie_planning_progress = processed
                tracker.update_reconcile_phase("planning_movies")
                tracker.update_active_reconcile_metrics(
                    {
                        "movie_items_processed": processed,
                        "movie_items_total": total,
                    }
                )

            last_movie_progress = -1

            def _movie_progress(processed: int, total: int) -> None:
                nonlocal last_movie_progress
                if tracker is None:
                    return
                # Throttle frequent updates while still reporting completion promptly.
                if processed != total and processed - last_movie_progress < 25:
                    return
                last_movie_progress = processed
                tracker.update_reconcile_phase("indexed")
                tracker.update_active_reconcile_metrics(
                    {
                        "movie_items_processed": processed,
                        "movie_items_total": total,
                    }
                )

            metrics = self.movie_projection.reconcile(
                scope["scoped_movie_ids"],
                inventory=movies_inventory,
                progress_callback=_movie_progress,
                planning_progress_callback=_movie_planning_progress,
            )
            if tracker is not None:
                planned_movies = int(metrics.get("planned_movies") or 0)
                skipped_movies = int(metrics.get("skipped_movies") or 0)
                tracker.update_active_reconcile_metrics(
                    {
                        "movie_folders_seen": planned_movies,
                        "movie_items_projected": max(0, planned_movies - skipped_movies),
                        "movie_items_processed": planned_movies,
                        "movie_items_total": planned_movies,
                        "created_links": int(metrics.get("projected_files") or 0),
                    }
                )
                movie_per_root = metrics.get("per_root") or []
                tracker.update_library_root_stats(
                    [{**r, "arr_type": "radarr"} for r in movie_per_root]
                )
            return metrics, False
        except Exception as exc:
            self._log_sync_config_hint(exc)
            LOG.warning(
                "Continuing reconcile without Radarr projection due to request failure: %s",
                exc,
            )
            return metrics, True

    def _run_series_projection(
        self,
        *,
        reconcile_ctx: dict,
        scope: dict,
        series_inventory: list[dict] | None,
    ) -> tuple[dict, bool]:
        tracker = getattr(self, "runtime_status_tracker", None)
        metrics = dict.fromkeys(
            [
                "scoped_series_count",
                "planned_series",
                "skipped_series",
                "projected_files",
                "unchanged_files",
                "skipped_files",
            ],
            0,
        )
        metrics["matched_series_ids"] = set()
        if not (self.sonarr_enabled and self.sonarr_sync_enabled):
            return metrics, False

        if self.sonarr_projection is None:
            raise RuntimeError("SonarrProjectionOrchestrator is required when Sonarr is enabled")

        self.sonarr_projection.sonarr = self.sonarr
        log_projection_dispatch(
            arr="sonarr",
            trigger_source=reconcile_ctx["trigger_source"],
            reconcile_mode=reconcile_ctx["reconcile_mode"],
            scope_kind=scope["series_scope_kind"],
            full_scope_reason=scope["series_full_scope_reason"],
            scoped_ids=scope["scoped_series_ids"],
        )
        try:
            last_series_planning_progress = -1

            def _series_planning_progress(processed: int, total: int) -> None:
                nonlocal last_series_planning_progress
                if tracker is None:
                    return
                if processed != total and processed - last_series_planning_progress < 25:
                    return
                last_series_planning_progress = processed
                tracker.update_reconcile_phase("planning_series")
                tracker.update_active_reconcile_metrics(
                    {
                        "series_items_processed": processed,
                        "series_items_total": total,
                    }
                )

            last_series_progress = -1

            def _series_progress(processed: int, total: int) -> None:
                nonlocal last_series_progress
                if tracker is None:
                    return
                if processed != total and processed - last_series_progress < 25:
                    return
                last_series_progress = processed
                tracker.update_reconcile_phase("cleaned")
                tracker.update_active_reconcile_metrics(
                    {
                        "series_items_processed": processed,
                        "series_items_total": total,
                    }
                )

            metrics = self.sonarr_projection.reconcile(
                scope["scoped_series_ids"],
                inventory=series_inventory,
                progress_callback=_series_progress,
                planning_progress_callback=_series_planning_progress,
            )
            if tracker is not None:
                planned_series = int(metrics.get("planned_series") or 0)
                skipped_series = int(metrics.get("skipped_series") or 0)
                tracker.update_active_reconcile_metrics(
                    {
                        "series_items_projected": max(0, planned_series - skipped_series),
                        "series_items_processed": planned_series,
                        "series_items_total": planned_series,
                    }
                )
                series_per_root = metrics.get("per_root") or []
                tracker.update_library_root_stats(
                    [{**r, "arr_type": "sonarr"} for r in series_per_root]
                )
            return metrics, False
        except Exception as exc:
            self._log_sonarr_sync_config_hint(exc)
            LOG.warning(
                "Continuing reconcile without Sonarr projection due to request failure: %s",
                exc,
            )
            return metrics, True
