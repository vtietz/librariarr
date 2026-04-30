"""Auto-add mixin: discovers unmatched folders and adds them to Radarr/Sonarr."""

from __future__ import annotations

from pathlib import Path

from ..sync.discovery import discover_movie_folders, discover_series_folders
from .common import LOG
from .reconcile_helpers import (
    AffectedPathMatcher,
    discover_unmatched_folders,
    managed_equivalent_path,
    resolve_managed_root_for_folder,
)


class ServiceAutoAddMixin:
    """Methods for auto-adding unmatched movies/series from managed roots."""

    def _auto_add_unmatched_movies(
        self,
        affected_paths: set[Path] | None,
        matcher: AffectedPathMatcher | None = None,
        movies_inventory: list[dict] | None = None,
    ) -> set[int]:
        if not (self.radarr_enabled and self.sync_enabled and self.auto_add_unmatched):
            return set()

        if movies_inventory is not None:
            movies = movies_inventory
        else:
            try:
                movies = self.radarr.get_movies()
            except Exception as exc:
                self._log_sync_config_hint(exc)
                LOG.warning("Skipping Radarr auto-add: inventory fetch failed: %s", exc)
                return set()

        resolved_matcher = matcher or AffectedPathMatcher(affected_paths)
        existing_paths = {
            managed_path.resolve(strict=False)
            for managed_path in (
                managed_equivalent_path(
                    str(movie.get("path") or "").strip(),
                    self.movie_root_mappings,
                )
                for movie in movies
            )
            if managed_path is not None
        }

        unmatched_folders = discover_unmatched_folders(
            mappings=self.movie_root_mappings,
            existing_paths=existing_paths,
            affected_paths=affected_paths,
            matcher=resolved_matcher,
            discover_fn=discover_movie_folders,
            video_exts=self.video_exts,
            scan_exclude_paths=self.scan_exclude_paths,
        )
        if not unmatched_folders:
            return set()

        tracker = getattr(self, "runtime_status_tracker", None)
        if tracker is not None:
            tracker.update_reconcile_phase("auto_add_movies")
            tracker.update_active_reconcile_metrics(
                {
                    "movie_items_processed": 0,
                    "movie_items_total": len(unmatched_folders),
                }
            )

        added_movie_ids: set[int] = set()
        for processed_count, folder in enumerate(unmatched_folders, start=1):
            managed_root = resolve_managed_root_for_folder(folder, self.movie_root_mappings)
            if managed_root is None:
                if tracker is not None:
                    tracker.update_active_reconcile_metrics(
                        {
                            "movie_items_processed": processed_count,
                            "movie_items_total": len(unmatched_folders),
                        }
                    )
                continue
            if tracker is not None:
                tracker.update_active_reconcile_metrics(
                    {
                        "active_movie_root": str(managed_root),
                        "movie_items_processed": processed_count,
                        "movie_items_total": len(unmatched_folders),
                    }
                )
            added_movie = self.radarr_sync.auto_add_movie_for_folder(
                folder,
                managed_root,
                movies_cache=movies,
            )
            if not isinstance(added_movie, dict):
                continue
            movie_id = added_movie.get("id")
            if isinstance(movie_id, int):
                added_movie_ids.add(movie_id)
                self._store_managed_folder_mapping(movie_id, folder)
                LOG.info(
                    "Resolved movie_id=%s for batched projection: managed_root=%s folder=%s",
                    movie_id,
                    managed_root,
                    folder,
                )

        LOG.info(
            "Radarr auto-add processed: added=%s total_unmatched=%s",
            len(added_movie_ids),
            len(unmatched_folders),
        )
        return added_movie_ids

    def _auto_add_unmatched_series(
        self,
        affected_paths: set[Path] | None,
        matcher: AffectedPathMatcher | None = None,
        series_inventory: list[dict] | None = None,
    ) -> set[int]:
        if not (
            self.sonarr_enabled and self.sonarr_sync_enabled and self.sonarr_auto_add_unmatched
        ):
            return set()

        if series_inventory is not None:
            series = series_inventory
        else:
            try:
                series = self.sonarr.get_series()
            except Exception as exc:
                self._log_sonarr_sync_config_hint(exc)
                LOG.warning("Skipping Sonarr auto-add: inventory fetch failed: %s", exc)
                return set()

        resolved_matcher = matcher or AffectedPathMatcher(affected_paths)
        existing_paths = {
            managed_path.resolve(strict=False)
            for managed_path in (
                managed_equivalent_path(
                    str(item.get("path") or "").strip(),
                    self.series_root_mappings,
                )
                for item in series
            )
            if managed_path is not None
        }

        unmatched_folders = discover_unmatched_folders(
            mappings=self.series_root_mappings,
            existing_paths=existing_paths,
            affected_paths=affected_paths,
            matcher=resolved_matcher,
            discover_fn=discover_series_folders,
            video_exts=self.video_exts,
            scan_exclude_paths=self.scan_exclude_paths,
        )
        if not unmatched_folders:
            return set()

        tracker = getattr(self, "runtime_status_tracker", None)
        if tracker is not None:
            tracker.update_reconcile_phase("auto_add_series")
            tracker.update_active_reconcile_metrics(
                {
                    "series_items_processed": 0,
                    "series_items_total": len(unmatched_folders),
                }
            )

        added_series_ids: set[int] = set()
        for processed_count, folder in enumerate(unmatched_folders, start=1):
            managed_root = resolve_managed_root_for_folder(folder, self.series_root_mappings)
            if managed_root is None:
                if tracker is not None:
                    tracker.update_active_reconcile_metrics(
                        {
                            "series_items_processed": processed_count,
                            "series_items_total": len(unmatched_folders),
                        }
                    )
                continue
            if tracker is not None:
                tracker.update_active_reconcile_metrics(
                    {
                        "active_series_root": str(managed_root),
                        "series_items_processed": processed_count,
                        "series_items_total": len(unmatched_folders),
                    }
                )
            added_series = self.sonarr_sync.auto_add_series_for_folder(
                folder, managed_root, series_cache=series
            )
            if not isinstance(added_series, dict):
                continue
            series_id = added_series.get("id")
            if isinstance(series_id, int):
                added_series_ids.add(series_id)
                self._store_series_folder_mapping(series_id, folder)
                LOG.info(
                    "Queued series_id=%s for immediate series projection after Sonarr path "
                    "reconciliation: discovered_managed_root=%s discovered_folder=%s",
                    series_id,
                    managed_root,
                    folder,
                )

        LOG.info(
            "Sonarr auto-add processed: added=%s total_unmatched=%s",
            len(added_series_ids),
            len(unmatched_folders),
        )
        return added_series_ids

    def _store_managed_folder_mapping(self, movie_id: int, folder: Path) -> None:
        """Persist movie_id → managed folder mapping in provenance DB."""
        state_store = getattr(getattr(self, "movie_projection", None), "state_store", None)
        if state_store is not None:
            state_store.set_managed_folder(movie_id, folder)

    def _store_series_folder_mapping(self, series_id: int, folder: Path) -> None:
        """Persist series_id → managed folder mapping in provenance DB."""
        state_store = getattr(getattr(self, "sonarr_projection", None), "state_store", None)
        if state_store is not None:
            state_store.set_managed_series_folder(series_id, folder)
