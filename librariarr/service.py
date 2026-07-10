"""Thin service facade: config + engine + status tracking."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from .config.models import AppConfig
from .core.engine import SCOPE_CONSISTENCY, SCOPE_FULL, ReconcileEngine, default_cache_path
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

    def reconcile(self, *, scope: str = SCOPE_FULL, dry_run: bool = False) -> ReconcileReport:
        """Run one reconcile cycle. Serialized: concurrent calls queue up."""
        with self._reconcile_lock:
            self.status.begin(scope)
            try:
                report = self.engine.run(scope=scope, dry_run=dry_run)
            except Exception as exc:
                self.status.fail(scope, str(exc))
                raise
            self.status.finish(report)
            return report

    def reconcile_consistency(self, *, dry_run: bool = False) -> ReconcileReport:
        return self.reconcile(scope=SCOPE_CONSISTENCY, dry_run=dry_run)

    def run(self, stop_event: threading.Event | None = None) -> None:
        """Run the background loop (blocking). Used by --web and plain daemon mode."""
        from .runtime.loop import RuntimeLoop

        RuntimeLoop(self, self.config.runtime).run(stop_event or threading.Event())
