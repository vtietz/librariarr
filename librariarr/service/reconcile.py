from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from ..sync import (
    MovieRef,
    ShadowCleanupManager,
    collect_current_links,
    discover_movie_folders,
    discover_series_folders,
)
from .common import LOG


class ServiceReconcileMixin:
    def reconcile(self, affected_paths: set[Path] | None = None) -> bool:
        with self._lock:
            started = time.time()
            LOG.info("Reconciling shadow links and Arr state...")
            for shadow_root in self.shadow_roots:
                shadow_root.mkdir(parents=True, exist_ok=True)

            self._update_arr_root_folder_availability(force=self._arr_root_poll_interval is None)

            ingested_count = self.ingestor.run() if self.config.ingest.enabled else 0
            ingest_pending = False
            if self.config.ingest.enabled:
                ingest_pending = self.ingestor.last_pending_quiescent_count > 0

            movie_folders: dict[Path, Path] = {}
            all_movie_folders: dict[Path, Path] = {}
            movie_affected_targets: set[Path] = set()
            movie_incremental_mode = False
            if self.radarr_enabled:
                (
                    movie_folders,
                    all_movie_folders,
                    movie_affected_targets,
                    movie_incremental_mode,
                ) = self._resolve_reconcile_scope(
                    affected_paths,
                    known_folders=self._known_movie_folders,
                    discover=discover_movie_folders,
                )
                self._known_movie_folders = dict(all_movie_folders)

            series_folders: dict[Path, Path] = {}
            all_series_folders: dict[Path, Path] = {}
            series_affected_targets: set[Path] = set()
            series_incremental_mode = False
            if self.sonarr_enabled:
                (
                    series_folders,
                    all_series_folders,
                    series_affected_targets,
                    series_incremental_mode,
                ) = self._resolve_reconcile_scope(
                    affected_paths,
                    known_folders=self._known_series_folders,
                    discover=discover_series_folders,
                )
                self._known_series_folders = dict(all_series_folders)

            target_to_links = collect_current_links(self.shadow_roots)
            movies_by_ref = self._build_movie_index() if self.sync_enabled else {}
            movies_by_path = (
                self._build_movie_path_index(movies_by_ref) if self.sync_enabled else {}
            )
            movies_by_external_id = (
                self._build_movie_external_id_index(movies_by_ref) if self.sync_enabled else {}
            )
            series_by_ref = self._build_series_index() if self.sonarr_sync_enabled else {}
            series_by_path = (
                self._build_series_path_index(series_by_ref) if self.sonarr_sync_enabled else {}
            )
            series_by_external_id = (
                self._build_series_external_id_index(series_by_ref)
                if self.sonarr_sync_enabled
                else {}
            )
            expected_links: set[Path] = set()
            movie_created_links = 0
            matched_movies = 0
            unmatched_movies = 0
            matched_movie_ids: set[int] = set()
            if self.radarr_enabled:
                (
                    movie_created_links,
                    matched_movies,
                    unmatched_movies,
                    matched_movie_ids,
                ) = self._reconcile_movie_links(
                    movie_folders=movie_folders,
                    target_to_links=target_to_links,
                    expected_links=expected_links,
                    movies_by_ref=movies_by_ref,
                    movies_by_path=movies_by_path,
                    movies_by_external_id=movies_by_external_id,
                )
            (
                series_created_links,
                matched_series,
                unmatched_series,
                matched_series_ids,
            ) = self._reconcile_series_links(
                series_folders=series_folders,
                target_to_links=target_to_links,
                expected_links=expected_links,
                series_by_ref=series_by_ref,
                series_by_path=series_by_path,
                series_by_external_id=series_by_external_id,
            )
            created_links = movie_created_links + series_created_links

            orphaned_links_removed = self._cleanup_orphans(
                all_movie_folders=all_movie_folders,
                all_series_folders=all_series_folders,
                expected_links=expected_links,
                movies_by_ref=movies_by_ref,
                series_by_ref=series_by_ref,
                movie_incremental_mode=movie_incremental_mode,
                series_incremental_mode=series_incremental_mode,
                movie_affected_targets=movie_affected_targets,
                series_affected_targets=series_affected_targets,
                matched_movie_ids=matched_movie_ids,
                matched_series_ids=matched_series_ids,
            )

            duration_seconds = round(time.time() - started, 2)
            if getattr(self, "runtime_status_tracker", None) is not None:
                self.runtime_status_tracker.update_active_reconcile_metrics(
                    {
                        "movie_folders_seen": len(movie_folders),
                        "series_folders_seen": len(series_folders),
                        "existing_links": sum(len(links) for links in target_to_links.values()),
                        "created_links": created_links,
                        "matched_movies": matched_movies,
                        "unmatched_movies": unmatched_movies,
                        "matched_series": matched_series,
                        "unmatched_series": unmatched_series,
                        "removed_orphans": orphaned_links_removed,
                        "ingested_dirs": ingested_count,
                        "pending_ingest_dirs": self.ingestor.last_pending_quiescent_count,
                        "ingest_pending": ingest_pending,
                        "duration_seconds": duration_seconds,
                        "affected_paths_count": (
                            len(affected_paths) if affected_paths is not None else None
                        ),
                    }
                )
            LOG.info(
                "Reconcile complete: movie_folders=%s existing_links=%s "
                "created_links=%s matched_movies=%s unmatched_movies=%s "
                "series_folders=%s matched_series=%s unmatched_series=%s "
                "removed_orphans=%s ingested_dirs=%s ingest_pending=%s "
                "sync_enabled=%s sonarr_sync_enabled=%s duration_seconds=%s",
                len(movie_folders),
                sum(len(links) for links in target_to_links.values()),
                created_links,
                matched_movies,
                unmatched_movies,
                len(series_folders),
                matched_series,
                unmatched_series,
                orphaned_links_removed,
                ingested_count,
                ingest_pending,
                self.sync_enabled,
                self.sonarr_sync_enabled,
                duration_seconds,
            )
            return ingest_pending

    def _reconcile_movie_links(
        self,
        movie_folders: dict[Path, Path],
        target_to_links: dict[Path, set[Path]],
        expected_links: set[Path],
        movies_by_ref: dict[MovieRef, dict],
        movies_by_path: dict[str, dict],
        movies_by_external_id: dict[str, dict],
    ) -> tuple[int, int, int, set[int]]:
        created_links = 0
        matched_movies = 0
        unmatched_movies = 0
        auto_added_movie_ids: set[int] = set()
        matched_movie_ids: set[int] = set()
        logged_unavailable_roots: set[str] = set()

        for folder, shadow_root in sorted(movie_folders.items()):
            existing_links = target_to_links.get(folder, set())
            root_available, preserved_existing_link = (
                self._resolve_root_availability_and_preserve_existing_link(
                    sync_enabled=self.sync_enabled,
                    shadow_root=shadow_root,
                    existing_links=existing_links,
                    expected_links=expected_links,
                    target_to_links=target_to_links,
                    folder=folder,
                    logged_unavailable_roots=logged_unavailable_roots,
                    is_root_available=self._is_radarr_root_available,
                    skip_log_message=(
                        "Skipping Radarr matching/sync for shadow root not configured in Radarr: %s"
                    ),
                )
            )
            if preserved_existing_link:
                continue
            movie = (
                self._match_movie_for_folder(
                    folder,
                    movies_by_ref,
                    movies_by_path,
                    movies_by_external_id,
                    existing_links,
                )
                if self.sync_enabled and root_available
                else None
            )
            attempted_auto_add = False
            if self.sync_enabled and root_available and movie is None and self.auto_add_unmatched:
                attempted_auto_add = True
                movie = self.radarr_sync.auto_add_movie_for_folder(folder, shadow_root)
                if movie is not None:
                    self._add_movie_id_if_present(auto_added_movie_ids, movie)
                    self._index_movie(index=movies_by_ref, movie=movie)
                    self._index_movie_path(index=movies_by_path, movie=movie)
                    self._index_movie_external_ids(index=movies_by_external_id, movie=movie)

            link_path, was_created = self.link_manager.ensure_link(
                folder,
                shadow_root,
                existing_links,
                movie,
            )
            expected_links.add(link_path)
            target_to_links.setdefault(folder, set()).add(link_path)
            if was_created:
                created_links += 1

            if not self.sync_enabled or not root_available:
                continue

            if movie is not None:
                movie_id = self._add_movie_id_if_present(matched_movie_ids, movie)
                auto_added = movie_id is not None and movie_id in auto_added_movie_ids
                self._sync_radarr_for_folder(
                    folder,
                    link_path,
                    movie,
                    force_refresh=auto_added,
                    apply_quality_mapping=auto_added,
                )
                matched_movies += 1
                continue

            if self.auto_add_unmatched:
                if attempted_auto_add:
                    LOG.warning(
                        "No Radarr match for folder after auto-add attempt: %s",
                        folder,
                    )
            else:
                LOG.warning(
                    "No Radarr match for folder: %s "
                    "(enable radarr.auto_add_unmatched=true to auto-create, "
                    "or add/import in Radarr first)",
                    folder,
                )
            unmatched_movies += 1

        return created_links, matched_movies, unmatched_movies, matched_movie_ids

    def _reconcile_series_links(
        self,
        series_folders: dict[Path, Path],
        target_to_links: dict[Path, set[Path]],
        expected_links: set[Path],
        series_by_ref: dict[MovieRef, dict],
        series_by_path: dict[str, dict],
        series_by_external_id: dict[str, dict],
    ) -> tuple[int, int, int, set[int]]:
        created_links = 0
        matched_series = 0
        unmatched_series = 0
        auto_added_series_ids: set[int] = set()
        matched_series_ids: set[int] = set()
        logged_unavailable_roots: set[str] = set()

        for folder, shadow_root in sorted(series_folders.items()):
            existing_links = target_to_links.get(folder, set())
            root_available, preserved_existing_link = (
                self._resolve_root_availability_and_preserve_existing_link(
                    sync_enabled=self.sonarr_sync_enabled,
                    shadow_root=shadow_root,
                    existing_links=existing_links,
                    expected_links=expected_links,
                    target_to_links=target_to_links,
                    folder=folder,
                    logged_unavailable_roots=logged_unavailable_roots,
                    is_root_available=self._is_sonarr_root_available,
                    skip_log_message=(
                        "Skipping Sonarr matching/sync for shadow root not configured in Sonarr: %s"
                    ),
                )
            )
            if preserved_existing_link:
                continue
            series = (
                self._match_series_for_folder(
                    folder,
                    series_by_ref,
                    series_by_path,
                    series_by_external_id,
                    existing_links,
                )
                if self.sonarr_sync_enabled and root_available
                else None
            )
            attempted_auto_add = False
            if (
                self.sonarr_sync_enabled
                and root_available
                and series is None
                and self.sonarr_auto_add_unmatched
            ):
                attempted_auto_add = True
                series = self.sonarr_sync.auto_add_series_for_folder(folder, shadow_root)
                if series is not None:
                    self._add_movie_id_if_present(auto_added_series_ids, series)
                    self._index_series(index=series_by_ref, series=series)
                    self._index_series_path(index=series_by_path, series=series)
                    self._index_series_external_ids(index=series_by_external_id, series=series)

            link_path, was_created = self.link_manager.ensure_link(
                folder,
                shadow_root,
                existing_links,
                series,
            )
            expected_links.add(link_path)
            target_to_links.setdefault(folder, set()).add(link_path)
            if was_created:
                created_links += 1

            if not self.sonarr_sync_enabled or not root_available:
                continue

            if series is not None:
                series_id = self._add_movie_id_if_present(matched_series_ids, series)
                self._sync_sonarr_for_folder(
                    folder,
                    link_path,
                    series,
                    force_refresh=series_id is not None and series_id in auto_added_series_ids,
                )
                matched_series += 1
                continue

            if self.sonarr_auto_add_unmatched:
                if attempted_auto_add:
                    LOG.warning(
                        "No Sonarr match for folder after auto-add attempt: %s",
                        folder,
                    )
            else:
                LOG.warning(
                    "No Sonarr match for folder: %s "
                    "(enable sonarr.auto_add_unmatched=true to auto-create, "
                    "or add/import in Sonarr first)",
                    folder,
                )
            unmatched_series += 1

        return created_links, matched_series, unmatched_series, matched_series_ids

    def _existing_link_for_shadow_root(
        self,
        existing_links: set[Path],
        shadow_root: Path,
    ) -> Path | None:
        candidates = sorted(
            [link for link in existing_links if link.parent == shadow_root],
            key=str,
        )
        if not candidates:
            return None
        return candidates[0]

    def _resolve_root_availability_and_preserve_existing_link(
        self,
        *,
        sync_enabled: bool,
        shadow_root: Path,
        existing_links: set[Path],
        expected_links: set[Path],
        target_to_links: dict[Path, set[Path]],
        folder: Path,
        logged_unavailable_roots: set[str],
        is_root_available: Callable[[Path], bool],
        skip_log_message: str,
    ) -> tuple[bool, bool]:
        if not sync_enabled:
            return True, False

        if is_root_available(shadow_root):
            return True, False

        normalized_shadow_root = self._normalize_arr_root_path(str(shadow_root))
        if normalized_shadow_root not in logged_unavailable_roots:
            logged_unavailable_roots.add(normalized_shadow_root)
            LOG.debug(skip_log_message, shadow_root)

        existing_link = self._existing_link_for_shadow_root(existing_links, shadow_root)
        if existing_link is None:
            return False, False

        expected_links.add(existing_link)
        target_to_links.setdefault(folder, set()).add(existing_link)
        return False, True

    def _cleanup_orphans(
        self,
        all_movie_folders: dict[Path, Path],
        all_series_folders: dict[Path, Path],
        expected_links: set[Path],
        movies_by_ref: dict[MovieRef, dict],
        series_by_ref: dict[MovieRef, dict],
        movie_incremental_mode: bool,
        series_incremental_mode: bool,
        movie_affected_targets: set[Path],
        series_affected_targets: set[Path],
        matched_movie_ids: set[int],
        matched_series_ids: set[int],
    ) -> int:
        if not self.config.cleanup.remove_orphaned_links:
            return 0

        existing_folders = set(all_movie_folders.keys()) | set(all_series_folders.keys())
        removed_orphans = 0
        if self.radarr_enabled:
            removed_orphans = self._cleanup_with_manager(
                manager=self.cleanup_manager,
                existing_folders=existing_folders,
                items_by_ref=movies_by_ref,
                expected_links=expected_links,
                incremental_mode=movie_incremental_mode,
                affected_targets=movie_affected_targets,
                matched_item_ids=matched_movie_ids,
            )

        if self.sonarr_enabled:
            removed_orphans += self._cleanup_with_manager(
                manager=self.sonarr_cleanup_manager,
                existing_folders=existing_folders,
                items_by_ref=series_by_ref,
                expected_links=expected_links,
                incremental_mode=series_incremental_mode,
                affected_targets=series_affected_targets,
                matched_item_ids=matched_series_ids,
            )

        return removed_orphans

    def _cleanup_with_manager(
        self,
        manager: ShadowCleanupManager,
        existing_folders: set[Path],
        items_by_ref: dict[MovieRef, dict],
        expected_links: set[Path],
        incremental_mode: bool,
        affected_targets: set[Path],
        matched_item_ids: set[int],
    ) -> int:
        if incremental_mode:
            return manager.cleanup_orphans_for_targets(
                existing_folders=existing_folders,
                movies_by_ref=items_by_ref,
                expected_links=expected_links,
                affected_targets=affected_targets,
                matched_movie_ids=matched_item_ids,
            )

        return manager.cleanup_orphans(
            existing_folders,
            items_by_ref,
            expected_links,
            matched_movie_ids=matched_item_ids,
        )
