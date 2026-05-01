from __future__ import annotations

from pathlib import Path

from ..projection import get_radarr_webhook_queue, get_sonarr_webhook_queue
from .reconcile_observability import log_scope_resolved
from .scope_resolution import resolve_projection_scope


class ServiceReconcileScopeMixin:
    def _resolve_projection_scope(
        self,
        *,
        force_full_scope: bool,
        incremental_mode: bool,
        affected_paths: set[Path] | None,
        ingested_movie_ids: set[int],
        auto_added_movie_ids: set[int],
        auto_added_series_ids: set[int],
    ) -> dict:
        queued_movie_ids = (
            get_radarr_webhook_queue().consume_movie_ids() if self.radarr_enabled else set()
        )
        queued_series_ids = (
            get_sonarr_webhook_queue().consume_series_ids()
            if self.sonarr_enabled and self.sonarr_sync_enabled
            else set()
        )
        affected_path_movie_ids: set[int] = set()
        affected_path_series_ids: set[int] = set()
        if not force_full_scope and incremental_mode and affected_paths:
            (
                affected_path_movie_ids,
                affected_path_series_ids,
            ) = self._resolve_ids_from_affected_paths(affected_paths)

        scope = resolve_projection_scope(
            force_full_scope=force_full_scope,
            incremental_mode=incremental_mode,
            radarr_enabled=self.radarr_enabled,
            sonarr_enabled=self.sonarr_enabled,
            sonarr_sync_enabled=self.sonarr_sync_enabled,
            queued_movie_ids=queued_movie_ids,
            queued_series_ids=queued_series_ids,
            ingested_movie_ids=ingested_movie_ids,
            auto_added_movie_ids=auto_added_movie_ids,
            auto_added_series_ids=auto_added_series_ids,
            affected_path_movie_ids=affected_path_movie_ids,
            affected_path_series_ids=affected_path_series_ids,
        )
        return scope.as_dict()

    def _resolve_ids_from_affected_paths(
        self,
        affected_paths: set[Path],
    ) -> tuple[set[int], set[int]]:
        """Resolve movie/series IDs from affected paths via provenance DB."""
        scoped_movie_ids: set[int] = set()
        scoped_series_ids: set[int] = set()
        if self.radarr_enabled:
            movie_proj = getattr(self, "movie_projection", None)
            if movie_proj is not None:
                path_movie_ids = movie_proj.state_store.resolve_movie_ids_by_paths(affected_paths)
                if path_movie_ids:
                    scoped_movie_ids.update(path_movie_ids)
        if self.sonarr_enabled and self.sonarr_sync_enabled:
            sonarr_proj = getattr(self, "sonarr_projection", None)
            if sonarr_proj is not None:
                path_series_ids = sonarr_proj.state_store.resolve_series_ids_by_paths(
                    affected_paths
                )
                if path_series_ids:
                    scoped_series_ids.update(path_series_ids)
        return scoped_movie_ids, scoped_series_ids

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
                "movie_items_processed": 0,
                "series_items_processed": 0,
                "movie_items_total": 0,
                "series_items_total": 0,
                "created_links": 0,
            }
        )
