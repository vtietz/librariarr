from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

_LIVE_RUNTIME_FIELDS = (
    "runtime_running",
    "watched_nested_roots",
    "watched_shadow_roots",
    "watched_roots_total",
    "debounce_seconds",
    "dirty_paths_queued",
    "next_event_reconcile_due_at",
    "next_event_reconcile_in_seconds",
    "current_task",
    "last_reconcile",
    "last_full_reconcile",
)


def build_runtime_router(*, runtime_status: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/api/runtime/status")
    def runtime_status_endpoint(request: Request) -> dict[str, Any]:
        supervisor = getattr(request.app.state.web, "runtime_supervisor", None)
        live_payload = runtime_status.snapshot()
        read_model = getattr(request.app.state.web, "dashboard_read_model", None)
        if read_model is not None:
            payload = read_model.snapshot()
            if payload.get("updated_at") is None:
                payload = read_model.refresh_now()
            # Keep expensive read-model aggregates, but always surface live runtime task state.
            for field in _LIVE_RUNTIME_FIELDS:
                payload[field] = live_payload.get(field)
        else:
            payload = live_payload
        payload["runtime_supervisor_present"] = supervisor is not None
        payload["runtime_supervisor_running"] = (
            bool(supervisor.is_running()) if supervisor is not None else False
        )
        return payload

    return router
