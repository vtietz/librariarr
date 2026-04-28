from __future__ import annotations

import time
from pathlib import Path

from ..projection import get_radarr_webhook_queue, get_sonarr_webhook_queue
from .common import LOG
from .reconcile_autoadd import ServiceAutoAddMixin
from .reconcile_helpers import current_reconcile_source
from .reconcile_ingest import ServiceIngestMixin
from .reconcile_observability import first_path, log_projection_dispatch, log_scope_resolved


class ServiceReconcileMixin(ServiceIngestMixin, ServiceAutoAddMixin):
    def reconcile(
        self,
        affected_paths: set[Path] | None = None,
        *,
        refresh_arr_root_availability: bool = True,
        force_full_scope: bool = False,
    ) -> bool:
        with self._lock:
            reconcile_ctx = self._build_reconcile_context(
                affected_paths=affected_paths,
                refresh_arr_root_availability=refresh_arr_root_availability,
                force_full_scope=force_full_scope,
            )
            self._log_reconcile_start(reconcile_ctx)
            self._refresh_arr_root_availability_if_needed(
                reconcile_ctx["refresh_arr_root_availability"],
            )

            movies_inventory, series_inventory = self._fetch_inventories()
            ingested_movie_ids, auto_added_movie_ids, auto_added_series_ids = (
                self._collect_pre_projection_ids(
                    affected_paths=affected_paths,
                    movies_inventory=movies_inventory,
                    series_inventory=series_inventory,
                )
            )

            scope = self._resolve_projection_scope(
                force_full_scope=force_full_scope,
                incremental_mode=reconcile_ctx["incremental_mode"],
                ingested_movie_ids=ingested_movie_ids,
                auto_added_movie_ids=auto_added_movie_ids,
                auto_added_series_ids=auto_added_series_ids,
            )
            self._log_scope_resolution(
                reconcile_ctx=reconcile_ctx,
                scope=scope,
                ingested_movie_ids=ingested_movie_ids,
                auto_added_movie_ids=auto_added_movie_ids,
                auto_added_series_ids=auto_added_series_ids,
            )
            self._update_scope_tracking(scope)

            had_projection_error = False
            movie_projection_metrics, movie_projection_error = self._run_movie_projection(
                reconcile_ctx=reconcile_ctx,
                scope=scope,
                movies_inventory=movies_inventory,
            )
            had_projection_error = had_projection_error or movie_projection_error

            tracker = getattr(self, "runtime_status_tracker", None)
            if tracker is not None:
                tracker.update_reconcile_phase("indexed")

            series_projection_metrics, series_projection_error = self._run_series_projection(
                reconcile_ctx=reconcile_ctx,
                scope=scope,
                series_inventory=series_inventory,
            )
            had_projection_error = had_projection_error or series_projection_error
            if tracker is not None:
                tracker.update_reconcile_phase("cleaned")

            self._finalize_reconcile(
                reconcile_ctx=reconcile_ctx,
                force_full_scope=force_full_scope,
                movie_projection_metrics=movie_projection_metrics,
                series_projection_metrics=series_projection_metrics,
                ingested_movie_ids=ingested_movie_ids,
                auto_added_movie_ids=auto_added_movie_ids,
                auto_added_series_ids=auto_added_series_ids,
                queued_movie_ids=scope["queued_movie_ids"],
                queued_series_ids=scope["queued_series_ids"],
            )
            return had_projection_error

    def _build_reconcile_context(
        self,
        *,
        affected_paths: set[Path] | None,
        refresh_arr_root_availability: bool,
        force_full_scope: bool,
    ) -> dict:
        incremental_mode = bool(affected_paths)
        return {
            "started": time.time(),
            "incremental_mode": incremental_mode,
            "reconcile_mode": "incremental" if incremental_mode else "full",
            "affected_paths_count": len(affected_paths) if incremental_mode else "all",
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

    def _collect_pre_projection_ids(
        self,
        *,
        affected_paths: set[Path] | None,
        movies_inventory: list[dict] | None,
        series_inventory: list[dict] | None,
    ) -> tuple[set[int], set[int], set[int]]:
        ingested_movie_ids = self._ingest_movies_from_library_roots(
            affected_paths,
            movies_inventory=movies_inventory,
        )
        auto_added_movie_ids = self._auto_add_unmatched_movies(
            affected_paths,
            movies_inventory=movies_inventory,
        )
        auto_added_series_ids = self._auto_add_unmatched_series(
            affected_paths,
            series_inventory=series_inventory,
        )
        return ingested_movie_ids, auto_added_movie_ids, auto_added_series_ids

    def _resolve_projection_scope(
        self,
        *,
        force_full_scope: bool,
        incremental_mode: bool,
        ingested_movie_ids: set[int],
        auto_added_movie_ids: set[int],
        auto_added_series_ids: set[int],
    ) -> dict:
        scoped_movie_ids: set[int] | None = None
        queued_movie_ids: set[int] = set()
        if self.radarr_enabled:
            queued_movie_ids = get_radarr_webhook_queue().consume_movie_ids()
            if not force_full_scope and queued_movie_ids:
                scoped_movie_ids = queued_movie_ids

        if not force_full_scope:
            if ingested_movie_ids and (incremental_mode or scoped_movie_ids is not None):
                if scoped_movie_ids is None:
                    scoped_movie_ids = set(ingested_movie_ids)
                else:
                    scoped_movie_ids.update(ingested_movie_ids)
            if auto_added_movie_ids and (incremental_mode or scoped_movie_ids is not None):
                if scoped_movie_ids is None:
                    scoped_movie_ids = set(auto_added_movie_ids)
                else:
                    scoped_movie_ids.update(auto_added_movie_ids)

        scoped_series_ids: set[int] | None = None
        queued_series_ids: set[int] = set()
        if self.sonarr_enabled and self.sonarr_sync_enabled:
            queued_series_ids = get_sonarr_webhook_queue().consume_series_ids()
            if not force_full_scope and queued_series_ids:
                scoped_series_ids = queued_series_ids
        if (
            not force_full_scope
            and auto_added_series_ids
            and (incremental_mode or scoped_series_ids is not None)
        ):
            if scoped_series_ids is None:
                scoped_series_ids = set(auto_added_series_ids)
            else:
                scoped_series_ids.update(auto_added_series_ids)

        movie_scope_kind = "scoped" if scoped_movie_ids is not None else "full"
        series_scope_kind = "scoped" if scoped_series_ids is not None else "full"
        return {
            "scoped_movie_ids": scoped_movie_ids,
            "queued_movie_ids": queued_movie_ids,
            "movie_scope_kind": movie_scope_kind,
            "movie_full_scope_reason": self._full_scope_reason(
                scope_kind=movie_scope_kind,
                force_full_scope=force_full_scope,
                arr_enabled=self.radarr_enabled,
                incremental_mode=incremental_mode,
            ),
            "scoped_series_ids": scoped_series_ids,
            "queued_series_ids": queued_series_ids,
            "series_scope_kind": series_scope_kind,
            "series_full_scope_reason": self._full_scope_reason(
                scope_kind=series_scope_kind,
                force_full_scope=force_full_scope,
                arr_enabled=(self.sonarr_enabled and self.sonarr_sync_enabled),
                incremental_mode=incremental_mode,
            ),
        }

    def _full_scope_reason(
        self,
        *,
        scope_kind: str,
        force_full_scope: bool,
        arr_enabled: bool,
        incremental_mode: bool,
    ) -> str:
        if scope_kind == "scoped":
            return "-"
        if force_full_scope:
            return "force_full_scope"
        if not arr_enabled:
            return "arr_disabled_or_sync_disabled"
        if not incremental_mode:
            return "full_mode_requested"
        return "incremental_no_ids_from_sources"

    def _log_scope_resolution(
        self,
        *,
        reconcile_ctx: dict,
        scope: dict,
        ingested_movie_ids: set[int],
        auto_added_movie_ids: set[int],
        auto_added_series_ids: set[int],
    ) -> None:
        log_scope_resolved(
            trigger_source=reconcile_ctx["trigger_source"],
            reconcile_mode=reconcile_ctx["reconcile_mode"],
            affected_paths_count=reconcile_ctx["affected_paths_count"],
            trigger_path=reconcile_ctx["trigger_path"],
            movie_scope_kind=scope["movie_scope_kind"],
            movie_full_scope_reason=scope["movie_full_scope_reason"],
            scoped_movie_ids=scope["scoped_movie_ids"],
            queued_movie_ids=scope["queued_movie_ids"],
            ingested_movie_ids=ingested_movie_ids,
            auto_added_movie_ids=auto_added_movie_ids,
            series_scope_kind=scope["series_scope_kind"],
            series_full_scope_reason=scope["series_full_scope_reason"],
            scoped_series_ids=scope["scoped_series_ids"],
            queued_series_ids=scope["queued_series_ids"],
            auto_added_series_ids=auto_added_series_ids,
        )

    def _update_scope_tracking(self, scope: dict) -> None:
        tracker = getattr(self, "runtime_status_tracker", None)
        if tracker is None:
            return
        tracker.update_reconcile_phase("scope_resolved")
        tracker.update_active_reconcile_metrics(
            {
                "movie_items_targeted": (
                    len(scope["scoped_movie_ids"])
                    if scope["scoped_movie_ids"] is not None
                    else None
                ),
                "series_items_targeted": (
                    len(scope["scoped_series_ids"])
                    if scope["scoped_series_ids"] is not None
                    else None
                ),
                "movie_items_projected": 0,
                "series_items_projected": 0,
                "created_links": 0,
            }
        )

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
            metrics = self.movie_projection.reconcile(
                scope["scoped_movie_ids"],
                inventory=movies_inventory,
            )
            if tracker is not None:
                planned_movies = int(metrics.get("planned_movies") or 0)
                skipped_movies = int(metrics.get("skipped_movies") or 0)
                tracker.update_active_reconcile_metrics(
                    {
                        "movie_folders_seen": planned_movies,
                        "movie_items_projected": max(0, planned_movies - skipped_movies),
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
            metrics = self.sonarr_projection.reconcile(
                scope["scoped_series_ids"],
                inventory=series_inventory,
            )
            if tracker is not None:
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

    def _finalize_reconcile(
        self,
        *,
        reconcile_ctx: dict,
        force_full_scope: bool,
        movie_projection_metrics: dict,
        series_projection_metrics: dict,
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
                    "removed_orphans": 0,
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

    def reconcile_full(self) -> bool:
        return self.reconcile(affected_paths=None, force_full_scope=True)
