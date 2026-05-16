from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

from ..config import AppConfig, load_config
from ..projection.orchestrator import _projection_state_db_path
from ..projection.provenance import ProjectionStateStore
from ..projection.sonarr_orchestrator import _sonarr_projection_state_db_path
from ..quality import VIDEO_EXTENSIONS
from ..sync.discovery import (
    _is_excluded_path,
    _normalize_exclude_patterns,
    discover_movie_folders,
)
from ..sync.naming import parse_movie_ref
from .jobs import JobManager
from .state_store import PersistentStateStore


def _duplicate_group_ref(path: Path) -> tuple[str, int | None]:
    for candidate in (path, *path.parents):
        ref = parse_movie_ref(candidate.name)
        if ref.year is not None and ref.title:
            return ref.title, ref.year

    fallback = parse_movie_ref(path.name)
    return fallback.title, fallback.year


def _build_discovery_warnings_payload(config: AppConfig) -> dict[str, Any]:
    video_exts = set(config.runtime.scan_video_extensions or VIDEO_EXTENSIONS)
    exclude_paths = list(config.paths.exclude_paths)

    all_movie_paths: set[Path] = set()
    excluded_movie_paths: list[Path] = []

    for mapping in config.paths.movie_root_mappings:
        managed_root = Path(mapping.managed_root)
        all_folders = discover_movie_folders(managed_root, video_exts, [])
        all_movie_paths.update(all_folders)
        if exclude_paths:
            included = discover_movie_folders(managed_root, video_exts, exclude_paths)
            excluded_movie_paths.extend(sorted(all_folders - included, key=lambda path: str(path)))

    for mapping in config.paths.series_root_mappings:
        nested_root = Path(mapping.nested_root)
        all_folders = discover_movie_folders(nested_root, video_exts, [])
        all_movie_paths.update(all_folders)
        if exclude_paths:
            included = discover_movie_folders(nested_root, video_exts, exclude_paths)
            excluded_movie_paths.extend(sorted(all_folders - included, key=lambda path: str(path)))

    included_movie_paths = all_movie_paths - set(excluded_movie_paths)
    excluded_movie_paths.sort(key=lambda path: str(path))

    grouped: dict[tuple[str, int | None], list[Path]] = {}
    for movie_path in all_movie_paths:
        grouped.setdefault(_duplicate_group_ref(movie_path), []).append(movie_path)

    duplicate_movie_candidates: list[dict[str, Any]] = []
    for (title, year), paths in grouped.items():
        if len(paths) < 2:
            continue

        ordered = sorted(paths, key=lambda path: str(path))
        preferred = [path for path in ordered if path in included_movie_paths]
        primary_path = preferred[0] if preferred else ordered[0]
        duplicate_paths = [path for path in ordered if path != primary_path]

        duplicate_movie_candidates.append(
            {
                "movie_ref": f"{title} ({year})" if year is not None else title,
                "primary_path": str(primary_path),
                "duplicate_paths": [str(path) for path in duplicate_paths],
                "contains_excluded": any(path in excluded_movie_paths for path in ordered),
            }
        )

    duplicate_movie_candidates.sort(
        key=lambda item: (
            -len(item["duplicate_paths"]),
            str(item["movie_ref"]),
        )
    )

    orphaned_managed_movie_paths = _discover_orphaned_managed_movie_folders(
        mappings=config.paths.movie_root_mappings,
        video_exts=video_exts,
        exclude_patterns=exclude_paths,
    )
    tracked_managed_folders = _tracked_managed_folder_paths()
    unmatched_managed_movie_paths = sorted(
        [
            path
            for path in included_movie_paths
            if path.resolve(strict=False) not in tracked_managed_folders
        ],
        key=lambda path: str(path),
    )
    unmanaged_shadow_video_files = _discover_unmanaged_shadow_video_files(
        config=config,
        video_exts=video_exts,
    )
    mapping_collision_candidates = _discover_mapping_collision_candidates()

    return {
        "summary": {
            "exclude_patterns_count": len(exclude_paths),
            "excluded_movie_candidates": len(excluded_movie_paths),
            "duplicate_movie_candidates": len(duplicate_movie_candidates),
            "orphaned_managed_movie_candidates": len(orphaned_managed_movie_paths),
            "unmatched_managed_movie_candidates": len(unmatched_managed_movie_paths),
            "unmanaged_shadow_video_files": len(unmanaged_shadow_video_files),
            "mapping_collision_candidates": len(mapping_collision_candidates),
        },
        "exclude_paths": exclude_paths,
        "excluded_movie_candidates": [
            {
                "path": str(path),
                "reason": "matches paths.exclude_paths",
            }
            for path in excluded_movie_paths
        ],
        "duplicate_movie_candidates": duplicate_movie_candidates,
        "orphaned_managed_movie_candidates": [
            {
                "path": str(path),
                "reason": "managed folder has no video files",
            }
            for path in orphaned_managed_movie_paths
        ],
        "unmatched_managed_movie_candidates": [
            {
                "path": str(path),
                "reason": "managed folder has video files but is not mapped in Arr/provenance",
            }
            for path in unmatched_managed_movie_paths
        ],
        "unmanaged_shadow_video_files": [
            {
                "path": str(path),
                "reason": (
                    "video file exists in shadow/library root but is not tracked by projection"
                ),
            }
            for path in unmanaged_shadow_video_files
        ],
        "mapping_collision_candidates": mapping_collision_candidates,
    }


def _discover_mapping_collision_candidates() -> list[dict[str, Any]]:
    folder_to_movie_ids: dict[str, set[int]] = {}
    source_to_movie_ids: dict[str, set[int]] = {}

    for db_path_fn in (_projection_state_db_path,):
        db_path = db_path_fn()
        if not db_path.exists():
            continue

        store = ProjectionStateStore(db_path)
        for movie_id, folder in store.get_managed_folders_by_movie_ids().items():
            folder_key = str(folder.resolve(strict=False))
            folder_to_movie_ids.setdefault(folder_key, set()).add(movie_id)

        for movie_id, _dest_path, source_path, _dev, _inode in store.list_managed_projected_rows():
            source_key = str(Path(source_path).resolve(strict=False))
            source_to_movie_ids.setdefault(source_key, set()).add(movie_id)

    collisions: list[dict[str, Any]] = []
    for folder, movie_ids in sorted(folder_to_movie_ids.items()):
        if len(movie_ids) < 2:
            continue
        collisions.append(
            {
                "type": "shared_managed_folder",
                "path": folder,
                "movie_ids": sorted(movie_ids),
                "reason": "multiple movie ids map to one managed folder",
            }
        )

    for source_path, movie_ids in sorted(source_to_movie_ids.items()):
        if len(movie_ids) < 2:
            continue
        collisions.append(
            {
                "type": "shared_source_file",
                "path": source_path,
                "movie_ids": sorted(movie_ids),
                "reason": "one managed source file is projected to multiple movie ids",
            }
        )

    collisions.sort(
        key=lambda item: (
            -len(item.get("movie_ids") or []),
            str(item.get("type") or ""),
            str(item.get("path") or ""),
        )
    )
    return collisions


def _tracked_projection_destination_paths() -> set[Path]:
    tracked: set[Path] = set()
    for db_path_fn in (_projection_state_db_path, _sonarr_projection_state_db_path):
        db_path = db_path_fn()
        if not db_path.exists():
            continue
        store = ProjectionStateStore(db_path)
        for _item_id, dest_path_raw, _source, _dev, _inode in store.list_managed_projected_rows():
            tracked.add(Path(dest_path_raw).resolve(strict=False))
    return tracked


def _tracked_managed_folder_paths() -> set[Path]:
    tracked: set[Path] = set()
    for db_path_fn in (_projection_state_db_path, _sonarr_projection_state_db_path):
        db_path = db_path_fn()
        if not db_path.exists():
            continue
        store = ProjectionStateStore(db_path)
        tracked.update(
            folder.resolve(strict=False)
            for folder in store.get_managed_folders_by_movie_ids().values()
        )
        tracked.update(
            folder.resolve(strict=False)
            for folder in store.get_managed_folders_by_series_ids().values()
        )
    return tracked


def _shadow_roots(config: AppConfig) -> list[Path]:
    roots: set[Path] = set()
    roots.update(
        Path(item.library_root).resolve(strict=False) for item in config.paths.movie_root_mappings
    )
    roots.update(
        Path(item.shadow_root).resolve(strict=False) for item in config.paths.series_root_mappings
    )
    return sorted(roots)


def _discover_unmanaged_shadow_video_files(
    *,
    config: AppConfig,
    video_exts: set[str],
) -> list[Path]:
    tracked_destinations = _tracked_projection_destination_paths()
    candidates: set[Path] = set()
    for shadow_root in _shadow_roots(config):
        if not shadow_root.exists() or not shadow_root.is_dir():
            continue
        for current, _dirs, files in os.walk(shadow_root):
            current_path = Path(current)
            for filename in files:
                file_path = (current_path / filename).resolve(strict=False)
                if file_path.suffix.lower() not in video_exts:
                    continue
                if file_path in tracked_destinations:
                    continue
                candidates.add(file_path)

    return sorted(candidates, key=lambda path: str(path))


def _discover_orphaned_managed_movie_folders(
    *,
    mappings: list[Any],
    video_exts: set[str],
    exclude_patterns: list[str] | None = None,
) -> list[Path]:
    excludes = _normalize_exclude_patterns(exclude_patterns)
    candidates: set[Path] = set()
    for mapping in mappings:
        managed_root = Path(mapping.managed_root)
        if not managed_root.exists():
            continue

        for current, dirs, _files in os.walk(managed_root):
            current_path = Path(current)
            if _is_excluded_path(current_path, managed_root, excludes, is_dir=True):
                dirs[:] = []
                continue

            # Treat any folder with child directories as a container folder,
            # even when those children are excluded from scanning.
            has_child_directories = bool(dirs)

            dirs[:] = sorted(
                dirname
                for dirname in dirs
                if not _is_excluded_path(
                    current_path / dirname,
                    managed_root,
                    excludes,
                    is_dir=True,
                )
            )
            if current_path == managed_root:
                continue
            if has_child_directories:
                continue
            # Keep orphan warnings focused on movie-like folders and skip
            # utility/container leaf folders such as collection placeholders.
            if parse_movie_ref(current_path.name).year is None:
                continue
            if _contains_video_recursively(
                current_path,
                video_exts,
                root=managed_root,
                exclude_patterns=excludes,
            ):
                continue
            candidates.add(current_path)

    return sorted(candidates, key=lambda path: str(path))


def _contains_video_recursively(
    folder: Path,
    video_exts: set[str],
    *,
    root: Path | None = None,
    exclude_patterns: list[str] | None = None,
) -> bool:
    base_root = root or folder
    excludes = exclude_patterns or []
    for current, dirs, files in os.walk(folder):
        current_path = Path(current)
        if _is_excluded_path(current_path, base_root, excludes, is_dir=True):
            dirs[:] = []
            continue

        dirs[:] = [
            dirname
            for dirname in dirs
            if not _is_excluded_path(current_path / dirname, base_root, excludes, is_dir=True)
        ]

        if any(
            Path(name).suffix.lower() in video_exts
            and not _is_excluded_path(current_path / name, base_root, excludes, is_dir=False)
            for name in files
        ):
            return True
    return False


class DiscoveryWarningsCache:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._payload: dict[str, Any] = {
            "summary": {
                "exclude_patterns_count": 0,
                "excluded_movie_candidates": 0,
                "duplicate_movie_candidates": 0,
                "orphaned_managed_movie_candidates": 0,
                "unmatched_managed_movie_candidates": 0,
                "unmanaged_shadow_video_files": 0,
                "mapping_collision_candidates": 0,
            },
            "exclude_paths": [],
            "excluded_movie_candidates": [],
            "duplicate_movie_candidates": [],
            "orphaned_managed_movie_candidates": [],
            "unmatched_managed_movie_candidates": [],
            "unmanaged_shadow_video_files": [],
            "mapping_collision_candidates": [],
        }
        self._updated_at_ms: int | None = None
        self._last_error: str | None = None
        self._building = False
        self._version = 0
        self._last_build_finished = 0.0
        self._last_build_duration_ms: int | None = None
        self._last_signature: tuple[Any, ...] | None = None
        self._build_generation = 0
        self._build_event = threading.Event()
        self._state_store: PersistentStateStore | None = None
        self._task_manager: JobManager | None = None

    def attach_state(self, *, state_store: PersistentStateStore, task_manager: JobManager) -> None:
        with self._lock:
            self._state_store = state_store
            self._task_manager = task_manager
            self._payload = {
                "summary": {
                    "exclude_patterns_count": 0,
                    "excluded_movie_candidates": 0,
                    "duplicate_movie_candidates": 0,
                    "orphaned_managed_movie_candidates": 0,
                    "unmatched_managed_movie_candidates": 0,
                    "unmanaged_shadow_video_files": 0,
                    "mapping_collision_candidates": 0,
                },
                "exclude_paths": [],
                "excluded_movie_candidates": [],
                "duplicate_movie_candidates": [],
                "orphaned_managed_movie_candidates": [],
                "unmatched_managed_movie_candidates": [],
                "unmanaged_shadow_video_files": [],
                "mapping_collision_candidates": [],
            }
            self._updated_at_ms = None
            self._last_error = None
            self._building = False
            self._version = 0
            self._last_build_finished = 0.0
            self._last_build_duration_ms = None
            self._last_signature = None
            self._build_generation += 1
            self._build_event = threading.Event()
            payload = state_store.load_cache_snapshot("discovery_warnings")
            if not isinstance(payload, dict):
                return
            stored_payload = payload.get("payload")
            if isinstance(stored_payload, dict):
                self._payload = stored_payload
            updated_at_ms = payload.get("updated_at_ms")
            self._updated_at_ms = updated_at_ms if isinstance(updated_at_ms, int | float) else None
            self._last_error = (
                str(payload.get("last_error")) if payload.get("last_error") is not None else None
            )
            self._version = int(payload.get("version") or self._version)
            self._last_build_duration_ms = payload.get("last_build_duration_ms")

    def _persist_snapshot_locked(self) -> None:
        if self._state_store is None:
            return
        self._state_store.save_cache_snapshot(
            "discovery_warnings",
            {
                "payload": dict(self._payload),
                "updated_at_ms": self._updated_at_ms,
                "last_error": self._last_error,
                "version": self._version,
                "last_build_duration_ms": self._last_build_duration_ms,
            },
        )

    def _rebuild_worker(self, config: AppConfig, build_generation: int) -> None:
        with self._lock:
            if build_generation != self._build_generation:
                return
        started = time.perf_counter()
        task_id: str | None = None
        if self._task_manager is not None:
            task_id = self._task_manager.begin_external_task(
                kind="cache-refresh-discovery",
                name="Discovery Snapshot Rebuild",
                source="cache",
                detail="Rebuilding discovery warning snapshot",
                payload={"cache_name": "discovery_warnings"},
                task_key="discovery-index",
                history_visible=False,
            )
        try:
            payload = _build_discovery_warnings_payload(config=config)
            duration_ms = int((time.perf_counter() - started) * 1000)
            with self._lock:
                if build_generation != self._build_generation:
                    return
                self._payload = payload
                self._updated_at_ms = int(time.time() * 1000)
                self._last_error = None
                self._version += 1
                self._last_build_finished = time.time()
                self._last_build_duration_ms = duration_ms
                self._persist_snapshot_locked()
            if task_id is not None and self._task_manager is not None:
                self._task_manager.finish_external_task(
                    task_id,
                    success=True,
                    detail="Discovery warning snapshot rebuilt",
                    result={
                        "excluded_movie_candidates": payload["summary"][
                            "excluded_movie_candidates"
                        ],
                        "duplicate_movie_candidates": payload["summary"][
                            "duplicate_movie_candidates"
                        ],
                        "orphaned_managed_movie_candidates": payload["summary"][
                            "orphaned_managed_movie_candidates"
                        ],
                        "unmatched_managed_movie_candidates": payload["summary"][
                            "unmatched_managed_movie_candidates"
                        ],
                        "unmanaged_shadow_video_files": payload["summary"][
                            "unmanaged_shadow_video_files"
                        ],
                        "mapping_collision_candidates": payload["summary"][
                            "mapping_collision_candidates"
                        ],
                        "duration_ms": duration_ms,
                    },
                )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            with self._lock:
                if build_generation != self._build_generation:
                    return
                self._last_error = str(exc)
                self._version += 1
                self._last_build_finished = time.time()
                self._last_build_duration_ms = duration_ms
                self._persist_snapshot_locked()
            if task_id is not None and self._task_manager is not None:
                self._task_manager.finish_external_task(
                    task_id,
                    success=False,
                    detail="Discovery warning snapshot rebuild failed",
                    error=str(exc),
                    result={"duration_ms": duration_ms},
                )
        finally:
            with self._lock:
                if build_generation == self._build_generation:
                    self._building = False
                    self._build_event.set()

    def request_refresh(self, config: AppConfig, *, force: bool = False) -> bool:
        signature = (
            tuple(
                (str(item.managed_root), str(item.library_root))
                for item in config.paths.movie_root_mappings
            ),
            tuple(
                (str(item.nested_root), str(item.shadow_root))
                for item in config.paths.series_root_mappings
            ),
            tuple(config.paths.exclude_paths),
            tuple(config.runtime.scan_video_extensions or []),
        )
        with self._lock:
            if self._building:
                return False
            signature_changed = signature != self._last_signature
            if not force:
                recent_build = (time.time() - self._last_build_finished) < 10
                if self._updated_at_ms is not None and recent_build and not signature_changed:
                    return False
            self._building = True
            self._last_signature = signature
            build_generation = self._build_generation
            self._build_event.clear()

        thread = threading.Thread(
            target=self._rebuild_worker,
            args=(config, build_generation),
            daemon=True,
        )
        thread.start()
        return True

    def wait_for_build(self, timeout: float) -> bool:
        return self._build_event.wait(timeout=timeout)

    def snapshot(self, *, limit: int | None = 200) -> dict[str, Any]:
        def _limited(items: list[Any]) -> list[Any]:
            if limit is None:
                return list(items)
            return list(items[:limit])

        with self._lock:
            excluded_items = list(self._payload.get("excluded_movie_candidates") or [])
            duplicate_items = list(self._payload.get("duplicate_movie_candidates") or [])
            orphaned_items = list(self._payload.get("orphaned_managed_movie_candidates") or [])
            unmatched_items = list(self._payload.get("unmatched_managed_movie_candidates") or [])
            unmanaged_shadow_items = list(self._payload.get("unmanaged_shadow_video_files") or [])
            mapping_collision_items = list(self._payload.get("mapping_collision_candidates") or [])

            payload = {
                "summary": dict(self._payload.get("summary") or {}),
                "exclude_paths": list(self._payload.get("exclude_paths") or []),
                "excluded_movie_candidates": _limited(excluded_items),
                "duplicate_movie_candidates": _limited(duplicate_items),
                "orphaned_managed_movie_candidates": _limited(orphaned_items),
                "unmatched_managed_movie_candidates": _limited(unmatched_items),
                "unmanaged_shadow_video_files": _limited(unmanaged_shadow_items),
                "mapping_collision_candidates": _limited(mapping_collision_items),
                "truncated": {
                    "excluded_movie_candidates": limit is not None and len(excluded_items) > limit,
                    "duplicate_movie_candidates": limit is not None
                    and len(duplicate_items) > limit,
                    "orphaned_managed_movie_candidates": limit is not None
                    and len(orphaned_items) > limit,
                    "unmatched_managed_movie_candidates": limit is not None
                    and len(unmatched_items) > limit,
                    "unmanaged_shadow_video_files": limit is not None
                    and len(unmanaged_shadow_items) > limit,
                    "mapping_collision_candidates": limit is not None
                    and len(mapping_collision_items) > limit,
                },
                "cache": {
                    "ready": self._updated_at_ms is not None,
                    "building": self._building,
                    "updated_at_ms": self._updated_at_ms,
                    "last_error": self._last_error,
                    "version": self._version,
                    "last_build_duration_ms": self._last_build_duration_ms,
                },
            }
        return payload


_discovery_warnings_cache = DiscoveryWarningsCache()


def get_discovery_warnings_cache() -> DiscoveryWarningsCache:
    return _discovery_warnings_cache


def warmup_discovery_warnings_cache(config_path: Path) -> None:
    try:
        config = load_config(config_path)
    except Exception:
        return
    if _discovery_warnings_cache.request_refresh(config, force=True):
        _discovery_warnings_cache.wait_for_build(timeout=10.0)
