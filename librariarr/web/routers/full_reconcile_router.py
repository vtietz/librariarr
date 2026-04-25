from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request


def build_full_reconcile_router(
    *,
    queue_full_reconcile_fn: Callable[..., dict[str, Any]],
    runtime_status: Any,
    mapped_cache: Any,
    discovery_cache: Any,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/maintenance/full-reconcile")
    def run_full_reconcile(request: Request) -> dict[str, Any]:
        return queue_full_reconcile_fn(
            request=request,
            runtime_status=runtime_status,
            mapped_cache=mapped_cache,
            discovery_cache=discovery_cache,
        )

    return router
