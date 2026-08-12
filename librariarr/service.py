"""Thin service facade: config + engine + status tracking."""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from pathlib import Path

from .config.models import AppConfig
from .core.engine import (
    SCOPE_CONSISTENCY,
    SCOPE_FULL,
    SCOPE_TARGETED,
    ReconcileEngine,
    default_cache_path,
)
from .core.model import ReconcileReport
from .core.status import get_status_tracker

LOG = logging.getLogger(__name__)


class LibrariArrService:
    def __init__(
        self,
        config: AppConfig,
        *,
        config_path: str | Path | None = None,
        engine: ReconcileEngine | None = None,
    ) -> None:
        self.config = config
        self.engine = engine or ReconcileEngine(config, cache_path=default_cache_path(config_path))
        self.status = get_status_tracker()
        self._reconcile_lock = threading.Lock()

    def reconcile(
        self,
        *,
        scope: str = SCOPE_FULL,
        dry_run: bool = False,
        radarr_movie_ids: Sequence[int] | None = None,
        sonarr_series_ids: Sequence[int] | None = None,
    ) -> ReconcileReport:
        """Run one reconcile cycle. Serialized: concurrent calls queue up.

        The same lock covers every scope, so a targeted pass can never mutate
        while a full or consistency pass is running.
        """
        with self._reconcile_lock:
            self.status.begin(scope)
            try:
                report = self.engine.run(
                    scope=scope,
                    dry_run=dry_run,
                    progress=self.status.progress,
                    radarr_movie_ids=radarr_movie_ids,
                    sonarr_series_ids=sonarr_series_ids,
                )
            except Exception as exc:
                self.status.fail(scope, str(exc))
                raise
            self.status.finish(report)
            return report

    def reconcile_targeted(
        self,
        *,
        radarr_movie_ids: Sequence[int] | None = None,
        sonarr_series_ids: Sequence[int] | None = None,
        dry_run: bool = False,
    ) -> ReconcileReport:
        return self.reconcile(
            scope=SCOPE_TARGETED,
            dry_run=dry_run,
            radarr_movie_ids=radarr_movie_ids,
            sonarr_series_ids=sonarr_series_ids,
        )

    def list_bucket_drift(self) -> list[dict]:
        """Read-only; safe to call without the reconcile lock."""
        return self.engine.list_bucket_drift()

    def reconcile_bucket_drift(self, *, dry_run: bool = False) -> ReconcileReport | None:
        """Poll for pending root-folder reassignments and reconcile just those.

        Returns None when nothing drifted — the common case, and the reason this
        is cheap enough to run on a short interval: the detection pass does no
        filesystem walk and the reconcile only ever touches drifted items.
        """
        drift = self.engine.list_bucket_drift()
        movie_ids = [entry["id"] for entry in drift if entry["kind"] == "movie"]
        series_ids = [entry["id"] for entry in drift if entry["kind"] == "series"]
        if not movie_ids and not series_ids:
            return None
        LOG.info(
            "Bucket drift detected: movies=%d series=%d; running targeted reconcile",
            len(movie_ids),
            len(series_ids),
        )
        return self.reconcile_targeted(
            radarr_movie_ids=movie_ids, sonarr_series_ids=series_ids, dry_run=dry_run
        )

    def manual_add(self, path: str) -> dict:
        """Add one managed folder to the matching Arr, serialized with reconciles."""
        with self._reconcile_lock:
            return self.engine.manual_add(path)

    def list_path_differences(self) -> list[dict]:
        """Read-only; safe to call without the reconcile lock."""
        return self.engine.list_path_differences()

    def reconcile_consistency(self, *, dry_run: bool = False) -> ReconcileReport:
        return self.reconcile(scope=SCOPE_CONSISTENCY, dry_run=dry_run)

    def run(self, stop_event: threading.Event | None = None) -> None:
        """Run the background loop (blocking). Used by --web and plain daemon mode."""
        from .runtime.loop import RuntimeLoop

        RuntimeLoop(self, self.config.runtime).run(stop_event or threading.Event())
