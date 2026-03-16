from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter


def build_diagnostics_router(
    *,
    state: Any,
    job_manager_or_http_fn: Callable[[Any], Any],
    safe_load_disk_config_fn: Callable[[Path], Any],
    run_radarr_diagnostics_fn: Callable[[Any], dict[str, Any]],
    run_sonarr_diagnostics_fn: Callable[[Any], dict[str, Any]],
    logger: logging.Logger,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/diagnostics/radarr")
    def diagnostics_radarr() -> dict[str, Any]:
        manager = job_manager_or_http_fn(state)

        def action() -> dict[str, Any]:
            logger.info("Running Radarr diagnostics")
            config = safe_load_disk_config_fn(state.config_path)
            result = run_radarr_diagnostics_fn(config)
            issue_count = len(result.get("issues", []))
            logger.info(
                "Radarr diagnostics completed: status=%s, issues=%d",
                result.get("status"),
                issue_count,
            )
            return result

        job_id = manager.submit(kind="diagnostics-radarr", func=action)
        return {
            "ok": True,
            "queued": True,
            "job_id": job_id,
            "message": "Radarr diagnostics scheduled.",
        }

    @router.post("/api/diagnostics/sonarr")
    def diagnostics_sonarr() -> dict[str, Any]:
        manager = job_manager_or_http_fn(state)

        def action() -> dict[str, Any]:
            logger.info("Running Sonarr diagnostics")
            config = safe_load_disk_config_fn(state.config_path)
            result = run_sonarr_diagnostics_fn(config)
            issue_count = len(result.get("issues", []))
            logger.info(
                "Sonarr diagnostics completed: status=%s, issues=%d",
                result.get("status"),
                issue_count,
            )
            return result

        job_id = manager.submit(kind="diagnostics-sonarr", func=action)
        return {
            "ok": True,
            "queued": True,
            "job_id": job_id,
            "message": "Sonarr diagnostics scheduled.",
        }

    return router
