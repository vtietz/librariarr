from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse


def build_logs_router(
    *,
    get_log_buffer_fn: Callable[[], Any],
    iter_logs_stream_events: Callable[..., Any],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/logs")
    def app_logs(
        tail: int = Query(default=250, ge=10, le=2000),
    ) -> dict[str, Any]:
        buf = get_log_buffer_fn()
        if buf is None:
            return {"tail": tail, "items": []}
        return {"tail": tail, "items": buf.get_entries(tail=tail)}

    @router.get("/api/logs/stream")
    async def app_logs_stream(
        request: Request,
        max_events: int = Query(default=0, ge=0),
    ) -> StreamingResponse:
        buf = get_log_buffer_fn()
        if buf is None:

            async def empty_stream():
                return
                yield

            stream = empty_stream()
        else:
            stream = iter_logs_stream_events(request=request, buf=buf, max_events=max_events)

        return StreamingResponse(
            stream,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router
