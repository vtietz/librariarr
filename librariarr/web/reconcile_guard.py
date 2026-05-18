from __future__ import annotations

import time
from typing import Any

_RECONCILE_KINDS = frozenset(
    {
        "reconcile-manual",
        "reconcile-manual-scoped",
        "reconcile-full",
        "runtime-reconcile",
    }
)


def _runtime_reconcile_running(runtime_status: Any) -> dict[str, str] | None:
    snapshot = runtime_status.snapshot()
    current_task = snapshot.get("current_task")
    if not isinstance(current_task, dict):
        return None
    if str(current_task.get("state") or "") != "running":
        return None
    return {
        "source": str(current_task.get("trigger_source") or "runtime"),
        "detail": str(current_task.get("phase") or "reconcile"),
    }


def _queued_or_running_reconcile(manager: Any) -> dict[str, str] | None:
    active_tasks = manager.list_active_tasks(limit=50)
    for task in active_tasks:
        if str(task.get("kind") or "") not in _RECONCILE_KINDS:
            continue
        return {
            "task_id": str(task.get("job_id") or ""),
            "task_key": str(task.get("task_key") or ""),
            "source": str(task.get("source") or "job-manager"),
            "detail": str(task.get("name") or task.get("kind") or "reconcile"),
        }
    return None


def _active_reconcile(
    *,
    manager: Any,
    runtime_status: Any,
    ignore_job_id: str | None = None,
    ignore_task_key: str | None = None,
) -> dict[str, str] | None:
    runtime_active = _runtime_reconcile_running(runtime_status)
    if runtime_active is not None:
        runtime_task = runtime_status.snapshot().get("current_task")
        runtime_task_id = ""
        if isinstance(runtime_task, dict):
            runtime_task_id = str(runtime_task.get("task_id") or "")
        if ignore_job_id and runtime_task_id and runtime_task_id == ignore_job_id:
            runtime_active = None
        else:
            return runtime_active

    active = _queued_or_running_reconcile(manager)
    if active is None:
        return None
    if ignore_job_id and active.get("task_id") == ignore_job_id:
        return None
    if ignore_task_key and active.get("task_key") == ignore_task_key:
        return None
    return active


def wait_for_reconcile_slot(
    *,
    manager: Any,
    runtime_status: Any,
    ignore_job_id: str | None = None,
    ignore_task_key: str | None = None,
    timeout_seconds: float = 6 * 60 * 60,
    poll_seconds: float = 0.25,
) -> None:
    started = time.time()
    while True:
        active = _active_reconcile(
            manager=manager,
            runtime_status=runtime_status,
            ignore_job_id=ignore_job_id,
            ignore_task_key=ignore_task_key,
        )
        if active is None:
            return
        if (time.time() - started) >= max(1.0, float(timeout_seconds)):
            raise TimeoutError(
                "Timed out while waiting for active reconcile to finish "
                f"({active['source']}: {active['detail']})."
            )
        time.sleep(max(0.05, float(poll_seconds)))
