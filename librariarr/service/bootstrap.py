from __future__ import annotations

import threading
import time
from pathlib import Path

from ..clients.radarr import RadarrClient
from ..clients.sonarr import SonarrClient
from ..config import AppConfig
from ..inventory_snapshot import get_inventory_snapshot_store
from ..projection import MovieProjectionOrchestrator, SonarrProjectionOrchestrator
from ..quality import VIDEO_EXTENSIONS
from ..runtime import ReconcileSchedule, RuntimeSyncLoop, get_runtime_status_tracker
from ..sync import RadarrSyncHelper, SonarrSyncHelper
from .common import LOG


class ServiceBootstrapMixin:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.radarr_enabled = config.radarr.enabled
        self.sync_enabled = config.radarr.enabled and config.radarr.sync_enabled
        self.auto_add_unmatched = config.radarr.enabled and config.radarr.auto_add_unmatched
        self.sonarr_enabled = config.sonarr.enabled
        self.sonarr_sync_enabled = config.sonarr.enabled and config.sonarr.sync_enabled
        self.sonarr_auto_add_unmatched = config.sonarr.enabled and config.sonarr.auto_add_unmatched
        self.radarr = RadarrClient(
            config.radarr.url,
            config.radarr.api_key,
            timeout=config.radarr.request_timeout_seconds,
            retry_attempts=config.radarr.request_retry_attempts,
            retry_backoff_seconds=config.radarr.request_retry_backoff_seconds,
            refresh_debounce_seconds=config.radarr.refresh_debounce_seconds,
        )
        self.sonarr = SonarrClient(
            config.sonarr.url,
            config.sonarr.api_key,
            timeout=config.sonarr.request_timeout_seconds,
            retry_attempts=config.sonarr.request_retry_attempts,
            retry_backoff_seconds=config.sonarr.request_retry_backoff_seconds,
            refresh_debounce_seconds=config.sonarr.refresh_debounce_seconds,
        )
        self.radarr_sync = RadarrSyncHelper(
            config=config,
            logger=LOG,
            get_radarr_client=lambda: self.radarr,
        )
        self.sonarr_sync = SonarrSyncHelper(
            config=config,
            logger=LOG,
            get_sonarr_client=lambda: self.sonarr,
        )
        self.movie_root_mappings = self._build_movie_root_mappings(config)
        self.series_root_mappings = self._build_series_root_mappings(config)
        self.series_managed_roots = [managed for managed, _ in self.series_root_mappings]
        self.series_library_roots = self._unique_paths(
            [library for _, library in self.series_root_mappings]
        )
        self.watched_source_roots = self._unique_paths(
            [managed for managed, _ in self.movie_root_mappings] + self.series_managed_roots
        )
        self.watched_target_roots = self._unique_paths(
            [library for _, library in self.movie_root_mappings] + self.series_library_roots
        )
        self.video_exts = set(config.runtime.scan_video_extensions or VIDEO_EXTENSIONS)
        self.scan_exclude_paths = list(config.paths.exclude_paths)
        self.movie_projection = (
            MovieProjectionOrchestrator(
                config=config,
                radarr=self.radarr,
                logger=LOG,
            )
            if self.radarr_enabled
            else None
        )
        self.sonarr_projection = (
            SonarrProjectionOrchestrator(
                config=config,
                sonarr=self.sonarr,
                logger=LOG,
            )
            if self.sonarr_enabled
            else None
        )

        self._debounce_seconds = max(1, config.runtime.debounce_seconds)
        self._polling_fallback_interval_seconds = config.runtime.polling_fallback_interval_seconds
        maintenance_minutes = config.runtime.maintenance_interval_minutes
        root_poll_minutes = config.runtime.arr_root_poll_interval_minutes
        self._maintenance_interval = (
            None if maintenance_minutes <= 0 else max(60, maintenance_minutes * 60)
        )
        self._arr_root_poll_interval = (
            None if root_poll_minutes <= 0 else max(15, root_poll_minutes * 60)
        )
        self._lock = threading.Lock()
        self._sync_hint_logged = False
        self._sonarr_sync_hint_logged = False
        self._next_arr_root_poll_at = 0.0
        self._radarr_missing_managed_roots: set[str] = set()
        self._sonarr_missing_managed_roots: set[str] = set()
        self.runtime_status_tracker = get_runtime_status_tracker()
        self.inventory_snapshot_store = get_inventory_snapshot_store()

    def _build_series_root_mappings(self, config: AppConfig) -> list[tuple[Path, Path]]:
        return [
            (Path(item.nested_root), Path(item.shadow_root))
            for item in config.paths.series_root_mappings
        ]

    def _build_movie_root_mappings(self, config: AppConfig) -> list[tuple[Path, Path]]:
        return [
            (Path(item.managed_root), Path(item.library_root))
            for item in config.paths.movie_root_mappings
        ]

    def _unique_paths(self, paths: list[Path]) -> list[Path]:
        seen: set[Path] = set()
        ordered: list[Path] = []
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            ordered.append(path)
        return ordered

    def run(self, stop_event: threading.Event | None = None) -> None:
        movie_managed_roots = "\n    - ".join(str(root) for root, _ in self.movie_root_mappings)
        movie_library_roots = "\n    - ".join(str(root) for _, root in self.movie_root_mappings)
        series_managed_roots = "\n    - ".join(str(root) for root, _ in self.series_root_mappings)
        series_library_roots = "\n    - ".join(str(root) for _, root in self.series_root_mappings)
        LOG.info("")
        LOG.info("================ LibrariArr Startup ================")
        LOG.info("Startup configuration:")
        LOG.info("  Movie projection paths:")
        LOG.info("    managed_roots:\n    - %s", movie_managed_roots or "-")
        LOG.info("    library_roots:\n    - %s", movie_library_roots or "-")
        LOG.info("  Sonarr projection paths:")
        LOG.info("    managed_roots:\n    - %s", series_managed_roots or "-")
        LOG.info("    library_roots:\n    - %s", series_library_roots or "-")
        LOG.info(
            "  Radarr: enabled=%s sync_enabled=%s auto_add_unmatched=%s",
            self.radarr_enabled,
            self.sync_enabled,
            self.auto_add_unmatched,
        )
        LOG.info(
            "  Sonarr: enabled=%s sync_enabled=%s auto_add_unmatched=%s",
            self.sonarr_enabled,
            self.sonarr_sync_enabled,
            self.sonarr_auto_add_unmatched,
        )
        LOG.info(
            "  Runtime: debounce_seconds=%s maintenance_interval_seconds=%s "
            "arr_root_poll_interval_seconds=%s",
            self._debounce_seconds,
            self._maintenance_interval if self._maintenance_interval is not None else "disabled",
            (
                self._arr_root_poll_interval
                if self._arr_root_poll_interval is not None
                else "disabled"
            ),
        )
        LOG.info("====================================================")
        for managed_root, library_root in self.movie_root_mappings:
            managed_root.mkdir(parents=True, exist_ok=True)
            library_root.mkdir(parents=True, exist_ok=True)
        for managed_root, library_root in self.series_root_mappings:
            managed_root.mkdir(parents=True, exist_ok=True)
            library_root.mkdir(parents=True, exist_ok=True)
        self._run_sync_preflight_checks()
        self._wait_for_arr_readiness()

        def _on_reconcile_complete() -> None:
            from ..web.discovery_cache import get_discovery_warnings_cache
            from ..web.mapped_cache import get_mapped_directories_cache

            get_mapped_directories_cache().request_refresh(self.config, force=True)
            get_discovery_warnings_cache().request_refresh(self.config, force=True)

        runtime_loop = RuntimeSyncLoop(
            nested_roots=self.watched_source_roots,
            shadow_roots=self.watched_target_roots,
            schedule=ReconcileSchedule(
                debounce_seconds=self._debounce_seconds,
                maintenance_interval_seconds=self._maintenance_interval,
            ),
            reconcile=self.reconcile,
            on_reconcile_error=self._log_arr_sync_config_hints,
            logger=LOG,
            poll_reconcile_trigger=self._poll_arr_root_reconcile_trigger,
            status_tracker=self.runtime_status_tracker,
            on_reconcile_complete=_on_reconcile_complete,
            tracked_video_extensions=self.video_exts,
            polling_fallback_interval_seconds=self._polling_fallback_interval_seconds,
        )
        runtime_loop.run(stop_event=stop_event)

    def _wait_for_arr_readiness(self) -> None:
        max_attempts = 5
        delay = 2.0
        for attempt in range(max_attempts):
            radarr_ok = not self.radarr_enabled
            sonarr_ok = not (self.sonarr_enabled and self.sonarr_sync_enabled)
            if self.radarr_enabled:
                try:
                    self.radarr.get_system_status()
                    radarr_ok = True
                except Exception:
                    pass
            if self.sonarr_enabled and self.sonarr_sync_enabled:
                try:
                    self.sonarr.get_system_status()
                    sonarr_ok = True
                except Exception:
                    pass
            if radarr_ok and sonarr_ok:
                LOG.info(
                    "Arr readiness probe passed (attempt %s/%s)",
                    attempt + 1,
                    max_attempts,
                )
                return
            LOG.info(
                "Arr readiness probe waiting: attempt=%s/%s radarr=%s sonarr=%s retry_in=%.0fs",
                attempt + 1,
                max_attempts,
                radarr_ok,
                sonarr_ok,
                delay,
            )
            time.sleep(delay)
            delay = min(delay * 2, 30.0)
        LOG.warning(
            "Arr readiness probe exhausted %s attempts; proceeding anyway",
            max_attempts,
        )
