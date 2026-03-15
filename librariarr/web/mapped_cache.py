from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from ..config import AppConfig, load_config


def shadow_roots(config: AppConfig) -> list[Path]:
    roots = {Path(item.shadow_root) for item in config.paths.root_mappings}
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
        self._build_event = threading.Event()

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
        try:
            items, roots = self._scan(config)
            with self._lock:
                self._items = items
                self._shadow_roots = roots
                self._updated_at_ms = int(time.time() * 1000)
                self._last_error = None
                self._version += 1
                self._last_build_finished = time.time()
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
                self._version += 1
                self._last_build_finished = time.time()
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
