"""Slim runtime loop: webhook-triggered consistency passes + scheduled full passes.

No filesystem watchers. Arr-side changes arrive via webhooks (instant, debounced);
user-side changes (manual folder drops/renames) are picked up by the scheduled
full pass, which is also the only pass that walks the managed tree.
"""

from __future__ import annotations

import logging
import threading
import time

from ..config.models import RuntimeConfig
from ..core.engine import SCOPE_CONSISTENCY, SCOPE_FULL

LOG = logging.getLogger(__name__)


class RuntimeLoop:
    def __init__(self, service, runtime_config: RuntimeConfig) -> None:
        self.service = service
        self.config = runtime_config
        self._wakeup = threading.Event()
        self._lock = threading.Lock()
        self._pending_scope: str | None = None
        self._pending_since: float | None = None

    # -- triggers (called from webhook handlers / API) -------------------

    def trigger_consistency(self, reason: str = "") -> None:
        self._trigger(SCOPE_CONSISTENCY, reason)

    def trigger_full(self, reason: str = "") -> None:
        self._trigger(SCOPE_FULL, reason)

    def _trigger(self, scope: str, reason: str) -> None:
        with self._lock:
            if self._pending_scope != SCOPE_FULL:
                self._pending_scope = scope
            if self._pending_since is None:
                self._pending_since = time.monotonic()
        LOG.debug("%s reconcile triggered%s", scope, f" ({reason})" if reason else "")
        self._wakeup.set()

    def _take_pending(self, now: float) -> str | None:
        with self._lock:
            if self._pending_since is None:
                return None
            if now < self._pending_since + self.config.debounce_seconds:
                return None
            scope = self._pending_scope
            self._pending_scope = None
            self._pending_since = None
            return scope

    def _pending_deadline(self) -> float | None:
        with self._lock:
            if self._pending_since is None:
                return None
            return self._pending_since + self.config.debounce_seconds

    # -- loop -------------------------------------------------------------

    def run(self, stop_event: threading.Event) -> None:
        interval = max(30, int(self.config.consistency_interval_seconds))
        full_interval = max(60, int(self.config.full_interval_minutes) * 60)

        if self.config.startup_scope in (SCOPE_FULL, SCOPE_CONSISTENCY):
            self._safe_reconcile(self.config.startup_scope)
        now = time.monotonic()
        next_consistency = now + interval
        next_full = now + full_interval

        while not stop_event.is_set():
            now = time.monotonic()
            deadline = min(
                next_consistency,
                next_full,
                self._pending_deadline() or float("inf"),
            )
            if now < deadline:
                self._wakeup.wait(timeout=min(deadline - now, 1.0))
                self._wakeup.clear()
                continue

            scope = self._take_pending(now)
            if scope is None:
                scope = SCOPE_FULL if now >= next_full else SCOPE_CONSISTENCY
            self._safe_reconcile(scope)
            now = time.monotonic()
            next_consistency = now + interval
            if scope == SCOPE_FULL:
                next_full = now + full_interval

    def _safe_reconcile(self, scope: str) -> None:
        try:
            self.service.reconcile(scope=scope)
        except Exception:  # noqa: BLE001 - the loop must survive any single failure
            LOG.exception("Reconcile failed (scope=%s)", scope)
