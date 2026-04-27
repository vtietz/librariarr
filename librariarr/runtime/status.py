from __future__ import annotations

import threading
import time
from collections.abc import Callable
from copy import deepcopy
from typing import Any


class RuntimeStatusTracker:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._task_start_callback: Callable[..., str | None] | None = None
        self._task_update_callback: Callable[..., None] | None = None
        self._task_finish_callback: Callable[..., None] | None = None
        self._current_task_id: str | None = None
        self._state: dict[str, Any] = {
            "runtime_running": False,
            "watched_nested_roots": 0,
            "watched_shadow_roots": 0,
            "watched_roots_total": 0,
            "debounce_seconds": 0,
            "dirty_paths_queued": 0,
            "next_event_reconcile_due_at": None,
            "current_task": {
                "state": "idle",
                "phase": None,
                "trigger_source": None,
                "started_at": None,
                "updated_at": None,
                "error": None,
                "task_id": None,
            },
            "last_reconcile": None,
            "last_full_reconcile": None,
            "library_root_stats": [],
            "updated_at": None,
        }

    def configure_task_callbacks(
        self,
        *,
        on_started: Callable[..., str | None] | None = None,
        on_updated: Callable[..., None] | None = None,
        on_finished: Callable[..., None] | None = None,
    ) -> None:
        with self._lock:
            self._task_start_callback = on_started
            self._task_update_callback = on_updated
            self._task_finish_callback = on_finished

    def mark_runtime_running(
        self,
        *,
        running: bool,
        watched_nested_roots: int = 0,
        watched_shadow_roots: int = 0,
        watched_roots_total: int = 0,
    ) -> None:
        with self._lock:
            self._state["runtime_running"] = running
            if running:
                self._state["watched_nested_roots"] = watched_nested_roots
                self._state["watched_shadow_roots"] = watched_shadow_roots
                self._state["watched_roots_total"] = watched_roots_total
            self._touch_locked()

    def set_debounce_seconds(self, debounce_seconds: int) -> None:
        with self._lock:
            self._state["debounce_seconds"] = max(0, int(debounce_seconds))
            self._touch_locked()

    def update_dirty_paths_queue(self, *, queued: int, last_event_at: float | None) -> None:
        with self._lock:
            queued = max(0, int(queued))
            self._state["dirty_paths_queued"] = queued
            debounce_seconds = int(self._state.get("debounce_seconds") or 0)
            if queued > 0 and last_event_at is not None and debounce_seconds > 0:
                self._state["next_event_reconcile_due_at"] = last_event_at + debounce_seconds
            else:
                self._state["next_event_reconcile_due_at"] = None
            self._touch_locked()

    def mark_reconcile_started(
        self,
        *,
        trigger_source: str,
        phase: str = "reconcile",
        task_id: str | None = None,
    ) -> None:
        with self._lock:
            now = time.time()
            callback = self._task_start_callback
            self._state["current_task"] = {
                "state": "running",
                "phase": phase,
                "trigger_source": trigger_source,
                "started_at": now,
                "updated_at": now,
                "error": None,
                "task_id": task_id,
            }
            current_payload = deepcopy(self._state["current_task"])
            self._current_task_id = task_id
            self._touch_locked()

        if callback is not None:
            resolved_task_id = callback(
                task_id=task_id,
                trigger_source=trigger_source,
                phase=phase,
                current_task=current_payload,
            )
            if resolved_task_id:
                with self._lock:
                    self._current_task_id = resolved_task_id
                    current_task = self._state.get("current_task")
                    if isinstance(current_task, dict):
                        current_task["task_id"] = resolved_task_id
                        current_task["updated_at"] = time.time()
                        self._touch_locked()

    def update_reconcile_phase(self, phase: str) -> None:
        with self._lock:
            current_task = self._state.get("current_task")
            if not isinstance(current_task, dict):
                return
            current_task["phase"] = phase
            current_task["updated_at"] = time.time()
            task_id = self._current_task_id
            current_payload = deepcopy(current_task)
            self._touch_locked()

        if self._task_update_callback is not None and task_id is not None:
            self._task_update_callback(task_id=task_id, current_task=current_payload)

    def update_active_reconcile_metrics(self, metrics: dict[str, Any]) -> None:
        with self._lock:
            current_task = self._state.get("current_task")
            if not isinstance(current_task, dict):
                return
            current_task.update(metrics)
            current_task["updated_at"] = time.time()
            task_id = self._current_task_id
            current_payload = deepcopy(current_task)
            self._touch_locked()

        if self._task_update_callback is not None and task_id is not None:
            self._task_update_callback(task_id=task_id, current_task=current_payload)

    def update_library_root_stats(self, per_root: list[dict[str, Any]]) -> None:
        with self._lock:
            now = time.time()
            existing_by_key = {
                str(r.get("library_root", "")): r
                for r in self._state.get("library_root_stats") or []
            }
            for entry in per_root:
                key = str(entry.get("library_root", ""))
                if key:
                    entry["updated_at"] = now
                    existing_by_key[key] = entry
            self._state["library_root_stats"] = sorted(
                existing_by_key.values(), key=lambda r: str(r.get("library_root", ""))
            )
            self._touch_locked()

    def mark_reconcile_finished(
        self,
        *,
        success: bool,
        followup_pending: bool = False,
        error: str | None = None,
    ) -> None:
        with self._lock:
            now = time.time()
            current_task = self._state.get("current_task")
            if not isinstance(current_task, dict):
                current_task = {}
            task_id = self._current_task_id

            started_at = current_task.get("started_at")
            duration_seconds: float | None = None
            if isinstance(started_at, int | float):
                duration_seconds = round(max(0.0, now - float(started_at)), 2)

            summary: dict[str, Any] = {
                "state": "ok" if success else "error",
                "trigger_source": current_task.get("trigger_source"),
                "phase": current_task.get("phase"),
                "started_at": started_at,
                "finished_at": now,
                "duration_seconds": duration_seconds,
                "followup_pending": bool(followup_pending),
                "error": error,
                "task_id": task_id,
            }
            for key, value in current_task.items():
                if key in summary:
                    continue
                summary[key] = value

            self._state["last_reconcile"] = summary
            if success and isinstance(summary.get("full_reconcile_stats"), dict):
                self._state["last_full_reconcile"] = deepcopy(summary)
            self._state["current_task"] = {
                "state": "idle" if success else "error",
                "phase": None,
                "trigger_source": None,
                "started_at": None,
                "updated_at": now,
                "error": error,
                "task_id": None,
            }
            finished_payload = deepcopy(summary)
            self._current_task_id = None
            self._touch_locked()

        if self._task_finish_callback is not None and task_id is not None:
            self._task_finish_callback(
                task_id=task_id,
                success=success,
                error=error,
                result=finished_payload,
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            payload = deepcopy(self._state)

        now = time.time()
        due_at = payload.get("next_event_reconcile_due_at")
        if isinstance(due_at, int | float):
            payload["next_event_reconcile_in_seconds"] = round(max(0.0, due_at - now), 1)
        else:
            payload["next_event_reconcile_in_seconds"] = None

        return payload

    def _touch_locked(self) -> None:
        self._state["updated_at"] = time.time()


_RUNTIME_STATUS_TRACKER = RuntimeStatusTracker()


def get_runtime_status_tracker() -> RuntimeStatusTracker:
    return _RUNTIME_STATUS_TRACKER
