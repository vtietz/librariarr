from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request


def build_runtime_router(*, runtime_status: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/api/runtime/status")
    def runtime_status_endpoint(request: Request) -> dict[str, Any]:
        supervisor = getattr(request.app.state.web, "runtime_supervisor", None)
        read_model = getattr(request.app.state.web, "dashboard_read_model", None)
        if read_model is not None:
            payload = read_model.snapshot()
            if payload.get("updated_at") is None:
                payload = read_model.refresh_now()
        else:
            payload = runtime_status.snapshot()
        payload["runtime_supervisor_present"] = supervisor is not None
        payload["runtime_supervisor_running"] = (
            bool(supervisor.is_running()) if supervisor is not None else False
        )
        return payload

    return router
