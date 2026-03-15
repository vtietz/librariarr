from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from ..config import AppConfig, load_config
from ..sync.discovery import discover_movie_folders
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


def _build_discovery_warnings_payload(config: AppConfig, limit: int = 200) -> dict[str, Any]:
    video_exts = set(config.runtime.scan_video_extensions or [".mkv", ".mp4", ".avi", ".mov"])
    exclude_paths = list(config.paths.exclude_paths)

    all_movie_paths: set[Path] = set()
    excluded_movie_paths: list[Path] = []

    for mapping in config.paths.root_mappings:
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

    return {
        "summary": {
            "exclude_patterns_count": len(exclude_paths),
            "excluded_movie_candidates": len(excluded_movie_paths),
            "duplicate_movie_candidates": len(duplicate_movie_candidates),
        },
        "exclude_paths": exclude_paths,
        "excluded_movie_candidates": [
            {
                "path": str(path),
                "reason": "matches paths.exclude_paths",
            }
            for path in excluded_movie_paths[:limit]
        ],
        "duplicate_movie_candidates": duplicate_movie_candidates[:limit],
    }


class DiscoveryWarningsCache:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._payload: dict[str, Any] = {
            "summary": {
                "exclude_patterns_count": 0,
                "excluded_movie_candidates": 0,
                "duplicate_movie_candidates": 0,
            },
            "exclude_paths": [],
            "excluded_movie_candidates": [],
            "duplicate_movie_candidates": [],
        }
        self._updated_at_ms: int | None = None
        self._last_error: str | None = None
        self._building = False
        self._version = 0
        self._last_build_finished = 0.0
        self._last_build_duration_ms: int | None = None
        self._last_signature: tuple[Any, ...] | None = None
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
                },
                "exclude_paths": [],
                "excluded_movie_candidates": [],
                "duplicate_movie_candidates": [],
            }
            self._updated_at_ms = None
            self._last_error = None
            self._building = False
            self._version = 0
            self._last_build_finished = 0.0
            self._last_build_duration_ms = None
            self._last_signature = None
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

    def _rebuild_worker(self, config: AppConfig) -> None:
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
                        "duration_ms": duration_ms,
                    },
                )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            with self._lock:
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
                self._building = False
                self._build_event.set()

    def request_refresh(self, config: AppConfig, *, force: bool = False) -> bool:
        signature = (
            tuple(
                (str(item.nested_root), str(item.shadow_root))
                for item in config.paths.root_mappings
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
            self._build_event.clear()

        thread = threading.Thread(target=self._rebuild_worker, args=(config,), daemon=True)
        thread.start()
        return True

    def wait_for_build(self, timeout: float) -> bool:
        return self._build_event.wait(timeout=timeout)

    def snapshot(self, *, limit: int = 200) -> dict[str, Any]:
        with self._lock:
            payload = {
                "summary": dict(self._payload.get("summary") or {}),
                "exclude_paths": list(self._payload.get("exclude_paths") or []),
                "excluded_movie_candidates": list(
                    (self._payload.get("excluded_movie_candidates") or [])[:limit]
                ),
                "duplicate_movie_candidates": list(
                    (self._payload.get("duplicate_movie_candidates") or [])[:limit]
                ),
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
