from __future__ import annotations

import time
from pathlib import Path

from ..projection import get_radarr_webhook_queue, get_sonarr_webhook_queue
from ..sync.discovery import discover_movie_folders, discover_series_folders
from .common import LOG
from .reconcile_helpers import (
    current_reconcile_source,
    discover_unmatched_folders,
    folder_matches_affected_paths,
    ingest_files_from_library_folder,
    managed_equivalent_path,
    resolve_managed_root_for_folder,
)
from .reconcile_observability import first_path, log_projection_dispatch, log_scope_resolved


class ServiceReconcileMixin:
    def reconcile(  # noqa: C901
        self,
        affected_paths: set[Path] | None = None,
        *,
        refresh_arr_root_availability: bool = True,
        force_full_scope: bool = False,
    ) -> bool:
        with self._lock:
            started = time.time()
            incremental_mode = bool(affected_paths)
            reconcile_mode = "incremental" if incremental_mode else "full"
            affected_paths_count: int | str = len(affected_paths) if incremental_mode else "all"
            trigger_source = current_reconcile_source(getattr(self, "runtime_status_tracker", None))
            trigger_path = first_path(affected_paths)
            LOG.info(
                "Reconcile started: source=%s mode=%s affected_paths=%s trigger_path=%s",
                trigger_source,
                reconcile_mode,
                affected_paths_count,
                trigger_path,
            )

            if force_full_scope:
                LOG.info(
                    "======== Full Reconcile started (source=%s) ========",
                    trigger_source,
                )
                refresh_arr_root_availability = True

            if refresh_arr_root_availability:
                self._update_arr_root_folder_availability(
                    force=self._arr_root_poll_interval is None,
                )

            ingested_movie_ids = self._ingest_movies_from_library_roots(affected_paths)

            auto_added_movie_ids = self._auto_add_unmatched_movies(affected_paths)
            auto_added_series_ids = self._auto_add_unmatched_series(affected_paths)

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

            movie_scope_kind = "scoped" if scoped_movie_ids is not None else "full"
            if movie_scope_kind == "scoped":
                movie_full_scope_reason = "-"
            elif force_full_scope:
                movie_full_scope_reason = "force_full_scope"
            elif not self.radarr_enabled:
                movie_full_scope_reason = "arr_disabled_or_sync_disabled"
            elif not incremental_mode:
                movie_full_scope_reason = "full_mode_requested"
            else:
                movie_full_scope_reason = "incremental_no_ids_from_sources"

            scoped_series_ids: set[int] | None = None
            queued_series_ids: set[int] = set()
            if self.sonarr_enabled and self.sonarr_sync_enabled:
                queued_series_ids = get_sonarr_webhook_queue().consume_series_ids()
                if not force_full_scope and queued_series_ids:
                    scoped_series_ids = queued_series_ids
            if not force_full_scope:
                if auto_added_series_ids and (incremental_mode or scoped_series_ids is not None):
                    if scoped_series_ids is None:
                        scoped_series_ids = set(auto_added_series_ids)
                    else:
                        scoped_series_ids.update(auto_added_series_ids)

            series_scope_kind = "scoped" if scoped_series_ids is not None else "full"
            if series_scope_kind == "scoped":
                series_full_scope_reason = "-"
            elif force_full_scope:
                series_full_scope_reason = "force_full_scope"
            elif not (self.sonarr_enabled and self.sonarr_sync_enabled):
                series_full_scope_reason = "arr_disabled_or_sync_disabled"
            elif not incremental_mode:
                series_full_scope_reason = "full_mode_requested"
            else:
                series_full_scope_reason = "incremental_no_ids_from_sources"

            log_scope_resolved(
                trigger_source=trigger_source,
                reconcile_mode=reconcile_mode,
                affected_paths_count=affected_paths_count,
                trigger_path=trigger_path,
                movie_scope_kind=movie_scope_kind,
                movie_full_scope_reason=movie_full_scope_reason,
                scoped_movie_ids=scoped_movie_ids,
                queued_movie_ids=queued_movie_ids,
                ingested_movie_ids=ingested_movie_ids,
                auto_added_movie_ids=auto_added_movie_ids,
                series_scope_kind=series_scope_kind,
                series_full_scope_reason=series_full_scope_reason,
                scoped_series_ids=scoped_series_ids,
                queued_series_ids=queued_series_ids,
                auto_added_series_ids=auto_added_series_ids,
            )

            if getattr(self, "runtime_status_tracker", None) is not None:
                self.runtime_status_tracker.update_reconcile_phase("scope_resolved")
                self.runtime_status_tracker.update_active_reconcile_metrics(
                    {
                        "movie_items_targeted": (
                            len(scoped_movie_ids) if scoped_movie_ids is not None else None
                        ),
                        "series_items_targeted": (
                            len(scoped_series_ids) if scoped_series_ids is not None else None
                        ),
                        "movie_items_projected": 0,
                        "series_items_projected": 0,
                        "created_links": 0,
                    }
                )

            had_projection_error = False
            movie_projection_metrics = dict.fromkeys(
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
            if self.radarr_enabled:
                if self.movie_projection is None:
                    raise RuntimeError(
                        "MovieProjectionOrchestrator is required when Radarr is enabled"
                    )
                self.movie_projection.radarr = self.radarr
                log_projection_dispatch(
                    arr="radarr",
                    trigger_source=trigger_source,
                    reconcile_mode=reconcile_mode,
                    scope_kind=movie_scope_kind,
                    full_scope_reason=movie_full_scope_reason,
                    scoped_ids=scoped_movie_ids,
                )
                try:
                    movie_projection_metrics = self.movie_projection.reconcile(scoped_movie_ids)
                    if getattr(self, "runtime_status_tracker", None) is not None:
                        planned_movies = int(movie_projection_metrics.get("planned_movies") or 0)
                        skipped_movies = int(movie_projection_metrics.get("skipped_movies") or 0)
                        self.runtime_status_tracker.update_active_reconcile_metrics(
                            {
                                "movie_folders_seen": planned_movies,
                                "movie_items_projected": max(0, planned_movies - skipped_movies),
                                "created_links": int(
                                    movie_projection_metrics.get("projected_files") or 0
                                ),
                            }
                        )
                except Exception as exc:
                    had_projection_error = True
                    self._log_sync_config_hint(exc)
                    LOG.warning(
                        "Continuing reconcile without Radarr projection due to request failure: %s",
                        exc,
                    )

            if getattr(self, "runtime_status_tracker", None) is not None:
                self.runtime_status_tracker.update_reconcile_phase("indexed")

            series_projection_metrics = dict.fromkeys(
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
            if self.sonarr_enabled and self.sonarr_sync_enabled:
                if self.sonarr_projection is None:
                    raise RuntimeError(
                        "SonarrProjectionOrchestrator is required when Sonarr is enabled"
                    )
                self.sonarr_projection.sonarr = self.sonarr
                log_projection_dispatch(
                    arr="sonarr",
                    trigger_source=trigger_source,
                    reconcile_mode=reconcile_mode,
                    scope_kind=series_scope_kind,
                    full_scope_reason=series_full_scope_reason,
                    scoped_ids=scoped_series_ids,
                )
                try:
                    series_projection_metrics = self.sonarr_projection.reconcile(scoped_series_ids)
                except Exception as exc:
                    had_projection_error = True
                    self._log_sonarr_sync_config_hint(exc)
                    LOG.warning(
                        "Continuing reconcile without Sonarr projection due to request failure: %s",
                        exc,
                    )

            if getattr(self, "runtime_status_tracker", None) is not None:
                self.runtime_status_tracker.update_reconcile_phase("applied")
                self.runtime_status_tracker.update_reconcile_phase("cleaned")

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

            duration_seconds = round(time.time() - started, 2)
            outcome = "updated"
            if (
                total_projected_files == 0
                and matched_movies == 0
                and unmatched_movies == 0
                and matched_series == 0
                and unmatched_series == 0
            ):
                outcome = "no_changes"

            if getattr(self, "runtime_status_tracker", None) is not None:
                self.runtime_status_tracker.update_active_reconcile_metrics(
                    {
                        "active_movie_root": None,
                        "active_series_root": None,
                        "movie_folders_seen": int(
                            movie_projection_metrics.get("planned_movies") or 0
                        ),
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
                        "affected_paths_count": (
                            int(affected_paths_count)
                            if isinstance(affected_paths_count, int)
                            else None
                        ),
                    }
                )
                movie_per_root = movie_projection_metrics.get("per_root") or []
                series_per_root = series_projection_metrics.get("per_root") or []
                all_per_root = [{**r, "arr_type": "radarr"} for r in movie_per_root] + [
                    {**r, "arr_type": "sonarr"} for r in series_per_root
                ]
                self.runtime_status_tracker.update_library_root_stats(all_per_root)

            LOG.info(
                "Reconcile finished: source=%s mode=%s affected_paths=%s trigger_path=%s "
                "outcome=%s projected_files=%s matched_movies=%s matched_series=%s "
                "duration_seconds=%s",
                trigger_source,
                reconcile_mode,
                affected_paths_count,
                trigger_path,
                outcome,
                total_projected_files,
                matched_movies,
                matched_series,
                duration_seconds,
            )
            if getattr(self, "runtime_status_tracker", None) is not None:
                self.runtime_status_tracker.update_reconcile_phase("completed")
            if force_full_scope:
                if getattr(self, "runtime_status_tracker", None) is not None:
                    self.runtime_status_tracker.update_active_reconcile_metrics(
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
            return had_projection_error

    def _ingest_movies_from_library_roots(self, affected_paths: set[Path] | None) -> set[int]:
        if not (self.radarr_enabled and self.sync_enabled and self.config.ingest.enabled):
            return set()

        try:
            movies = self.radarr.get_movies()
        except Exception as exc:
            self._log_sync_config_hint(exc)
            LOG.warning("Skipping ingest scan because Radarr movie inventory fetch failed: %s", exc)
            return set()

        moved_movie_ids: set[int] = set()

        for movie in movies:
            moved_movie_id = self._ingest_movie_if_needed(
                movie,
                affected_paths=affected_paths,
            )
            if moved_movie_id is not None:
                moved_movie_ids.add(moved_movie_id)

        return moved_movie_ids

    def _ingest_movie_if_needed(
        self,
        movie: dict,
        *,
        affected_paths: set[Path] | None,
    ) -> int | None:
        movie_id = movie.get("id")
        movie_path_raw = str(movie.get("path") or "").strip()
        if not isinstance(movie_id, int) or not movie_path_raw:
            return None

        source_folder = Path(movie_path_raw)
        destination_info = self._resolve_ingest_target(
            source_folder,
            affected_paths=affected_paths,
        )
        if destination_info is not None:
            managed_root, resolved_destination = destination_info
            if not self._move_movie_from_shadow_to_managed(source_folder, resolved_destination):
                return None

            LOG.info(
                "Ingest moved movie folder from library root to managed root: movie_id=%s "
                "source=%s destination=%s",
                movie_id,
                source_folder,
                resolved_destination,
            )
            return movie_id

        return self._ingest_files_for_existing_movie(
            movie_id,
            source_folder,
            affected_paths=affected_paths,
        )

    def _ingest_files_for_existing_movie(
        self,
        movie_id: int,
        source_folder: Path,
        *,
        affected_paths: set[Path] | None,
    ) -> int | None:
        mapping_info = self._resolve_ingest_mapping_for_folder(source_folder)
        if mapping_info is None:
            return None
        managed_root, _library_root, relative_folder = mapping_info
        managed_folder = managed_root / relative_folder
        if not managed_folder.exists() or not managed_folder.is_dir():
            return None
        if not source_folder.exists() or not source_folder.is_dir():
            return None
        if not folder_matches_affected_paths(source_folder, affected_paths):
            return None
        proj = self.config.radarr.projection
        result = ingest_files_from_library_folder(
            library_folder=source_folder,
            managed_folder=managed_folder,
            managed_video_extensions=set(proj.managed_video_extensions),
            extras_allowlist=proj.managed_extras_allowlist,
        )
        if result.ingested_count > 0:
            LOG.info(
                "File-level ingest for movie_id=%s: ingested=%s failed=%s",
                movie_id,
                result.ingested_count,
                result.failed_count,
            )
            return movie_id
        return None

    def _resolve_ingest_target(
        self,
        source_folder: Path,
        *,
        affected_paths: set[Path] | None,
    ) -> tuple[Path, Path] | None:
        mapping_and_relative = self._resolve_ingest_mapping_for_folder(source_folder)
        if mapping_and_relative is None:
            return None
        managed_root, _library_root, relative_folder = mapping_and_relative

        if not source_folder.exists() or not source_folder.is_dir():
            return None
        if not folder_matches_affected_paths(source_folder, affected_paths):
            return None

        destination_folder = managed_root / relative_folder
        if destination_folder.resolve(strict=False) == source_folder.resolve(strict=False):
            return None

        if destination_folder.exists():
            return None

        return managed_root, destination_folder

    def _move_movie_from_shadow_to_managed(
        self,
        source_folder: Path,
        resolved_destination: Path,
    ) -> bool:
        resolved_destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            source_folder.rename(resolved_destination)
        except OSError as exc:
            LOG.warning(
                "Ingest move failed: source=%s destination=%s error=%s",
                source_folder,
                resolved_destination,
                exc,
            )
            return False

        return True

    def _resolve_ingest_mapping_for_folder(
        self,
        folder: Path,
    ) -> tuple[Path, Path, Path] | None:
        sorted_mappings = sorted(
            self.movie_root_mappings,
            key=lambda item: len(item[1].parts),
            reverse=True,
        )
        for managed_root, library_root in sorted_mappings:
            try:
                relative_folder = folder.relative_to(library_root)
            except ValueError:
                continue
            return managed_root, library_root, relative_folder
        return None

    def _auto_add_unmatched_movies(
        self,
        affected_paths: set[Path] | None,
    ) -> set[int]:
        if not (self.radarr_enabled and self.sync_enabled and self.auto_add_unmatched):
            return set()

        try:
            movies = self.radarr.get_movies()
        except Exception as exc:
            self._log_sync_config_hint(exc)
            LOG.warning(
                "Skipping Radarr auto-add scan because movie inventory fetch failed: %s",
                exc,
            )
            return set()

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
            discover_fn=discover_movie_folders,
            video_exts=self.video_exts,
            scan_exclude_paths=self.scan_exclude_paths,
        )
        if not unmatched_folders:
            return set()

        added_movie_ids: set[int] = set()
        for folder in unmatched_folders:
            managed_root = resolve_managed_root_for_folder(folder, self.movie_root_mappings)
            if managed_root is None:
                continue
            if getattr(self, "runtime_status_tracker", None) is not None:
                self.runtime_status_tracker.update_active_reconcile_metrics(
                    {"active_movie_root": str(managed_root)}
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

    def _auto_add_unmatched_series(self, affected_paths: set[Path] | None) -> set[int]:
        if not (
            self.sonarr_enabled and self.sonarr_sync_enabled and self.sonarr_auto_add_unmatched
        ):
            return set()

        try:
            series = self.sonarr.get_series()
        except Exception as exc:
            self._log_sonarr_sync_config_hint(exc)
            LOG.warning(
                "Skipping Sonarr auto-add scan because series inventory fetch failed: %s",
                exc,
            )
            return set()

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
            discover_fn=discover_series_folders,
            video_exts=self.video_exts,
            scan_exclude_paths=self.scan_exclude_paths,
        )
        if not unmatched_folders:
            return set()

        added_series_ids: set[int] = set()
        for folder in unmatched_folders:
            managed_root = resolve_managed_root_for_folder(folder, self.series_root_mappings)
            if managed_root is None:
                continue
            if getattr(self, "runtime_status_tracker", None) is not None:
                self.runtime_status_tracker.update_active_reconcile_metrics(
                    {"active_series_root": str(managed_root)}
                )
            added_series = self.sonarr_sync.auto_add_series_for_folder(folder, managed_root)
            if not isinstance(added_series, dict):
                continue
            series_id = added_series.get("id")
            if isinstance(series_id, int):
                added_series_ids.add(series_id)
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

    def reconcile_full(self) -> bool:
        return self.reconcile(affected_paths=None, force_full_scope=True)
