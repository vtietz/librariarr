from __future__ import annotations

from ..runtime.status import RuntimeStatusTracker
from .jobs import JobManager


def configure_runtime_task_callbacks(
    *,
    runtime_status_tracker: RuntimeStatusTracker,
    job_manager: JobManager,
) -> None:
    runtime_status_tracker.configure_task_callbacks(
        on_started=lambda **kwargs: job_manager.begin_external_task(
            kind="runtime-reconcile",
            name="Reconcile Cycle",
            source=str(kwargs.get("trigger_source") or "runtime"),
            detail=str(kwargs.get("phase") or "running"),
            payload=dict(kwargs.get("current_task") or {}),
            task_key="runtime-reconcile",
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
