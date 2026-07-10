"""Thread-safe runtime status for the web API."""

from __future__ import annotations

import threading
import time
from typing import Any

from .model import ReconcileReport

_MAX_HISTORY = 20


class StatusTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running_scope: str | None = None
        self._started_at: float | None = None
        self._last_report: dict[str, Any] | None = None
        self._last_finished_at: float | None = None
        self._last_error: str | None = None
        self._history: list[dict[str, Any]] = []

    def begin(self, scope: str) -> None:
        with self._lock:
            self._running_scope = scope
            self._started_at = time.time()

    def finish(self, report: ReconcileReport) -> None:
        with self._lock:
            self._running_scope = None
            self._last_finished_at = time.time()
            self._last_error = report.errors[0] if report.errors else None
            payload = report.to_dict()
            self._last_report = payload
            self._history.insert(
                0,
                {
                    "finished_at": self._last_finished_at,
                    "scope": payload["scope"],
                    "dry_run": payload["dry_run"],
                    "items_seen": payload["items_seen"],
                    "items_changed": payload["items_changed"],
                    "unmatched": len(payload["unmatched"]),
                    "warnings": len(payload["warnings"]),
                    "errors": len(payload["errors"]),
                    "duration_seconds": payload["duration_seconds"],
                },
            )
            del self._history[_MAX_HISTORY:]

    def fail(self, scope: str, error: str) -> None:
        with self._lock:
            self._running_scope = None
            self._last_finished_at = time.time()
            self._last_error = error
            self._history.insert(
                0,
                {"finished_at": self._last_finished_at, "scope": scope, "error": error},
            )
            del self._history[_MAX_HISTORY:]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._running_scope is not None,
                "running_scope": self._running_scope,
                "started_at": self._started_at,
                "last_finished_at": self._last_finished_at,
                "last_error": self._last_error,
                "last_report": self._last_report,
                "history": list(self._history),
            }


_TRACKER = StatusTracker()


def get_status_tracker() -> StatusTracker:
    return _TRACKER
