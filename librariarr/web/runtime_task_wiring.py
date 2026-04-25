from __future__ import annotations

from ..runtime.status import RuntimeStatusTracker
from ..service.constants import (
    RECONCILE_TASK_FULL_KEY,
    RECONCILE_TASK_FULL_STARTUP_KEY,
    RECONCILE_TASK_INCREMENTAL_KEY,
)
from .jobs import JobManager


def _task_key_for_runtime_trigger(trigger_source: str) -> str:
    normalized = str(trigger_source).strip().lower()
    if normalized in {"filesystem", "poll"}:
        return RECONCILE_TASK_INCREMENTAL_KEY
    if normalized == "startup":
        return RECONCILE_TASK_FULL_STARTUP_KEY
    return RECONCILE_TASK_FULL_KEY


def _task_name_for_runtime_trigger(trigger_source: str) -> str:
    if str(trigger_source).strip().lower() == "startup":
        return "Startup Full Reconcile"
    return "Reconcile Cycle"


def configure_runtime_task_callbacks(
    *,
    runtime_status_tracker: RuntimeStatusTracker,
    job_manager: JobManager,
) -> None:
    runtime_status_tracker.configure_task_callbacks(
        on_started=lambda **kwargs: job_manager.begin_external_task(
            kind="runtime-reconcile",
            name=_task_name_for_runtime_trigger(str(kwargs.get("trigger_source") or "")),
            source=str(kwargs.get("trigger_source") or "runtime"),
            detail=str(kwargs.get("phase") or "running"),
            payload=dict(kwargs.get("current_task") or {}),
            task_key=_task_key_for_runtime_trigger(str(kwargs.get("trigger_source") or "")),
            history_visible=False,
        ),
        on_updated=lambda **kwargs: job_manager.update_external_task(
            str(kwargs["task_id"]),
            status="running",
            detail=str((kwargs.get("current_task") or {}).get("phase") or "running"),
            payload_updates=dict(kwargs.get("current_task") or {}),
        ),
        on_finished=lambda **kwargs: job_manager.finish_external_task(
            str(kwargs["task_id"]),
            success=bool(kwargs.get("success")),
            detail="Reconcile completed" if kwargs.get("success") else "Reconcile failed",
            error=str(kwargs.get("error")) if kwargs.get("error") is not None else None,
            result=dict(kwargs.get("result") or {}),
        ),
    )
