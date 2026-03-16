from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field


class ArrConnectionRequest(BaseModel):
    url: str = Field(min_length=1)
    api_key: str = Field(min_length=1)


def build_arr_router(
    *,
    logger: logging.Logger,
    safe_log_url_fn: Callable[[str], str],
    radarr_client_cls: Any,
    sonarr_client_cls: Any,
    load_config_or_http_fn: Callable[[Path], Any],
    read_config_path_fn: Callable[[Request], Path],
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/radarr/test")
    def test_radarr_connection(payload: ArrConnectionRequest) -> dict[str, Any]:
        safe_url = safe_log_url_fn(payload.url)
        logger.info("Testing Radarr connection to %s", safe_url)
        client = radarr_client_cls(payload.url, payload.api_key)
        try:
            status = client.get_system_status()
            version = status.get("version") if isinstance(status, dict) else None
            suffix = f" (version={version})" if isinstance(version, str) and version else ""
            logger.info("Radarr connection test succeeded: %s%s", safe_url, suffix)
            return {"ok": True, "message": f"Connected to Radarr{suffix}."}
        except Exception as exc:
            logger.error("Radarr connection test failed for %s: %s", safe_url, exc)
            return {"ok": False, "message": str(exc)}

    @router.post("/api/radarr/movies/{movie_id}/refresh")
    def refresh_radarr_movie(movie_id: int, request: Request) -> dict[str, Any]:
        config = load_config_or_http_fn(read_config_path_fn(request))
        if not config.radarr.enabled:
            raise HTTPException(status_code=400, detail="Radarr is disabled.")

        client = radarr_client_cls(
            config.radarr.url,
            config.radarr.api_key,
            refresh_debounce_seconds=config.radarr.refresh_debounce_seconds,
        )

        try:
            started = client.refresh_movie(movie_id, force=True)
            return {
                "ok": True,
                "movie_id": movie_id,
                "started": bool(started),
            }
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to refresh Radarr movie: {exc}",
            ) from exc

    @router.post("/api/sonarr/test")
    def test_sonarr_connection(payload: ArrConnectionRequest) -> dict[str, Any]:
        safe_url = safe_log_url_fn(payload.url)
        logger.info("Testing Sonarr connection to %s", safe_url)
        client = sonarr_client_cls(payload.url, payload.api_key)
        try:
            status = client.get_system_status()
            version = status.get("version") if isinstance(status, dict) else None
            suffix = f" (version={version})" if isinstance(version, str) and version else ""
            logger.info("Sonarr connection test succeeded: %s%s", safe_url, suffix)
            return {"ok": True, "message": f"Connected to Sonarr{suffix}."}
        except Exception as exc:
            logger.error("Sonarr connection test failed for %s: %s", safe_url, exc)
            return {"ok": False, "message": str(exc)}

    return router
