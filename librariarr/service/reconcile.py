from __future__ import annotations

import time
from pathlib import Path

from ..projection import get_radarr_webhook_queue, get_sonarr_webhook_queue
from ..sync.discovery import discover_movie_folders, discover_series_folders
from .common import LOG


def _first_path(paths: set[Path] | None) -> str:
    if not paths:
        return "-"
    return sorted(str(path) for path in paths)[0]


class ServiceReconcileMixin:
    def reconcile(  # noqa: C901
        self,
        affected_paths: set[Path] | None = None,
        *,
        refresh_arr_root_availability: bool = True,
    ) -> bool:
        with self._lock:
            started = time.time()
            incremental_mode = bool(affected_paths)
            reconcile_mode = "incremental" if incremental_mode else "full"
            affected_paths_count: int | str = len(affected_paths) if incremental_mode else "all"
            trigger_source = self._current_reconcile_source()
            trigger_path = _first_path(affected_paths)
            LOG.info(
                "Reconcile started: source=%s mode=%s affected_paths=%s trigger_path=%s",
                trigger_source,
                reconcile_mode,
                affected_paths_count,
                trigger_path,
            )

            if refresh_arr_root_availability:
                self._update_arr_root_folder_availability(
                    force=self._arr_root_poll_interval is None,
                )

            ingested_movie_ids = self._ingest_movies_from_library_roots(affected_paths)
            auto_added_movie_ids = self._auto_add_unmatched_movies(affected_paths)
            auto_added_series_ids = self._auto_add_unmatched_series(affected_paths)

            scoped_movie_ids: set[int] | None = None
            if self.radarr_enabled:
                queued_movie_ids = get_radarr_webhook_queue().consume_movie_ids()
                if queued_movie_ids:
                    scoped_movie_ids = queued_movie_ids
            if ingested_movie_ids:
                if scoped_movie_ids is None:
                    scoped_movie_ids = set(ingested_movie_ids)
                else:
                    scoped_movie_ids.update(ingested_movie_ids)
            if auto_added_movie_ids:
                if scoped_movie_ids is None:
                    scoped_movie_ids = set(auto_added_movie_ids)
                else:
                    scoped_movie_ids.update(auto_added_movie_ids)

            scoped_series_ids: set[int] | None = None
            if self.sonarr_enabled and self.sonarr_sync_enabled:
                queued_series_ids = get_sonarr_webhook_queue().consume_series_ids()
                if queued_series_ids:
                    scoped_series_ids = queued_series_ids
            if auto_added_series_ids:
                if scoped_series_ids is None:
                    scoped_series_ids = set(auto_added_series_ids)
                else:
                    scoped_series_ids.update(auto_added_series_ids)

            if getattr(self, "runtime_status_tracker", None) is not None:
                self.runtime_status_tracker.update_reconcile_phase("scope_resolved")

            had_projection_error = False
            movie_projection_metrics = {
                "scoped_movie_count": 0,
                "planned_movies": 0,
                "skipped_movies": 0,
                "projected_files": 0,
                "unchanged_files": 0,
                "skipped_files": 0,
            }
            if self.radarr_enabled:
                if self.movie_projection is None:
                    raise RuntimeError(
                        "MovieProjectionOrchestrator is required when Radarr is enabled"
                    )
                self.movie_projection.radarr = self.radarr
                try:
                    movie_projection_metrics = self.movie_projection.reconcile(scoped_movie_ids)
                except Exception as exc:
                    had_projection_error = True
                    self._log_sync_config_hint(exc)
                    LOG.warning(
                        "Continuing reconcile without Radarr projection due to request failure: %s",
                        exc,
                    )

            if getattr(self, "runtime_status_tracker", None) is not None:
                self.runtime_status_tracker.update_reconcile_phase("indexed")

            series_projection_metrics = {
                "scoped_series_count": 0,
                "planned_series": 0,
                "skipped_series": 0,
                "projected_files": 0,
                "unchanged_files": 0,
                "skipped_files": 0,
            }
            if self.sonarr_enabled and self.sonarr_sync_enabled:
                if self.sonarr_projection is None:
                    raise RuntimeError(
                        "SonarrProjectionOrchestrator is required when Sonarr is enabled"
                    )
                self.sonarr_projection.sonarr = self.sonarr
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

        strategy = str(self.config.ingest.collision_strategy).strip().lower()
        moved_movie_ids: set[int] = set()

        for movie in movies:
            moved_movie_id = self._ingest_movie_if_needed(
                movie,
                affected_paths=affected_paths,
                strategy=strategy,
            )
            if moved_movie_id is not None:
                moved_movie_ids.add(moved_movie_id)

        return moved_movie_ids

    def _ingest_movie_if_needed(
        self,
        movie: dict,
        *,
        affected_paths: set[Path] | None,
        strategy: str,
    ) -> int | None:
        movie_id = movie.get("id")
        movie_path_raw = str(movie.get("path") or "").strip()
        if not isinstance(movie_id, int) or not movie_path_raw:
            return None

        source_folder = Path(movie_path_raw)
        destination_info = self._resolve_ingest_target(
            source_folder,
            affected_paths=affected_paths,
            strategy=strategy,
        )
        if destination_info is None:
            return None

        managed_root, resolved_destination = destination_info
        if not self._move_and_update_movie_path(movie, source_folder, resolved_destination):
            return None

        LOG.info(
            "Ingest moved movie folder from library root to managed root: movie_id=%s "
            "source=%s destination=%s",
            movie_id,
            source_folder,
            resolved_destination,
        )
        LOG.info(
            "Queued movie_id=%s for movie projection after ingest move: managed_root=%s folder=%s",
            movie_id,
            managed_root,
            resolved_destination,
        )
        return movie_id

    def _resolve_ingest_target(
        self,
        source_folder: Path,
        *,
        affected_paths: set[Path] | None,
        strategy: str,
    ) -> tuple[Path, Path] | None:
        mapping_and_relative = self._resolve_ingest_mapping_for_folder(source_folder)
        if mapping_and_relative is None:
            return None
        managed_root, _library_root, relative_folder = mapping_and_relative

        if not source_folder.exists() or not source_folder.is_dir():
            return None
        if not self._folder_matches_affected_paths(source_folder, affected_paths):
            return None

        destination_folder = managed_root / relative_folder
        if destination_folder.resolve(strict=False) == source_folder.resolve(strict=False):
            return None

        resolved_destination = self._resolve_ingest_destination(
            destination_folder,
            strategy=strategy,
        )
        if resolved_destination is None:
            return None
        return managed_root, resolved_destination

    def _move_and_update_movie_path(
        self,
        movie: dict,
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

        try:
            self.radarr.update_movie_path(movie, str(resolved_destination))
        except Exception as exc:
            try:
                resolved_destination.rename(source_folder)
            except OSError as rollback_exc:
                LOG.error(
                    "Ingest path update failed and rollback failed: source=%s destination=%s "
                    "update_error=%s rollback_error=%s",
                    source_folder,
                    resolved_destination,
                    exc,
                    rollback_exc,
                )
            else:
                LOG.warning(
                    "Ingest path update failed; restored original folder: source=%s "
                    "destination=%s error=%s",
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

    def _resolve_ingest_destination(self, destination: Path, *, strategy: str) -> Path | None:
        if not destination.exists():
            return destination

        if strategy == "skip":
            LOG.warning(
                "Ingest collision detected; skipping move because destination exists: %s",
                destination,
            )
            return None

        for index in range(2, 1000):
            candidate = destination.with_name(f"{destination.name} ({index})")
            if not candidate.exists():
                return candidate

        LOG.warning(
            "Ingest collision detected; no free qualified destination found for: %s",
            destination,
        )
        return None

    def _auto_add_unmatched_movies(self, affected_paths: set[Path] | None) -> set[int]:
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
            Path(path_raw).resolve(strict=False)
            for path_raw in (str(movie.get("path") or "").strip() for movie in movies)
            if path_raw
        }

        unmatched_folders = self._discover_unmatched_folders(
            mappings=self.movie_root_mappings,
            existing_paths=existing_paths,
            affected_paths=affected_paths,
            discover_fn=discover_movie_folders,
        )
        if not unmatched_folders:
            return set()

        selected_folders, total_unmatched, next_cursor = self._select_root_chunk(
            unmatched_folders=unmatched_folders,
            mappings=self.movie_root_mappings,
            cursor=self._movie_auto_add_root_cursor,
            batch_limit=max(1, int(self.config.runtime.auto_add_batch_size)),
        )
        if not selected_folders:
            return set()
        self._movie_auto_add_root_cursor = next_cursor

        added_movie_ids: set[int] = set()
        for managed_root, folder in selected_folders:
            if getattr(self, "runtime_status_tracker", None) is not None:
                self.runtime_status_tracker.update_active_reconcile_metrics(
                    {
                        "active_movie_root": str(managed_root),
                    }
                )

            added_movie = self.radarr_sync.auto_add_movie_for_folder(folder, managed_root)
            if not isinstance(added_movie, dict):
                continue
            movie_id = added_movie.get("id")
            if isinstance(movie_id, int):
                added_movie_ids.add(movie_id)
                LOG.info(
                    "Queued movie_id=%s for movie projection after Radarr path reconciliation: "
                    "managed_root=%s folder=%s",
                    movie_id,
                    managed_root,
                    folder,
                )

        LOG.info(
            "Radarr auto-add chunk processed: selected=%s total_unmatched=%s next_root_cursor=%s",
            len(selected_folders),
            total_unmatched,
            self._movie_auto_add_root_cursor,
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
            Path(path_raw).resolve(strict=False)
            for path_raw in (str(item.get("path") or "").strip() for item in series)
            if path_raw
        }

        unmatched_folders = self._discover_unmatched_folders(
            mappings=self.series_root_mappings,
            existing_paths=existing_paths,
            affected_paths=affected_paths,
            discover_fn=discover_series_folders,
        )
        if not unmatched_folders:
            return set()

        selected_folders, total_unmatched, next_cursor = self._select_root_chunk(
            unmatched_folders=unmatched_folders,
            mappings=self.series_root_mappings,
            cursor=self._series_auto_add_root_cursor,
            batch_limit=max(1, int(self.config.runtime.auto_add_batch_size)),
        )
        if not selected_folders:
            return set()
        self._series_auto_add_root_cursor = next_cursor

        added_series_ids: set[int] = set()
        for managed_root, folder in selected_folders:
            if getattr(self, "runtime_status_tracker", None) is not None:
                self.runtime_status_tracker.update_active_reconcile_metrics(
                    {
                        "active_series_root": str(managed_root),
                    }
                )

            added_series = self.sonarr_sync.auto_add_series_for_folder(folder, managed_root)
            if not isinstance(added_series, dict):
                continue
            series_id = added_series.get("id")
            if isinstance(series_id, int):
                added_series_ids.add(series_id)
                LOG.info(
                    "Queued series_id=%s for series projection after Sonarr path reconciliation: "
                    "managed_root=%s folder=%s",
                    series_id,
                    managed_root,
                    folder,
                )

        LOG.info(
            "Sonarr auto-add chunk processed: selected=%s total_unmatched=%s next_root_cursor=%s",
            len(selected_folders),
            total_unmatched,
            self._series_auto_add_root_cursor,
        )

        return added_series_ids

    def _discover_unmatched_folders(
        self,
        *,
        mappings: list[tuple[Path, Path]],
        existing_paths: set[Path],
        affected_paths: set[Path] | None,
        discover_fn,
    ) -> list[Path]:
        discovered_folders: set[Path] = set()
        for managed_root, _library_root in mappings:
            discovered_folders.update(
                discover_fn(managed_root, self.video_exts, self.scan_exclude_paths)
            )

        return sorted(
            folder
            for folder in discovered_folders
            if folder.resolve(strict=False) not in existing_paths
            and self._folder_matches_affected_paths(folder, affected_paths)
        )

    def _select_root_chunk(
        self,
        *,
        unmatched_folders: list[Path],
        mappings: list[tuple[Path, Path]],
        cursor: int,
        batch_limit: int,
    ) -> tuple[list[tuple[Path, Path]], int, int]:
        unmatched_by_root: dict[Path, list[Path]] = {managed: [] for managed, _ in mappings}
        for folder in unmatched_folders:
            managed_root = self._resolve_managed_root_for_folder(folder, mappings)
            if managed_root is None:
                continue
            unmatched_by_root.setdefault(managed_root, []).append(folder)

        configured_roots = [managed for managed, _ in mappings]
        if not configured_roots:
            return [], len(unmatched_folders), cursor

        start_index = cursor % len(configured_roots)
        ordered_roots = configured_roots[start_index:] + configured_roots[:start_index]
        selected_folders: list[tuple[Path, Path]] = []
        for managed_root in ordered_roots:
            for folder in unmatched_by_root.get(managed_root, []):
                selected_folders.append((managed_root, folder))
                if len(selected_folders) >= batch_limit:
                    break
            if len(selected_folders) >= batch_limit:
                break

        if not selected_folders:
            return [], len(unmatched_folders), cursor

        last_managed_root = selected_folders[-1][0]
        last_root_index = configured_roots.index(last_managed_root)
        next_cursor = (last_root_index + 1) % len(configured_roots)
        return selected_folders, len(unmatched_folders), next_cursor

    def _folder_matches_affected_paths(
        self,
        folder: Path,
        affected_paths: set[Path] | None,
    ) -> bool:
        if not affected_paths:
            return True

        folder_resolved = folder.resolve(strict=False)
        for candidate in affected_paths:
            candidate_resolved = candidate.resolve(strict=False)
            if folder_resolved == candidate_resolved:
                return True
            if candidate_resolved in folder_resolved.parents:
                return True
            if folder_resolved in candidate_resolved.parents:
                return True
        return False

    def _resolve_managed_root_for_folder(
        self,
        folder: Path,
        mappings: list[tuple[Path, Path]],
    ) -> Path | None:
        sorted_mappings = sorted(mappings, key=lambda item: len(item[0].parts), reverse=True)
        for managed_root, _library_root in sorted_mappings:
            try:
                folder.relative_to(managed_root)
            except ValueError:
                continue
            return managed_root
        return None

    def _resolve_library_root_for_folder(
        self,
        folder: Path,
        mappings: list[tuple[Path, Path]],
    ) -> Path | None:
        sorted_mappings = sorted(mappings, key=lambda item: len(item[0].parts), reverse=True)
        for managed_root, library_root in sorted_mappings:
            try:
                folder.relative_to(managed_root)
            except ValueError:
                continue
            return library_root
        return None

    def _current_reconcile_source(self) -> str:
        runtime_status_tracker = getattr(self, "runtime_status_tracker", None)
        if runtime_status_tracker is None:
            return "direct"

        try:
            snapshot = runtime_status_tracker.snapshot()
        except Exception:
            return "direct"

        if not isinstance(snapshot, dict):
            return "direct"

        current_task = snapshot.get("current_task")
        if not isinstance(current_task, dict):
            return "direct"

        trigger_source = current_task.get("trigger_source")
        if isinstance(trigger_source, str) and trigger_source.strip():
            return trigger_source

        return "direct"
