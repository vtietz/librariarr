from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Query, Request


def build_maintenance_router(
    *,
    queue_maintenance_reconcile_fn: Callable[..., dict[str, Any]],
    runtime_status: Any,
    mapped_cache: Any,
    discovery_cache: Any,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/maintenance/reconcile")
    def run_maintenance_reconcile(
        request: Request,
        path: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return queue_maintenance_reconcile_fn(
            request=request,
            path=path,
            runtime_status=runtime_status,
            mapped_cache=mapped_cache,
            discovery_cache=discovery_cache,
        )

    return router
