"""Slim runtime loop: webhook-triggered passes + scheduled drift/consistency/full.

No filesystem watchers. Arr-side changes arrive via webhooks (instant,
debounced) and are reconciled for the named item only when the payload
identifies one. The two things a webhook cannot tell us are covered by polls:
root-folder reassignments by the cheap bucket-drift poll (Radarr publishes no
notification for those), and user-side changes in the managed tree by the
scheduled full pass, which is also the only pass that walks the tree. The
interval consistency pass stays as the safety net for anything a lost webhook
would otherwise leave unreconciled.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from ..config.models import RuntimeConfig
from ..core.engine import SCOPE_CONSISTENCY, SCOPE_FULL, SCOPE_TARGETED

LOG = logging.getLogger(__name__)

# Broader scopes win when triggers overlap inside one debounce window: a
# consistency or full pass already covers whatever the targeted ids would have.
_SCOPE_RANK = {SCOPE_TARGETED: 0, SCOPE_CONSISTENCY: 1, SCOPE_FULL: 2}


@dataclass
class _Pending:
    scope: str
    movie_ids: set[int] = field(default_factory=set)
    series_ids: set[int] = field(default_factory=set)


class RuntimeLoop:
    def __init__(self, service, runtime_config: RuntimeConfig) -> None:
        self.service = service
        self.config = runtime_config
        self._wakeup = threading.Event()
        self._lock = threading.Lock()
        self._pending: _Pending | None = None
        self._pending_since: float | None = None

    # -- triggers (called from webhook handlers / API) -------------------

    def trigger_consistency(self, reason: str = "") -> None:
        self._trigger(SCOPE_CONSISTENCY, reason)

    def trigger_full(self, reason: str = "") -> None:
        self._trigger(SCOPE_FULL, reason)

    def trigger_targeted(
        self,
        reason: str = "",
        *,
        movie_ids: set[int] | list[int] = (),
        series_ids: set[int] | list[int] = (),
    ) -> None:
        """Queue a pass for these Arr ids only. Repeated triggers for the same
        item inside the debounce window collapse into one pass."""
        self._trigger(SCOPE_TARGETED, reason, movie_ids=movie_ids, series_ids=series_ids)

    def _trigger(
        self,
        scope: str,
        reason: str,
        *,
        movie_ids: set[int] | list[int] = (),
        series_ids: set[int] | list[int] = (),
    ) -> None:
        with self._lock:
            if self._pending is None:
                self._pending = _Pending(scope)
            elif _SCOPE_RANK[scope] > _SCOPE_RANK[self._pending.scope]:
                # Widening: the accumulated ids are covered by the broader pass.
                self._pending = _Pending(scope)
            if self._pending.scope == SCOPE_TARGETED:
                self._pending.movie_ids.update(int(i) for i in movie_ids)
                self._pending.series_ids.update(int(i) for i in series_ids)
            if self._pending_since is None:
                self._pending_since = time.monotonic()
        LOG.debug("%s reconcile triggered%s", scope, f" ({reason})" if reason else "")
        self._wakeup.set()

    def _take_pending(self, now: float) -> _Pending | None:
        with self._lock:
            if self._pending_since is None:
                return None
            if now < self._pending_since + self.config.debounce_seconds:
                return None
            pending = self._pending
            self._pending = None
            self._pending_since = None
            return pending

    def _pending_deadline(self) -> float | None:
        with self._lock:
            if self._pending_since is None:
                return None
            return self._pending_since + self.config.debounce_seconds

    # -- loop -------------------------------------------------------------

    def run(self, stop_event: threading.Event) -> None:
        interval = max(30, int(self.config.consistency_interval_seconds))
        full_interval = max(60, int(self.config.full_interval_minutes) * 60)
        drift_configured = int(self.config.bucket_drift_interval_seconds)
        drift_interval = max(30, drift_configured) if drift_configured > 0 else None

        if self.config.startup_scope in (SCOPE_FULL, SCOPE_CONSISTENCY):
            self._safe_reconcile(self.config.startup_scope)
        now = time.monotonic()
        next_consistency = now + interval
        next_full = now + full_interval
        next_drift = now + drift_interval if drift_interval else float("inf")

        while not stop_event.is_set():
            now = time.monotonic()
            deadline = min(
                next_consistency,
                next_full,
                next_drift,
                self._pending_deadline() or float("inf"),
            )
            if now < deadline:
                self._wakeup.wait(timeout=min(deadline - now, 1.0))
                self._wakeup.clear()
                continue

            pending = self._take_pending(now)
            if pending is not None:
                self._safe_reconcile(
                    pending.scope,
                    movie_ids=sorted(pending.movie_ids),
                    series_ids=sorted(pending.series_ids),
                )
                if pending.scope == SCOPE_TARGETED:
                    # A targeted pass verified one item, not the library, so it
                    # must not push the global safety net out: under continuous
                    # webhook traffic that would starve it indefinitely.
                    continue
                scope = pending.scope
            elif now >= next_full:
                self._safe_reconcile(SCOPE_FULL)
                scope = SCOPE_FULL
            elif now >= next_consistency:
                self._safe_reconcile(SCOPE_CONSISTENCY)
                scope = SCOPE_CONSISTENCY
            elif drift_interval is not None and now >= next_drift:
                self._safe_bucket_drift()
                next_drift = time.monotonic() + drift_interval
                continue
            else:
                # No deadline actually came due (a trigger landed between
                # computing the deadline and taking it). Wait rather than
                # spinning on a recomputed deadline.
                self._wakeup.wait(timeout=0.1)
                self._wakeup.clear()
                continue

            now = time.monotonic()
            next_consistency = now + interval
            if scope == SCOPE_FULL:
                next_full = now + full_interval

    def _safe_reconcile(self, scope: str, *, movie_ids=(), series_ids=()) -> None:
        try:
            if scope == SCOPE_TARGETED:
                self.service.reconcile_targeted(
                    radarr_movie_ids=list(movie_ids), sonarr_series_ids=list(series_ids)
                )
            else:
                self.service.reconcile(scope=scope)
        except Exception:  # noqa: BLE001 - the loop must survive any single failure
            LOG.exception("Reconcile failed (scope=%s)", scope)

    def _safe_bucket_drift(self) -> None:
        try:
            self.service.reconcile_bucket_drift()
        except Exception:  # noqa: BLE001 - the loop must survive any single failure
            LOG.exception("Bucket drift reconcile failed")
