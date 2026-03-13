from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..clients.radarr import RadarrClient
from ..clients.sonarr import SonarrClient
from ..config import AppConfig, load_config
from ..service import LibrariArrService
from .docker_logs import read_docker_logs, stream_docker_logs


class ArrConnectionRequest(BaseModel):
    url: str = Field(min_length=1)
    api_key: str = Field(min_length=1)


def _load_config_or_http(config_path: Path) -> AppConfig:
    try:
        return load_config(config_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unable to load config: {exc}") from exc


def _read_config_path(request: Request) -> Path:
    return Path(request.app.state.web.config_path)


def _shadow_roots(config: AppConfig) -> list[Path]:
    roots = {Path(item.shadow_root) for item in config.paths.root_mappings}
    return sorted(roots)


def _safe_directory_entries(root: Path) -> list[Path]:
    try:
        return sorted(root.iterdir(), key=lambda item: item.name.lower())
    except FileNotFoundError:
        return []


def _mapped_directories_fingerprint(roots: list[Path]) -> str:
    hasher = hashlib.sha256()
    for root in sorted(roots):
        hasher.update(f"root:{root}\n".encode("utf-8", errors="replace"))
        for child in _safe_directory_entries(root):
            if not child.is_symlink():
                continue
            try:
                link_target = os.readlink(child)
            except OSError:
                link_target = ""
            try:
                stat_info = child.lstat()
                link_mtime = stat_info.st_mtime_ns
            except OSError:
                link_mtime = 0
            hasher.update(
                f"link:{child.name}|target:{link_target}|mtime:{link_mtime}\n".encode(
                    "utf-8", errors="replace"
                )
            )
    return hasher.hexdigest()


def build_operations_router() -> APIRouter:  # noqa: C901
    router = APIRouter()

    @router.get("/api/logs/docker")
    def docker_logs(
        container: str | None = Query(default=None),
        tail: int = Query(default=250, ge=10, le=2000),
    ) -> dict[str, Any]:
        selected_container = container or os.getenv(
            "LIBRARIARR_DOCKER_LOGS_CONTAINER", "librariarr"
        )
        items = read_docker_logs(container=selected_container, tail=tail)
        return {
            "container": selected_container,
            "tail": tail,
            "items": items,
        }

    @router.get("/api/logs/docker/stream")
    async def docker_logs_stream(
        container: str | None = Query(default=None),
        tail: int = Query(default=0, ge=0, le=2000),
    ) -> StreamingResponse:
        selected_container = container or os.getenv(
            "LIBRARIARR_DOCKER_LOGS_CONTAINER", "librariarr"
        )

        async def event_stream():
            async for item in stream_docker_logs(container=selected_container, tail=tail):
                payload = json.dumps(item, ensure_ascii=False)
                yield f"data: {payload}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.post("/api/radarr/test")
    def test_radarr_connection(payload: ArrConnectionRequest) -> dict[str, Any]:
        client = RadarrClient(payload.url, payload.api_key)
        try:
            status = client.get_system_status()
            version = status.get("version") if isinstance(status, dict) else None
            suffix = f" (version={version})" if isinstance(version, str) and version else ""
            return {"ok": True, "message": f"Connected to Radarr{suffix}."}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    @router.post("/api/sonarr/test")
    def test_sonarr_connection(payload: ArrConnectionRequest) -> dict[str, Any]:
        client = SonarrClient(payload.url, payload.api_key)
        try:
            status = client.get_system_status()
            version = status.get("version") if isinstance(status, dict) else None
            suffix = f" (version={version})" if isinstance(version, str) and version else ""
            return {"ok": True, "message": f"Connected to Sonarr{suffix}."}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    @router.post("/api/maintenance/reconcile")
    def run_maintenance_reconcile(request: Request) -> dict[str, Any]:
        config = _load_config_or_http(_read_config_path(request))
        started = time.perf_counter()
        try:
            service = LibrariArrService(config)
            ingest_pending = service.reconcile()
            duration_ms = int((time.perf_counter() - started) * 1000)
            return {
                "ok": True,
                "message": "Reconcile completed.",
                "duration_ms": duration_ms,
                "ingest_pending": ingest_pending,
            }
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    @router.get("/api/fs/mapped-directories")
    def mapped_directories(
        request: Request,
        search: str = Query(default=""),
        shadow_root: str | None = Query(default=None),
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> dict[str, Any]:
        config = _load_config_or_http(_read_config_path(request))
        all_roots = _shadow_roots(config)

        if shadow_root is None:
            selected_roots = all_roots
        else:
            selected_roots = [root for root in all_roots if str(root) == shadow_root]
            if not selected_roots:
                raise HTTPException(status_code=400, detail="Unknown shadow_root filter value")

        lowered_search = search.strip().lower()
        items: list[dict[str, Any]] = []
        truncated = False

        for root in selected_roots:
            for child in _safe_directory_entries(root):
                if not child.is_symlink():
                    continue

                virtual_path = str(child)
                real_path = str(child.resolve(strict=False))
                if (
                    lowered_search
                    and lowered_search not in virtual_path.lower()
                    and lowered_search not in real_path.lower()
                ):
                    continue

                items.append(
                    {
                        "shadow_root": str(root),
                        "virtual_path": virtual_path,
                        "real_path": real_path,
                        "target_exists": Path(real_path).exists(),
                    }
                )
                if len(items) >= limit:
                    truncated = True
                    break
            if truncated:
                break

        return {
            "items": items,
            "shadow_roots": [str(root) for root in all_roots],
            "truncated": truncated,
        }

    @router.get("/api/fs/mapped-directories/stream")
    async def mapped_directories_stream(
        request: Request,
        interval_ms: int = Query(default=1000, ge=200, le=10000),
        max_events: int = Query(default=0, ge=0),
    ) -> StreamingResponse:
        async def event_stream():
            previous_fingerprint: str | None = None
            event_count = 0
            while True:
                if await request.is_disconnected():
                    break

                config = _load_config_or_http(_read_config_path(request))
                roots = _shadow_roots(config)
                current_fingerprint = _mapped_directories_fingerprint(roots)

                changed = (
                    previous_fingerprint is not None and current_fingerprint != previous_fingerprint
                )

                if previous_fingerprint is None or changed:
                    payload = {
                        "changed": changed,
                        "shadow_roots": [str(root) for root in roots],
                        "timestamp_ms": int(time.time() * 1000),
                    }
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    event_count += 1
                    if max_events > 0 and event_count >= max_events:
                        break
                else:
                    yield ": keepalive\n\n"

                previous_fingerprint = current_fingerprint
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
