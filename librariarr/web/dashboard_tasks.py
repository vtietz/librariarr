from __future__ import annotations

import time
from typing import Any


def build_pending_tasks(
    *,
    runtime_payload: dict[str, Any],
    jobs_summary: dict[str, Any],
    mapped_cache_snapshot: dict[str, Any],
    discovery_cache_snapshot: dict[str, Any],
    active_jobs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    now = time.time()
    tasks: list[dict[str, Any]] = []

    current_task = runtime_payload.get("current_task")
    if isinstance(current_task, dict) and current_task.get("state") == "running":
        started_at = current_task.get("started_at")
        duration_seconds = None
        if isinstance(started_at, int | float):
            duration_seconds = round(max(0.0, now - float(started_at)), 1)
        tasks.append(
            {
                "id": "runtime-reconcile",
                "name": "Reconcile Cycle",
                "status": "running",
                "source": str(current_task.get("trigger_source") or "runtime"),
                "detail": str(
                    current_task.get("phase") or current_task.get("trigger_source") or "running"
                ),
                "queued_at": current_task.get("started_at"),
                "started_at": current_task.get("started_at"),
                "duration_seconds": duration_seconds,
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
            }
        )

    for job in active_jobs:
        status = str(job.get("status") or "queued")
        if status not in {"queued", "running"}:
            continue
        queued_at = job.get("queued_at")
        started_at = job.get("started_at")
        duration_seconds = None
        if isinstance(started_at, int | float):
            duration_seconds = round(max(0.0, now - float(started_at)), 1)
        tasks.append(
            {
                "id": str(job.get("job_id") or "job"),
                "name": str(job.get("kind") or "Background Job"),
                "status": status,
                "source": "job-manager",
                "detail": str(job.get("error") or "active"),
                "queued_at": queued_at if isinstance(queued_at, int | float) else None,
                "started_at": started_at if isinstance(started_at, int | float) else None,
                "duration_seconds": duration_seconds,
            }
        )

    has_concrete_job_tasks = any(item.get("source") == "job-manager" for item in tasks)
    if not has_concrete_job_tasks:
        queued_jobs = int(jobs_summary.get("queued") or 0)
        if queued_jobs > 0:
            tasks.append(
                {
                    "id": "jobs-queued",
                    "name": "Job Backlog",
                    "status": "queued",
                    "source": "job-manager",
                    "detail": f"{queued_jobs} queued",
                    "queued_at": now,
                    "started_at": None,
                    "duration_seconds": None,
                }
            )

        running_jobs = int(jobs_summary.get("running") or 0)
        if running_jobs > 0:
            tasks.append(
                {
                    "id": "jobs-running",
                    "name": "Job Workers",
                    "status": "running",
                    "source": "job-manager",
                    "detail": f"{running_jobs} running",
                    "queued_at": None,
                    "started_at": now,
                    "duration_seconds": None,
                }
            )

    if bool(mapped_cache_snapshot.get("building")):
        tasks.append(
            {
                "id": "mapped-index",
                "name": "Mapped Index Rebuild",
                "status": "running",
                "source": "cache",
                "detail": "Rebuilding in-memory link index",
                "queued_at": None,
                "started_at": now,
                "duration_seconds": None,
            }
        )

    discovery_cache_meta = discovery_cache_snapshot.get("cache")
    if isinstance(discovery_cache_meta, dict) and bool(discovery_cache_meta.get("building")):
        tasks.append(
            {
                "id": "discovery-index",
                "name": "Discovery Snapshot Rebuild",
                "status": "running",
                "source": "cache",
                "detail": "Rebuilding in-memory warning snapshot",
                "queued_at": None,
                "started_at": now,
                "duration_seconds": None,
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
