from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse


def build_fs_router(  # noqa: C901
    *,
    load_config_or_http_fn: Callable[[Path], Any],
    read_config_path_fn: Callable[[Request], Path],
    job_manager_or_http_fn: Callable[[Request], Any],
    mapped_cache: Any,
    discovery_cache: Any,
    shadow_roots_fn: Callable[[Any], list[Path]],
    enrich_mapped_directories_with_radarr_state_fn: Callable[..., list[dict[str, Any]]],
    apply_path_mapping_outcomes_fn: Callable[..., list[dict[str, Any]]],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/fs/mapped-directories")
    def mapped_directories(
        request: Request,
        search: str = Query(default=""),
        shadow_root: str | None = Query(default=None),
        limit: int = Query(default=500, ge=1, le=5000),
        include_arr_state: bool = Query(default=False),
        arr_virtual_path: Annotated[list[str] | None, Query()] = None,
    ) -> dict[str, Any]:
        config = load_config_or_http_fn(read_config_path_fn(request))
        all_roots = shadow_roots_fn(config)

        snapshot = mapped_cache.snapshot()

        if shadow_root is None:
            selected_roots = {str(root) for root in all_roots}
        else:
            selected_roots = {str(root) for root in all_roots if str(root) == shadow_root}
            if not selected_roots:
                raise HTTPException(status_code=400, detail="Unknown shadow_root filter value")

        lowered_search = search.strip().lower()
        items: list[dict[str, Any]] = []

        for entry in snapshot["items"]:
            root_str = str(entry.get("shadow_root", ""))
            if root_str not in selected_roots:
                continue
            virtual_path = str(entry.get("virtual_path", ""))
            real_path = str(entry.get("real_path", ""))
            if (
                lowered_search
                and lowered_search not in virtual_path.lower()
                and lowered_search not in real_path.lower()
            ):
                continue
            items.append(entry)

        if include_arr_state:
            scoped_virtual_paths = {
                value.strip()
                for value in (arr_virtual_path or [])
                if isinstance(value, str) and value.strip()
            }
            if scoped_virtual_paths:
                scoped_items = [
                    item
                    for item in items
                    if str(item.get("virtual_path", "")) in scoped_virtual_paths
                ]
                scoped_enriched = enrich_mapped_directories_with_radarr_state_fn(
                    scoped_items,
                    config=config,
                    selected_roots=selected_roots,
                    lowered_search=lowered_search,
                    include_missing_virtual_paths=False,
                )
                enriched_by_virtual_path = {
                    str(entry.get("virtual_path", "")): entry for entry in scoped_enriched
                }
                items = [
                    enriched_by_virtual_path.get(str(item.get("virtual_path", "")), item)
                    for item in items
                ]
            else:
                items = enrich_mapped_directories_with_radarr_state_fn(
                    items,
                    config=config,
                    selected_roots=selected_roots,
                    lowered_search=lowered_search,
                    include_missing_virtual_paths=True,
                )

        items = apply_path_mapping_outcomes_fn(
            items,
            state_store=getattr(request.app.state.web, "state_store", None),
        )

        truncated = len(items) > limit
        if truncated:
            items = items[:limit]

        return {
            "items": items,
            "shadow_roots": [str(root) for root in all_roots],
            "truncated": truncated,
            "cache": {
                "ready": bool(snapshot["ready"]),
                "building": bool(snapshot["building"]),
                "updated_at_ms": snapshot["updated_at_ms"],
                "last_error": snapshot["last_error"],
                "entries_total": len(snapshot["items"]),
                "version": snapshot["version"],
                "last_build_duration_ms": snapshot.get("last_build_duration_ms"),
            },
        }

    @router.get("/api/fs/discovery-warnings")
    def discovery_warnings(
        request: Request,
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> dict[str, Any]:
        config = load_config_or_http_fn(read_config_path_fn(request))
        discovery_cache.request_refresh(config)
        snapshot = discovery_cache.snapshot(limit=limit)
        if not snapshot["cache"]["ready"] and snapshot["cache"]["building"]:
            discovery_cache.wait_for_build(timeout=2.0)
            snapshot = discovery_cache.snapshot(limit=limit)
        return snapshot

    @router.post("/api/fs/mapped-directories/refresh")
    def refresh_mapped_directories(request: Request) -> dict[str, Any]:
        manager = job_manager_or_http_fn(request)
        config_path = read_config_path_fn(request)

        def action() -> dict[str, Any]:
            config = load_config_or_http_fn(config_path)
            started = mapped_cache.request_refresh(config, force=True)
            return {
                "ok": True,
                "started": bool(started),
                "message": (
                    "Mapped directory refresh started."
                    if started
                    else "Mapped directory refresh already in progress."
                ),
            }

        snapshot = mapped_cache.snapshot()
        job_id = manager.submit(
            kind="cache-refresh-mapped-request",
            name="Refresh Mapped Directories",
            source="job-manager",
            detail="queued",
            func=action,
            history_visible=False,
        )
        return {
            "ok": True,
            "queued": True,
            "job_id": job_id,
            "cache": {
                "ready": bool(snapshot["ready"]),
                "building": bool(snapshot["building"]),
                "entries_total": len(snapshot["items"]),
                "version": snapshot["version"],
                "last_build_duration_ms": snapshot.get("last_build_duration_ms"),
            },
        }

    @router.get("/api/fs/mapped-directories/stream")
    async def mapped_directories_stream(
        request: Request,
        interval_ms: int = Query(default=2000, ge=200, le=10000),
        max_events: int = Query(default=0, ge=0),
    ) -> StreamingResponse:
        async def event_stream():
            previous_version: int | None = None
            event_count = 0
            while True:
                if await request.is_disconnected():
                    break

                snapshot = mapped_cache.snapshot()
                current_version = int(snapshot["version"])
                changed = previous_version is not None and current_version != previous_version

                if previous_version is None or changed:
                    payload = {
                        "changed": changed,
                        "cache_ready": bool(snapshot["ready"]),
                        "cache_building": bool(snapshot["building"]),
                        "cache_entries_total": len(snapshot["items"]),
                        "timestamp_ms": int(time.time() * 1000),
                    }
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\\n\\n"
                    event_count += 1
                    if max_events > 0 and event_count >= max_events:
                        break
                else:
                    yield ": keepalive\\n\\n"

                previous_version = current_version
                await asyncio.sleep(interval_ms / 1000)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router
