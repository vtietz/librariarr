from __future__ import annotations

import errno
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from .status import RuntimeStatusTracker


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
    def __init__(self, trigger: Callable[[FileSystemEvent], None]) -> None:
        self.trigger = trigger

    def on_any_event(self, event):  # type: ignore[override]
        self.trigger(event)


class RuntimeSyncLoop:
    _NOISY_EVENT_TYPES = frozenset({"opened", "closed", "closed_no_write"})
    _SHADOW_TRIGGER_EVENT_TYPES = frozenset({"created", "deleted", "moved"})

    def __init__(
        self,
        nested_roots: list[Path],
        shadow_roots: list[Path],
        schedule: ReconcileSchedule,
        reconcile: Callable[[set[Path] | None], bool],
        on_reconcile_error: Callable[[Exception], None],
        logger: logging.Logger,
        poll_reconcile_trigger: Callable[[], bool] | None = None,
        status_tracker: RuntimeStatusTracker | None = None,
        on_reconcile_complete: Callable[[], None] | None = None,
    ) -> None:
        self.nested_roots = nested_roots
        self.shadow_roots = shadow_roots
        self.schedule = schedule
        self.reconcile = reconcile
        self.on_reconcile_error = on_reconcile_error
        self.poll_reconcile_trigger = poll_reconcile_trigger
        self.on_reconcile_complete = on_reconcile_complete
        self.log = logger
        self.status_tracker = status_tracker
        self._dirty_paths: set[Path] = set()
        self._dirty_paths_lock = threading.Lock()
        if self.status_tracker is not None:
            self.status_tracker.set_debounce_seconds(self.schedule.debounce_seconds)

    def run(self, stop_event: threading.Event | None = None) -> None:
        handler = _SyncEventHandler(self.mark_dirty)
        observer, watched_roots, observer_mode = self._start_observer(handler)

        if self.status_tracker is not None:
            self.status_tracker.mark_runtime_running(
                running=True,
                watched_nested_roots=len(self.nested_roots),
                watched_shadow_roots=len(self.shadow_roots),
                watched_roots_total=len(watched_roots),
            )

        if observer_mode == "polling":
            self.log.info("Runtime observer mode: polling")

        try:
            if self._run_reconcile_with_handling("Initial reconcile failed"):
                self.log.info(
                    "Ingest candidates are pending stability; scheduling retry in ~%ss",
                    self.schedule.debounce_seconds,
                )
                self.schedule.mark_event()
            while stop_event is None or not stop_event.is_set():
                poll_triggered = self._poll_reconcile_trigger_safe()
                self._run_due_reconcile_cycle(poll_triggered)
                if stop_event is None:
                    time.sleep(1)
                elif stop_event.wait(1):
                    break
        finally:
            observer.stop()
            observer.join()
            if self.status_tracker is not None:
                self.status_tracker.mark_runtime_running(running=False)

    def _start_observer(
        self,
        handler: _SyncEventHandler,
    ) -> tuple[Observer | PollingObserver, set[Path], str]:
        observer = Observer()
        watched_roots = self._schedule_observer_roots(observer, handler)
        try:
            observer.start()
            return observer, watched_roots, "inotify"
        except OSError as exc:
            if exc.errno != errno.ENOSPC:
                raise

        self.log.warning(
            "Inotify watch limit reached; falling back to polling observer mode. "
            "Filesystem sync remains active but may react slower to changes.",
        )
        polling_observer = PollingObserver()
        watched_roots = self._schedule_observer_roots(polling_observer, handler)
        polling_observer.start()
        return polling_observer, watched_roots, "polling"

    def _schedule_observer_roots(
        self,
        observer: Observer | PollingObserver,
        handler: _SyncEventHandler,
    ) -> set[Path]:
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

        return watched_roots

    def _poll_reconcile_trigger_safe(self) -> bool:
        if self.poll_reconcile_trigger is None:
            return False
        try:
            return self.poll_reconcile_trigger()
        except Exception:
            self.log.exception("Poll-based reconcile trigger failed")
            return False

    def _run_due_reconcile_cycle(self, poll_triggered: bool) -> None:
        should_maintenance, should_event_sync = self.schedule.due()
        if not (should_maintenance or should_event_sync or poll_triggered):
            return

        trigger_source = "maintenance"
        if should_event_sync and not should_maintenance:
            trigger_source = "filesystem"
        elif poll_triggered and not should_maintenance and not should_event_sync:
            trigger_source = "poll"

        reconcile_paths: set[Path] | None = None
        if should_maintenance:
            self.log.info("Running scheduled maintenance reconcile")
            self._clear_dirty_paths()
        if should_event_sync:
            if should_maintenance:
                self.log.info("Running event-triggered reconcile (covered by maintenance)")
            else:
                reconcile_paths = self._consume_dirty_paths()
                self.log.info(
                    "Running event-triggered reconcile (affected_paths=%s)",
                    len(reconcile_paths),
                )
        if poll_triggered and not should_maintenance and not should_event_sync:
            self.log.info("Running poll-triggered reconcile")

        reconcile_mode = "incremental" if reconcile_paths is not None else "full"
        self.log.info(
            "Starting reconcile cycle (mode=%s, trigger=%s)",
            reconcile_mode,
            trigger_source,
        )

        if self.status_tracker is not None:
            self.status_tracker.mark_reconcile_started(trigger_source=trigger_source)
            self.status_tracker.update_reconcile_phase("running")

        ingest_pending = self._run_reconcile_with_handling(
            "Reconcile failed; will retry on next cycle",
            affected_paths=reconcile_paths,
        )
        if ingest_pending:
            self.log.info(
                "Ingest candidates are pending stability; scheduling retry in ~%ss",
                self.schedule.debounce_seconds,
            )
            self.schedule.mark_event()
        else:
            self.schedule.clear_event()

    def mark_dirty(self, event: FileSystemEvent | None = None) -> None:
        if event is not None and not self._should_trigger_for_event(event):
            return

        event_paths: list[Path] = []
        if event is not None:
            event_paths = self._extract_event_paths(event)
            if event_paths:
                with self._dirty_paths_lock:
                    self._dirty_paths.update(event_paths)

        if self.schedule.last_event == 0.0:
            self.log.info(
                "Filesystem change detected; reconciling in ~%ss after debounce",
                self.schedule.debounce_seconds,
            )
        self.schedule.mark_event()
        if self.status_tracker is not None:
            with self._dirty_paths_lock:
                dirty_count = len(self._dirty_paths)
            self.status_tracker.update_dirty_paths_queue(
                queued=dirty_count,
                last_event_at=self.schedule.last_event,
            )

    def _consume_dirty_paths(self) -> set[Path]:
        with self._dirty_paths_lock:
            dirty_paths = set(self._dirty_paths)
            self._dirty_paths.clear()
        if self.status_tracker is not None:
            self.status_tracker.update_dirty_paths_queue(queued=0, last_event_at=None)
        return dirty_paths

    def _clear_dirty_paths(self) -> None:
        with self._dirty_paths_lock:
            self._dirty_paths.clear()
        if self.status_tracker is not None:
            self.status_tracker.update_dirty_paths_queue(queued=0, last_event_at=None)

    def _should_trigger_for_event(self, event: FileSystemEvent) -> bool:
        if event.event_type in self._NOISY_EVENT_TYPES:
            return False

        # Recursive watches generate frequent directory metadata updates during scans.
        # create/delete/move still produce their own concrete events.
        if event.is_directory and event.event_type == "modified":
            return False

        event_paths = self._extract_event_paths(event)
        if event_paths and self._is_shadow_event(event_paths):
            if event.event_type not in self._SHADOW_TRIGGER_EVENT_TYPES:
                return False
            return self._is_shadow_top_level_event(event_paths)

        return True

    def _extract_event_paths(self, event: FileSystemEvent) -> list[Path]:
        paths: list[Path] = []
        for attr in ("src_path", "dest_path"):
            raw = getattr(event, attr, None)
            if not isinstance(raw, str) or not raw.strip():
                continue
            paths.append(Path(raw))
        return paths

    def _is_shadow_event(self, paths: list[Path]) -> bool:
        for path in paths:
            for root in self.shadow_roots:
                try:
                    path.relative_to(root)
                    return True
                except ValueError:
                    continue
        return False

    def _is_shadow_top_level_event(self, paths: list[Path]) -> bool:
        for path in paths:
            for root in self.shadow_roots:
                try:
                    relative = path.relative_to(root)
                except ValueError:
                    continue

                if len(relative.parts) == 1:
                    return True
        return False

    def _run_reconcile_with_handling(
        self,
        error_log_message: str,
        affected_paths: set[Path] | None = None,
    ) -> bool:
        # Preserve existing semantics: sync time updates when a reconcile attempt starts.
        self.schedule.mark_sync()
        try:
            ingest_pending = self.reconcile(affected_paths)
            if self.on_reconcile_complete is not None:
                try:
                    self.on_reconcile_complete()
                except Exception:
                    self.log.debug("on_reconcile_complete callback failed", exc_info=True)
            if self.status_tracker is not None:
                self.status_tracker.mark_reconcile_finished(
                    success=True,
                    ingest_pending=ingest_pending,
                )
            return ingest_pending
        except Exception as exc:
            self.on_reconcile_error(exc)
            if isinstance(exc, requests.RequestException):
                self.log.warning(
                    "%s: %s (%s)",
                    error_log_message,
                    exc,
                    type(exc).__name__,
                )
            else:
                self.log.exception(error_log_message)
            if self.status_tracker is not None:
                self.status_tracker.mark_reconcile_finished(
                    success=False,
                    ingest_pending=False,
                    error=str(exc),
                )
            return False
