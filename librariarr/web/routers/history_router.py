from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from ..history_events import clear_history_events


def build_history_router(*, state_store_or_http_fn: Callable[[Request], Any]) -> APIRouter:
    router = APIRouter()

    @router.get("/api/history")
    def history_list(
        request: Request,
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> dict[str, Any]:
        state_store = state_store_or_http_fn(request)
        items = state_store.load_history()
        return {
            "items": items[:limit],
            "total": len(items),
            "truncated": len(items) > limit,
        }

    @router.post("/api/history/clear")
    def history_clear(request: Request) -> dict[str, Any]:
        state_store = state_store_or_http_fn(request)
        removed = clear_history_events(state_store)
        return {"ok": True, "removed": removed}

    @router.delete("/api/history/{event_id}")
    def history_delete(event_id: str, request: Request) -> dict[str, Any]:
        state_store = state_store_or_http_fn(request)
        items = state_store.load_history()
        kept = [item for item in items if str(item.get("id")) != event_id]
        if len(kept) == len(items):
            raise HTTPException(status_code=404, detail="History event not found")
        state_store.save_history(kept)
        return {"ok": True, "event_id": event_id}

    return router
