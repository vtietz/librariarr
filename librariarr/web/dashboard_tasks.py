from __future__ import annotations

from typing import Any


def build_pending_tasks(
    *,
    runtime_payload: dict[str, Any],
    jobs_summary: dict[str, Any],
    mapped_cache_snapshot: dict[str, Any],
    discovery_cache_snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []

    current_task = runtime_payload.get("current_task")
    if isinstance(current_task, dict) and current_task.get("state") == "running":
        tasks.append(
            {
                "kind": "runtime-reconcile",
                "status": "running",
                "label": "Reconcile cycle",
                "detail": (
                    current_task.get("phase") or current_task.get("trigger_source") or "running"
                ),
            }
        )

    dirty_paths_queued = int(runtime_payload.get("dirty_paths_queued") or 0)
    if dirty_paths_queued > 0:
        tasks.append(
            {
                "kind": "filesystem-debounce",
                "status": "queued",
                "label": "Filesystem debounce queue",
                "detail": f"{dirty_paths_queued} paths waiting for reconcile",
            }
        )

    queued_jobs = int(jobs_summary.get("queued") or 0)
    if queued_jobs > 0:
        tasks.append(
            {
                "kind": "jobs-queued",
                "status": "queued",
                "label": "Background jobs queued",
                "detail": f"{queued_jobs} queued",
            }
        )

    running_jobs = int(jobs_summary.get("running") or 0)
    if running_jobs > 0:
        tasks.append(
            {
                "kind": "jobs-running",
                "status": "running",
                "label": "Background jobs running",
                "detail": f"{running_jobs} running",
            }
        )

    if bool(mapped_cache_snapshot.get("building")):
        tasks.append(
            {
                "kind": "mapped-index",
                "status": "running",
                "label": "Mapped directories index",
                "detail": "Rebuilding in-memory link index",
            }
        )

    discovery_cache_meta = discovery_cache_snapshot.get("cache")
    if isinstance(discovery_cache_meta, dict) and bool(discovery_cache_meta.get("building")):
        tasks.append(
            {
                "kind": "discovery-index",
                "status": "running",
                "label": "Discovery warnings snapshot",
                "detail": "Rebuilding in-memory warning snapshot",
            }
        )

    return tasks
