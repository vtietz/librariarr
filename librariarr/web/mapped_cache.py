from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from ..config import AppConfig, load_config
from .jobs import JobManager
from .state_store import PersistentStateStore


def shadow_roots(config: AppConfig) -> list[Path]:
    roots = {Path(item.shadow_root) for item in config.paths.series_root_mappings}
    return sorted(roots)


def safe_directory_entries(root: Path) -> list[Path]:
    try:
        return sorted(root.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        return []


class MappedDirectoriesCache:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: list[dict[str, Any]] = []
        self._shadow_roots: list[str] = []
        self._updated_at_ms: int | None = None
        self._last_error: str | None = None
        self._building = False
        self._version = 0
        self._last_build_finished = 0.0
        self._last_build_duration_ms: int | None = None
        self._build_event = threading.Event()
        self._state_store: PersistentStateStore | None = None
        self._task_manager: JobManager | None = None

    def attach_state(self, *, state_store: PersistentStateStore, task_manager: JobManager) -> None:
        with self._lock:
            self._state_store = state_store
            self._task_manager = task_manager
            self._items = []
            self._shadow_roots = []
            self._updated_at_ms = None
            self._last_error = None
            self._building = False
            self._version = 0
            self._last_build_finished = 0.0
            self._last_build_duration_ms = None
            self._build_event = threading.Event()
            payload = state_store.load_cache_snapshot("mapped_directories")
            if not isinstance(payload, dict):
                return
            items = payload.get("items")
            roots = payload.get("shadow_roots")
            if isinstance(items, list):
                self._items = list(items)
            if isinstance(roots, list):
                self._shadow_roots = [str(root) for root in roots]
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
            "mapped_directories",
            {
                "items": list(self._items),
                "shadow_roots": list(self._shadow_roots),
                "updated_at_ms": self._updated_at_ms,
                "last_error": self._last_error,
                "version": self._version,
                "last_build_duration_ms": self._last_build_duration_ms,
            },
        )

    def _scan(self, config: AppConfig) -> tuple[list[dict[str, Any]], list[str]]:
        roots = shadow_roots(config)
        items: list[dict[str, Any]] = []
        for root in roots:
            for child in safe_directory_entries(root):
                if not child.is_symlink():
                    continue
                virtual_path = str(child)
                real_path = str(child.resolve(strict=False))
                items.append(
                    {
                        "shadow_root": str(root),
                        "virtual_path": virtual_path,
                        "real_path": real_path,
                        "target_exists": Path(real_path).exists(),
                    }
                )
        return items, [str(root) for root in roots]

    def _rebuild_worker(self, config: AppConfig) -> None:
        started = time.perf_counter()
        task_id: str | None = None
        if self._task_manager is not None:
            task_id = self._task_manager.begin_external_task(
                kind="cache-refresh-mapped",
                name="Mapped Index Rebuild",
                source="cache",
                detail="Rebuilding mapped directory index",
                payload={"cache_name": "mapped_directories"},
                task_key="mapped-index",
                history_visible=False,
            )
        try:
            items, roots = self._scan(config)
            duration_ms = int((time.perf_counter() - started) * 1000)
            with self._lock:
                self._items = items
                self._shadow_roots = roots
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
                    detail="Mapped directory index rebuilt",
                    result={
                        "entries_total": len(items),
                        "shadow_roots": roots,
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
                    detail="Mapped directory index rebuild failed",
                    error=str(exc),
                    result={"duration_ms": duration_ms},
                )
        finally:
            with self._lock:
                self._building = False
                self._build_event.set()

    def request_refresh(self, config: AppConfig, *, force: bool = False) -> bool:
        with self._lock:
            if self._building:
                return False
            new_roots = sorted(str(r) for r in shadow_roots(config))
            roots_changed = new_roots != self._shadow_roots
            if not force and not roots_changed:
                recent_build = (time.time() - self._last_build_finished) < 10
                if self._updated_at_ms is not None and recent_build:
                    return False
            self._building = True
            self._build_event.clear()

        thread = threading.Thread(target=self._rebuild_worker, args=(config,), daemon=True)
        thread.start()
        return True

    def wait_for_build(self, timeout: float) -> bool:
        return self._build_event.wait(timeout=timeout)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "items": list(self._items),
                "shadow_roots": list(self._shadow_roots),
                "updated_at_ms": self._updated_at_ms,
                "last_error": self._last_error,
                "building": self._building,
                "ready": self._updated_at_ms is not None,
                "version": self._version,
                "last_build_duration_ms": self._last_build_duration_ms,
            }


_mapped_directories_cache = MappedDirectoriesCache()


def get_mapped_directories_cache() -> MappedDirectoriesCache:
    return _mapped_directories_cache


def warmup_mapped_directories_cache(config_path: Path) -> None:
    try:
        config = load_config(config_path)
    except Exception:
        return
    if _mapped_directories_cache.request_refresh(config, force=True):
        _mapped_directories_cache.wait_for_build(timeout=10.0)
