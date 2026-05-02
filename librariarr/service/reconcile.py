from __future__ import annotations

from pathlib import Path

from .reconcile_autoadd import ServiceAutoAddMixin
from .reconcile_helpers import AffectedPathMatcher
from .reconcile_ingest import ServiceIngestMixin
from .reconcile_lifecycle import ServiceReconcileLifecycleMixin
from .reconcile_projection import ServiceReconcileProjectionMixin
from .reconcile_scope import ServiceReconcileScopeMixin


class ServiceReconcileMixin(
    ServiceReconcileLifecycleMixin,
    ServiceReconcileProjectionMixin,
    ServiceReconcileScopeMixin,
    ServiceIngestMixin,
    ServiceAutoAddMixin,
):
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
                affected_paths=affected_paths,
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

            removed_orphans = self._run_stale_shadow_cleanup(
                reconcile_ctx=reconcile_ctx,
                scope=scope,
                movie_projection_metrics=movie_projection_metrics,
                series_projection_metrics=series_projection_metrics,
            )

            self._finalize_reconcile(
                reconcile_ctx=reconcile_ctx,
                force_full_scope=force_full_scope,
                movie_projection_metrics=movie_projection_metrics,
                series_projection_metrics=series_projection_metrics,
                removed_orphans=removed_orphans,
                ingested_movie_ids=ingested_movie_ids,
                auto_added_movie_ids=auto_added_movie_ids,
                auto_added_series_ids=auto_added_series_ids,
                queued_movie_ids=scope["queued_movie_ids"],
                queued_series_ids=scope["queued_series_ids"],
            )
            return had_projection_error

    def _collect_pre_projection_ids(
        self,
        *,
        affected_paths: set[Path] | None,
        movies_inventory: list[dict] | None,
        series_inventory: list[dict] | None,
    ) -> tuple[set[int], set[int], set[int]]:
        matcher = AffectedPathMatcher(affected_paths)
        ingested_movie_ids = self._ingest_movies_from_library_roots(
            affected_paths,
            matcher=matcher,
            movies_inventory=movies_inventory,
        )
        auto_added_movie_ids = self._auto_add_unmatched_movies(
            affected_paths,
            matcher=matcher,
            movies_inventory=movies_inventory,
        )
        auto_added_series_ids = self._auto_add_unmatched_series(
            affected_paths,
            matcher=matcher,
            series_inventory=series_inventory,
        )
        return ingested_movie_ids, auto_added_movie_ids, auto_added_series_ids

    def reconcile_full(self) -> bool:
        return self.reconcile(affected_paths=None, force_full_scope=True)
