from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


@dataclass
class ReconcileSchedule:
    debounce_seconds: int
    maintenance_interval_seconds: int | None
    last_event: float = 0.0
    last_sync: float = 0.0

    def mark_event(self, now: float | None = None) -> None:
        self.last_event = time.time() if now is None else now

    def clear_event(self) -> None:
        self.last_event = 0.0

    def mark_sync(self, now: float | None = None) -> None:
        self.last_sync = time.time() if now is None else now

    def due(self, now: float | None = None) -> tuple[bool, bool]:
        current = time.time() if now is None else now
        maintenance_due = self.maintenance_interval_seconds is not None and (
            (current - self.last_sync) >= self.maintenance_interval_seconds
        )
        event_due = self.last_event and ((current - self.last_event) >= self.debounce_seconds)
        return maintenance_due, bool(event_due)


class _SyncEventHandler(FileSystemEventHandler):
    def __init__(self, trigger: callable) -> None:
        self.trigger = trigger

    def on_any_event(self, event):  # type: ignore[override]
        self.trigger()


class RuntimeSyncLoop:
    def __init__(
        self,
        nested_roots: list[Path],
        shadow_roots: list[Path],
        schedule: ReconcileSchedule,
        reconcile: callable,
        on_reconcile_error: callable,
        logger: logging.Logger,
    ) -> None:
        self.nested_roots = nested_roots
        self.shadow_roots = shadow_roots
        self.schedule = schedule
        self.reconcile = reconcile
        self.on_reconcile_error = on_reconcile_error
        self.log = logger

    def run(self) -> None:
        observer = Observer()
        handler = _SyncEventHandler(self.mark_dirty)
        watched_roots: set[Path] = set()

        for root in self.nested_roots:
            root.mkdir(parents=True, exist_ok=True)
            if root not in watched_roots:
                observer.schedule(handler, str(root), recursive=True)
                self.log.info("Watching nested root: %s", root)
                watched_roots.add(root)

        for root in self.shadow_roots:
            root.mkdir(parents=True, exist_ok=True)
            if root not in watched_roots:
                observer.schedule(handler, str(root), recursive=True)
                self.log.info("Watching shadow root: %s", root)
                watched_roots.add(root)

        observer.start()
        try:
            self._run_reconcile_with_handling("Initial reconcile failed")
            while True:
                should_maintenance, should_event_sync = self.schedule.due()
                if should_maintenance or should_event_sync:
                    if should_maintenance:
                        self.log.info("Running scheduled maintenance reconcile")
                    if should_event_sync:
                        self.log.info("Running event-triggered reconcile")
                    self._run_reconcile_with_handling("Reconcile failed; will retry on next cycle")
                    self.schedule.clear_event()
                time.sleep(1)
        finally:
            observer.stop()
            observer.join()

    def mark_dirty(self) -> None:
        if self.schedule.last_event == 0.0:
            self.log.info(
                "Filesystem change detected; reconciling in ~%ss after debounce",
                self.schedule.debounce_seconds,
            )
        self.schedule.mark_event()

    def _run_reconcile_with_handling(self, error_log_message: str) -> None:
        # Preserve existing semantics: sync time updates when a reconcile attempt starts.
        self.schedule.mark_sync()
        try:
            self.reconcile()
        except Exception as exc:
            self.on_reconcile_error(exc)
            self.log.exception(error_log_message)
