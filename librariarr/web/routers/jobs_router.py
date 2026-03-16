from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request


def build_jobs_router(*, job_manager_or_http_fn: Callable[[Request], Any]) -> APIRouter:
    router = APIRouter()

    @router.get("/api/jobs/summary")
    def jobs_summary(request: Request) -> dict[str, Any]:
        manager = job_manager_or_http_fn(request)
        return manager.summary()

    @router.get("/api/jobs")
    def jobs_list(
        request: Request,
        limit: int = Query(default=20, ge=1, le=200),
        status: str | None = Query(default=None),
    ) -> dict[str, Any]:
        manager = job_manager_or_http_fn(request)
        items = manager.list(limit=limit, status=status)
        return {"items": items}

    @router.get("/api/jobs/{job_id}")
    def jobs_get(job_id: str, request: Request) -> dict[str, Any]:
        manager = job_manager_or_http_fn(request)
        item = manager.get(job_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return item

    @router.post("/api/jobs/{job_id}/cancel")
    def jobs_cancel(job_id: str, request: Request) -> dict[str, Any]:
        manager = job_manager_or_http_fn(request)
        result = manager.cancel(job_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return result

    return router
