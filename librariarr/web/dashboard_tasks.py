from __future__ import annotations

import time
from typing import Any


def build_pending_tasks(
    *,
    runtime_payload: dict[str, Any],
    authoritative_tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    now = time.time()
    tasks: list[dict[str, Any]] = []

    runtime_task_active = any(
        str(task.get("kind") or "") == "runtime-reconcile"
        and str(task.get("status") or "") == "running"
        for task in authoritative_tasks
    )

    for task in authoritative_tasks:
        status = str(task.get("status") or "queued")
        if status not in {"queued", "running"}:
            continue
        kind = str(task.get("kind") or "")
        if runtime_task_active and kind == "reconcile-manual" and status == "running":
            continue
        queued_at = task.get("queued_at")
        started_at = task.get("started_at")
        duration_seconds = None
        if isinstance(started_at, int | float):
            duration_seconds = round(max(0.0, now - float(started_at)), 1)
        tasks.append(
            {
                "id": str(task.get("job_id") or task.get("id") or kind or "task"),
                "name": str(task.get("name") or kind or "Task"),
                "status": status,
                "source": str(task.get("source") or "task-manager"),
                "detail": str(task.get("detail") or status),
                "queued_at": queued_at if isinstance(queued_at, int | float) else None,
                "started_at": started_at if isinstance(started_at, int | float) else None,
                "duration_seconds": duration_seconds,
                "authoritative": bool(task.get("authoritative", False)),
            }
        )

    dirty_paths_queued = int(runtime_payload.get("dirty_paths_queued") or 0)
    if dirty_paths_queued > 0:
        next_due = runtime_payload.get("next_event_reconcile_due_at")
        tasks.append(
            {
                "id": "filesystem-debounce",
                "name": "Filesystem Debounce",
                "status": "queued",
                "source": "filesystem",
                "detail": f"{dirty_paths_queued} paths waiting for reconcile",
                "queued_at": now,
                "started_at": None,
                "duration_seconds": None,
                "next_run_at": next_due if isinstance(next_due, int | float) else None,
                "authoritative": False,
            }
        )

    tasks.sort(
        key=lambda item: (
            0 if item.get("status") == "running" else 1,
            0 if item.get("status") == "queued" else 1,
            str(item.get("name") or ""),
        )
    )
    return tasks
