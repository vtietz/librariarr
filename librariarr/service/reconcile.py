from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..core import (
    MediaReconcileOutcome,
    MediaScope,
    ReconcilePlan,
    build_cleanup_tasks,
    create_reconcile_plan,
    resolve_reconcile_mode,
)
from ..projection import get_radarr_webhook_queue
from ..sync import (
    MovieRef,
    ShadowCleanupManager,
    collect_current_links,
    discover_series_folders,
)
from .common import LOG


def _summarize_path_set(paths: set[Path] | None, limit: int = 4) -> str:
    if not paths:
        return "-"

    unique_paths = sorted({str(path) for path in paths})
    shown = unique_paths[:limit]
    remaining = len(unique_paths) - len(shown)
    suffix = f" (+{remaining} more)" if remaining > 0 else ""
    return ", ".join(shown) + suffix


def _first_path(paths: set[Path] | None) -> str:
    if not paths:
        return "-"
    return sorted(str(path) for path in paths)[0]


@dataclass(frozen=True)
class _MediaReconcileSpec:
    sync_enabled: bool
    auto_add_unmatched: bool
    is_root_available: Callable[[Path], bool]
    skip_log_message: str
    post_auto_add_no_match_log_message: str
    post_auto_add_no_match_log_level: str
    no_match_message_when_auto_add_disabled: str
    match_item_for_folder: Callable[
        [Path, dict[MovieRef, dict], dict[str, dict], dict[str, dict], set[Path]],
        dict | None,
    ]
    auto_add_item_for_folder: Callable[[Path, Path], dict | None]
    sync_item_for_folder: Callable[[Path, Path, dict, bool], None]
    index_item: Callable[[dict[MovieRef, dict], dict], None]
    index_item_path: Callable[[dict[str, dict], dict], None]
    index_item_external_ids: Callable[[dict[str, dict], dict], None]


class ServiceReconcileMixin:
    def reconcile(  # noqa: C901
        self,
        affected_paths: set[Path] | None = None,
        *,
        refresh_arr_root_availability: bool = True,
    ) -> bool:
        with self._lock:
            started = time.time()
            reconcile_mode, affected_paths_count = resolve_reconcile_mode(affected_paths)
            trigger_source = self._current_reconcile_source()
            trigger_path = _first_path(affected_paths)
            LOG.info(
                "Reconcile started: source=%s mode=%s affected_paths=%s trigger_path=%s",
                trigger_source,
                reconcile_mode,
                affected_paths_count,
                trigger_path,
            )
            for shadow_root in self.shadow_roots:
                shadow_root.mkdir(parents=True, exist_ok=True)

            if refresh_arr_root_availability:
                self._update_arr_root_folder_availability(
                    force=self._arr_root_poll_interval is None,
                )

            scoped_movie_ids: set[int] | None = None
            if self.radarr_enabled:
                queued_movie_ids = get_radarr_webhook_queue().consume_movie_ids()
                if queued_movie_ids:
                    scoped_movie_ids = queued_movie_ids

            ingested_count = self.ingestor.run() if self.config.ingest.enabled else 0
            ingest_pending = False
            if self.config.ingest.enabled:
                ingest_pending = self.ingestor.last_pending_quiescent_count > 0

            scoped_affected_paths = affected_paths
            if scoped_movie_ids is not None and affected_paths is None:
                scoped_affected_paths = set()

            plan = self._build_reconcile_plan(
                affected_paths=scoped_affected_paths,
                reconcile_mode=reconcile_mode,
                affected_paths_count=affected_paths_count,
            )
            if getattr(self, "runtime_status_tracker", None) is not None:
                self.runtime_status_tracker.update_reconcile_phase("scope_resolved")

            LOG.debug(
                "Reconcile scope: source=%s mode=%s affected_paths=%s "
                "considered_movie_folders=%s considered_series_folders=%s",
                trigger_source,
                plan.mode,
                plan.affected_paths_count,
                len(plan.movie_scope.folders),
                len(plan.series_scope.folders),
            )

            target_to_links = collect_current_links(self.shadow_roots)
            if plan.fetch_series_index:
                series_by_ref, series_by_path, series_by_external_id = self._build_series_indices()
            else:
                series_by_ref, series_by_path, series_by_external_id = {}, {}, {}
            if getattr(self, "runtime_status_tracker", None) is not None:
                self.runtime_status_tracker.update_reconcile_phase("indexed")
            expected_links: set[Path] = set()
            movie_created_links = 0
            matched_movies = 0
            unmatched_movies = 0
            if self.radarr_enabled:
                if self.movie_projection is None:
                    raise RuntimeError(
                        "MovieProjectionOrchestrator is required when Radarr is enabled"
                    )
                self.movie_projection.radarr = self.radarr
                projection_metrics = self.movie_projection.reconcile(scoped_movie_ids)
                movie_created_links = int(projection_metrics.get("projected_files") or 0)
                matched_movies = max(
                    0,
                    int(projection_metrics.get("planned_movies") or 0)
                    - int(projection_metrics.get("skipped_movies") or 0),
                )
                unmatched_movies = int(projection_metrics.get("skipped_movies") or 0)
            (
                series_created_links,
                matched_series,
                unmatched_series,
                matched_series_ids,
            ) = self._reconcile_series_links(
                series_folders=plan.series_scope.folders,
                target_to_links=target_to_links,
                expected_links=expected_links,
                series_by_ref=series_by_ref,
                series_by_path=series_by_path,
                series_by_external_id=series_by_external_id,
            )
            created_links = movie_created_links + series_created_links
            if getattr(self, "runtime_status_tracker", None) is not None:
                self.runtime_status_tracker.update_reconcile_phase("applied")

            orphaned_links_removed = self._cleanup_orphans(
                all_series_folders=plan.series_scope.all_folders,
                expected_links=expected_links,
                series_by_ref=series_by_ref,
                series_incremental_mode=plan.series_scope.incremental_mode,
                series_affected_targets=plan.series_scope.affected_targets,
                matched_series_ids=matched_series_ids,
            )
            if getattr(self, "runtime_status_tracker", None) is not None:
                self.runtime_status_tracker.update_reconcile_phase("cleaned")

            duration_seconds = round(time.time() - started, 2)
            outcome = "updated"
            if (
                created_links == 0
                and orphaned_links_removed == 0
                and matched_movies == 0
                and unmatched_movies == 0
                and matched_series == 0
                and unmatched_series == 0
                and ingested_count == 0
            ):
                outcome = "pending_ingest" if ingest_pending else "no_changes"
            if getattr(self, "runtime_status_tracker", None) is not None:
                self.runtime_status_tracker.update_active_reconcile_metrics(
                    {
                        "movie_folders_seen": len(plan.movie_scope.folders),
                        "series_folders_seen": len(plan.series_scope.folders),
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
                            int(plan.affected_paths_count)
                            if isinstance(plan.affected_paths_count, int)
                            else None
                        ),
                    }
                )
            LOG.info(
                "Reconcile finished: source=%s mode=%s affected_paths=%s trigger_path=%s "
                "outcome=%s movie_folders=%s series_folders=%s "
                "created_links=%s matched_movies=%s matched_series=%s "
                "removed_orphans=%s ingest_pending=%s duration_seconds=%s",
                trigger_source,
                plan.mode,
                plan.affected_paths_count,
                trigger_path,
                outcome,
                len(plan.movie_scope.folders),
                len(plan.series_scope.folders),
                created_links,
                matched_movies,
                matched_series,
                orphaned_links_removed,
                ingest_pending,
                duration_seconds,
            )
            if getattr(self, "runtime_status_tracker", None) is not None:
                self.runtime_status_tracker.update_reconcile_phase("completed")
            return ingest_pending

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

    def _build_reconcile_plan(
        self,
        *,
        affected_paths: set[Path] | None,
        reconcile_mode: str,
        affected_paths_count: int | str,
    ) -> ReconcilePlan:
        movie_scope = MediaScope(
            folders={},
            all_folders={},
            affected_targets=set(),
            incremental_mode=False,
        )

        series_scope = MediaScope(
            folders={},
            all_folders={},
            affected_targets=set(),
            incremental_mode=False,
        )
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
            self._known_series_folders = all_series_folders
            series_scope = MediaScope(
                folders=series_folders,
                all_folders=all_series_folders,
                affected_targets=series_affected_targets,
                incremental_mode=series_incremental_mode,
            )

        return create_reconcile_plan(
            mode=reconcile_mode,
            affected_paths_count=affected_paths_count,
            movie_scope=movie_scope,
            series_scope=series_scope,
            movie_sync_enabled=False,
            series_sync_enabled=self.sonarr_sync_enabled,
        )

    def _reconcile_series_links(
        self,
        series_folders: dict[Path, Path],
        target_to_links: dict[Path, set[Path]],
        expected_links: set[Path],
        series_by_ref: dict[MovieRef, dict],
        series_by_path: dict[str, dict],
        series_by_external_id: dict[str, dict],
    ) -> tuple[int, int, int, set[int]]:
        def _sync_series(folder: Path, link_path: Path, series: dict, auto_added: bool) -> None:
            self._sync_sonarr_for_folder(
                folder,
                link_path,
                series,
                force_refresh=auto_added,
            )

        outcome = self._reconcile_links_for_kind(
            folders=series_folders,
            target_to_links=target_to_links,
            expected_links=expected_links,
            items_by_ref=series_by_ref,
            items_by_path=series_by_path,
            items_by_external_id=series_by_external_id,
            spec=_MediaReconcileSpec(
                sync_enabled=self.sonarr_sync_enabled,
                auto_add_unmatched=self.sonarr_auto_add_unmatched,
                is_root_available=self._is_sonarr_root_available,
                skip_log_message=(
                    "Skipping Sonarr matching/sync for shadow root not configured in Sonarr: %s"
                ),
                post_auto_add_no_match_log_message=(
                    "No Sonarr match for folder after auto-add attempt: %s"
                ),
                post_auto_add_no_match_log_level="warning",
                no_match_message_when_auto_add_disabled=(
                    "No Sonarr match for folder: %s "
                    "(enable sonarr.auto_add_unmatched=true to auto-create, "
                    "or add/import in Sonarr first)"
                ),
                match_item_for_folder=self._match_series_for_folder,
                auto_add_item_for_folder=self.sonarr_sync.auto_add_series_for_folder,
                sync_item_for_folder=_sync_series,
                index_item=self._index_series,
                index_item_path=self._index_series_path,
                index_item_external_ids=self._index_series_external_ids,
            ),
        )
        return (
            outcome.created_links,
            outcome.matched_items,
            outcome.unmatched_items,
            outcome.matched_item_ids,
        )

    def _reconcile_links_for_kind(
        self,
        *,
        folders: dict[Path, Path],
        target_to_links: dict[Path, set[Path]],
        expected_links: set[Path],
        items_by_ref: dict[MovieRef, dict],
        items_by_path: dict[str, dict],
        items_by_external_id: dict[str, dict],
        spec: _MediaReconcileSpec,
    ) -> MediaReconcileOutcome:
        created_links = 0
        matched_items = 0
        unmatched_items = 0
        auto_added_item_ids: set[int] = set()
        matched_item_ids: set[int] = set()
        logged_unavailable_roots: set[str] = set()

        for folder, shadow_root in sorted(folders.items()):
            existing_links = target_to_links.get(folder, set())
            root_available, preserved_existing_link = (
                self._resolve_root_availability_and_preserve_existing_link(
                    sync_enabled=spec.sync_enabled,
                    shadow_root=shadow_root,
                    existing_links=existing_links,
                    expected_links=expected_links,
                    target_to_links=target_to_links,
                    folder=folder,
                    logged_unavailable_roots=logged_unavailable_roots,
                    is_root_available=spec.is_root_available,
                    skip_log_message=spec.skip_log_message,
                )
            )
            if preserved_existing_link:
                continue

            item = (
                spec.match_item_for_folder(
                    folder,
                    items_by_ref,
                    items_by_path,
                    items_by_external_id,
                    existing_links,
                )
                if spec.sync_enabled and root_available
                else None
            )
            attempted_auto_add = False
            if spec.sync_enabled and root_available and item is None and spec.auto_add_unmatched:
                attempted_auto_add = True
                item = spec.auto_add_item_for_folder(folder, shadow_root)
                if item is not None:
                    self._add_movie_id_if_present(auto_added_item_ids, item)
                    spec.index_item(items_by_ref, item)
                    spec.index_item_path(items_by_path, item)
                    spec.index_item_external_ids(items_by_external_id, item)

            link_path, was_created = self.link_manager.ensure_link(
                folder,
                shadow_root,
                existing_links,
                item,
            )
            expected_links.add(link_path)
            target_to_links.setdefault(folder, set()).add(link_path)
            if was_created:
                created_links += 1

            if not spec.sync_enabled or not root_available:
                continue

            if item is not None:
                item_id = self._add_movie_id_if_present(matched_item_ids, item)
                spec.sync_item_for_folder(
                    folder,
                    link_path,
                    item,
                    item_id is not None and item_id in auto_added_item_ids,
                )
                matched_items += 1
                continue

            if spec.auto_add_unmatched:
                if attempted_auto_add:
                    if spec.post_auto_add_no_match_log_level == "debug":
                        LOG.debug(spec.post_auto_add_no_match_log_message, folder)
                    else:
                        LOG.warning(spec.post_auto_add_no_match_log_message, folder)
            else:
                LOG.warning(spec.no_match_message_when_auto_add_disabled, folder)
            unmatched_items += 1

        return MediaReconcileOutcome(
            created_links=created_links,
            matched_items=matched_items,
            unmatched_items=unmatched_items,
            matched_item_ids=matched_item_ids,
        )

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
        all_series_folders: dict[Path, Path],
        expected_links: set[Path],
        series_by_ref: dict[MovieRef, dict],
        series_incremental_mode: bool,
        series_affected_targets: set[Path],
        matched_series_ids: set[int],
    ) -> int:
        cleanup_tasks = build_cleanup_tasks(
            remove_orphaned_links=self.config.cleanup.remove_orphaned_links,
            radarr_enabled=False,
            sonarr_enabled=self.sonarr_enabled,
            movie_incremental_mode=False,
            series_incremental_mode=series_incremental_mode,
            movie_affected_targets=set(),
            series_affected_targets=series_affected_targets,
            matched_movie_ids=set(),
            matched_series_ids=matched_series_ids,
        )
        if not cleanup_tasks:
            return 0

        existing_folders = set(all_series_folders.keys())
        removed_orphans = 0
        for task in cleanup_tasks:
            removed_orphans += self._cleanup_with_manager(
                manager=self.sonarr_cleanup_manager,
                existing_folders=existing_folders,
                items_by_ref=series_by_ref,
                expected_links=expected_links,
                incremental_mode=task.incremental_mode,
                affected_targets=task.affected_targets,
                matched_item_ids=task.matched_item_ids,
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
