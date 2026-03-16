from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter


def build_metadata_router(  # noqa: C901
    *,
    state: Any,
    safe_load_disk_config_fn: Callable[[Path], Any],
    logger: logging.Logger,
    radarr_client_cls: Any,
    sonarr_client_cls: Any,
) -> APIRouter:
    router = APIRouter()

    def _radarr_items(fetch: Callable[[Any], Any]) -> dict[str, Any]:
        config = safe_load_disk_config_fn(state.config_path)
        if not config.radarr.enabled:
            return {"enabled": False, "items": [], "error": None}

        client = radarr_client_cls(config.radarr.url, config.radarr.api_key, timeout=5)
        try:
            items = fetch(client)
            count = len(items) if isinstance(items, list) else 0
            logger.debug("Radarr metadata fetch returned %d items", count)
            return {"enabled": True, "items": items, "error": None}
        except Exception as exc:
            logger.error("Radarr metadata fetch failed: %s", exc)
            return {"enabled": True, "items": [], "error": str(exc)}

    def _sonarr_items(fetch: Callable[[Any], Any]) -> dict[str, Any]:
        config = safe_load_disk_config_fn(state.config_path)
        if not config.sonarr.enabled:
            return {"enabled": False, "items": [], "error": None}

        client = sonarr_client_cls(config.sonarr.url, config.sonarr.api_key, timeout=5)
        try:
            items = fetch(client)
            count = len(items) if isinstance(items, list) else 0
            logger.debug("Sonarr metadata fetch returned %d items", count)
            return {"enabled": True, "items": items, "error": None}
        except Exception as exc:
            logger.error("Sonarr metadata fetch failed: %s", exc)
            return {"enabled": True, "items": [], "error": str(exc)}

    @router.get("/api/radarr/quality-profiles")
    def radarr_quality_profiles() -> dict[str, Any]:
        return _radarr_items(lambda client: client.get_quality_profiles())

    @router.get("/api/radarr/quality-definitions")
    def radarr_quality_definitions() -> dict[str, Any]:
        return _radarr_items(lambda client: client.get_quality_definitions())

    @router.get("/api/radarr/custom-formats")
    def radarr_custom_formats() -> dict[str, Any]:
        return _radarr_items(lambda client: client.get_custom_formats())

    @router.get("/api/radarr/root-folders")
    def radarr_root_folders() -> dict[str, Any]:
        return _radarr_items(lambda client: client.get_root_folders())

    @router.get("/api/radarr/tags")
    def radarr_tags() -> dict[str, Any]:
        return _radarr_items(lambda client: client.get_tags())

    @router.get("/api/sonarr/quality-profiles")
    def sonarr_quality_profiles() -> dict[str, Any]:
        return _sonarr_items(lambda client: client.get_quality_profiles())

    @router.get("/api/sonarr/language-profiles")
    def sonarr_language_profiles() -> dict[str, Any]:
        return _sonarr_items(lambda client: client.get_language_profiles())

    @router.get("/api/sonarr/root-folders")
    def sonarr_root_folders() -> dict[str, Any]:
        return _sonarr_items(lambda client: client.get_root_folders())

    @router.get("/api/sonarr/tags")
    def sonarr_tags() -> dict[str, Any]:
        return _sonarr_items(lambda client: client.get_tags())

    return router
