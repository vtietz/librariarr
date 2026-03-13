from __future__ import annotations

import threading
from pathlib import Path

from ..clients.radarr import RadarrClient
from ..clients.sonarr import SonarrClient
from ..config import AppConfig
from ..quality import VIDEO_EXTENSIONS
from ..runtime import ReconcileSchedule, RuntimeSyncLoop
from ..sync import (
    RadarrSyncHelper,
    ShadowCleanupManager,
    ShadowIngestor,
    ShadowLinkManager,
    SonarrSyncHelper,
)
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
            refresh_debounce_seconds=config.radarr.refresh_debounce_seconds,
        )
        self.sonarr = SonarrClient(
            config.sonarr.url,
            config.sonarr.api_key,
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
        self.root_mappings = self._build_root_mappings(config)
        self.nested_roots = [nested for nested, _ in self.root_mappings]
        self.shadow_roots = self._unique_paths([shadow for _, shadow in self.root_mappings])
        self.shadow_to_nested_roots = self._build_shadow_to_nested_roots(self.root_mappings)
        self._validate_ingest_root_mappings(config.ingest.enabled)
        self.video_exts = set(config.runtime.scan_video_extensions or VIDEO_EXTENSIONS)
        self.link_manager = ShadowLinkManager(self.nested_roots, logger=LOG)
        self.ingestor = ShadowIngestor(
            config=config.ingest,
            video_exts=self.video_exts,
            shadow_roots=self.shadow_roots,
            shadow_to_nested_roots=self.shadow_to_nested_roots,
            logger=LOG,
        )
        self.cleanup_manager = ShadowCleanupManager(
            shadow_roots=self.shadow_roots,
            sync_enabled=self.sync_enabled,
            unmonitor_on_delete=config.cleanup.unmonitor_on_delete,
            delete_from_radarr_on_missing=config.cleanup.delete_from_radarr_on_missing,
            missing_grace_seconds=config.cleanup.missing_grace_seconds,
            get_radarr_client=lambda: self.radarr,
            resolve_movie_for_link_name=self._resolve_movie_for_link_name,
            logger=LOG,
        )
        self.sonarr_cleanup_manager = ShadowCleanupManager(
            shadow_roots=self.shadow_roots,
            sync_enabled=self.sonarr_sync_enabled,
            unmonitor_on_delete=config.cleanup.unmonitor_on_delete,
            delete_from_radarr_on_missing=config.cleanup.delete_from_sonarr_on_missing,
            missing_grace_seconds=config.cleanup.missing_grace_seconds,
            get_radarr_client=lambda: self.sonarr,
            resolve_movie_for_link_name=self._resolve_series_for_link_name,
            logger=LOG,
        )

        self._debounce_seconds = max(1, config.runtime.debounce_seconds)
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
        self._radarr_missing_shadow_roots: set[str] = set()
        self._sonarr_missing_shadow_roots: set[str] = set()
        self._known_movie_folders: dict[Path, Path] | None = None
        self._known_series_folders: dict[Path, Path] | None = None

    def _build_root_mappings(self, config: AppConfig) -> list[tuple[Path, Path]]:
        return [
            (Path(item.nested_root), Path(item.shadow_root)) for item in config.paths.root_mappings
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

    def _build_shadow_to_nested_roots(
        self,
        mappings: list[tuple[Path, Path]],
    ) -> dict[Path, list[Path]]:
        out: dict[Path, list[Path]] = {}
        for nested_root, shadow_root in mappings:
            out.setdefault(shadow_root, [])
            if nested_root not in out[shadow_root]:
                out[shadow_root].append(nested_root)
        return out

    def _validate_ingest_root_mappings(self, ingest_enabled: bool) -> None:
        if not ingest_enabled:
            return

        ambiguous = [
            shadow_root
            for shadow_root, nested_roots in self.shadow_to_nested_roots.items()
            if len(nested_roots) != 1
        ]
        if not ambiguous:
            return

        roots = ", ".join(str(root) for root in sorted(ambiguous))
        raise ValueError(
            "Ingest requires a 1:1 mapping between each shadow root and nested root. "
            f"Ambiguous shadow roots: {roots}. Use paths.root_mappings with unique "
            "shadow_root values when ingest is enabled."
        )

    def run(self, stop_event: threading.Event | None = None) -> None:
        shadow_roots = "\n    - ".join(str(root) for root in self.shadow_roots)
        nested_roots = "\n    - ".join(str(root) for root in self.nested_roots)
        LOG.info("")
        LOG.info("================ LibrariArr Startup ================")
        LOG.info("Startup configuration:")
        LOG.info("  Paths:")
        LOG.info("    shadow_roots:\n    - %s", shadow_roots)
        LOG.info("    nested_roots:\n    - %s", nested_roots)
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
        for shadow_root in self.shadow_roots:
            shadow_root.mkdir(parents=True, exist_ok=True)
        self._run_sync_preflight_checks()
        runtime_loop = RuntimeSyncLoop(
            nested_roots=self.nested_roots,
            shadow_roots=self.shadow_roots,
            schedule=ReconcileSchedule(
                debounce_seconds=self._debounce_seconds,
                maintenance_interval_seconds=self._maintenance_interval,
            ),
            reconcile=self.reconcile,
            on_reconcile_error=self._log_arr_sync_config_hints,
            logger=LOG,
            poll_reconcile_trigger=self._poll_arr_root_reconcile_trigger,
        )
        runtime_loop.run(stop_event=stop_event)
