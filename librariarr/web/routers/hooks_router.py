from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from ...projection import get_radarr_webhook_queue, get_sonarr_webhook_queue


def build_hooks_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/hooks/radarr")
    async def radarr_hook(
        request: Request,
        x_librariarr_webhook_secret: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _validate_secret(x_librariarr_webhook_secret)

        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Webhook payload must be a JSON object")

        movie_id = _extract_movie_id(payload)
        event_type = _extract_event_type(payload)
        normalized_path = _extract_event_path(payload)

        if movie_id is None:
            return {
                "ok": True,
                "queued": False,
                "reason": "movie_id_missing",
            }

        queue = get_radarr_webhook_queue()
        queue_result = queue.enqueue(
            movie_id=movie_id,
            event_type=event_type,
            normalized_path=normalized_path,
        )

        return {
            "ok": True,
            "queued": bool(queue_result["queued"]),
            "deduped": bool(queue_result["deduped"]),
            "movie_id": movie_id,
            "event_type": event_type,
            "queue_size": int(queue_result["queue_size"]),
            "dropped_events": int(queue_result["dropped_events"]),
        }

    @router.post("/api/hooks/sonarr")
    async def sonarr_hook(
        request: Request,
        x_librariarr_webhook_secret: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _validate_secret(x_librariarr_webhook_secret)

        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Webhook payload must be a JSON object")

        series_id = _extract_series_id(payload)
        event_type = _extract_event_type(payload)
        normalized_path = _extract_series_event_path(payload)

        if series_id is None:
            return {
                "ok": True,
                "queued": False,
                "reason": "series_id_missing",
            }

        queue = get_sonarr_webhook_queue()
        queue_result = queue.enqueue(
            series_id=series_id,
            event_type=event_type,
            normalized_path=normalized_path,
        )

        return {
            "ok": True,
            "queued": bool(queue_result["queued"]),
            "deduped": bool(queue_result["deduped"]),
            "series_id": series_id,
            "event_type": event_type,
            "queue_size": int(queue_result["queue_size"]),
            "dropped_events": int(queue_result["dropped_events"]),
        }

    return router


def _validate_secret(received_secret: str | None) -> None:
    configured = str(
        os.getenv("LIBRARIARR_WEBHOOK_SECRET")
        or os.getenv("LIBRARIARR_RADARR_WEBHOOK_SECRET")
        or ""
    ).strip()
    if not configured:
        return
    if received_secret is None or received_secret.strip() != configured:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


def _extract_movie_id(payload: dict[str, Any]) -> int | None:
    movie_value = payload.get("movie")
    if isinstance(movie_value, dict):
        movie_id = movie_value.get("id")
        if isinstance(movie_id, int):
            return movie_id

    for key in ("movieId", "movie_id", "id"):
        movie_id = payload.get(key)
        if isinstance(movie_id, int):
            return movie_id

    return None


def _extract_event_type(payload: dict[str, Any]) -> str:
    for key in ("eventType", "event_type", "type"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unknown"


def _extract_series_id(payload: dict[str, Any]) -> int | None:
    series_value = payload.get("series")
    if isinstance(series_value, dict):
        series_id = series_value.get("id")
        if isinstance(series_id, int):
            return series_id

    episode_file = payload.get("episodeFile")
    if isinstance(episode_file, dict):
        series_id = episode_file.get("seriesId")
        if isinstance(series_id, int):
            return series_id

    for key in ("seriesId", "series_id", "id"):
        series_id = payload.get(key)
        if isinstance(series_id, int):
            return series_id

    return None


def _extract_event_path(payload: dict[str, Any]) -> str:
    movie_value = payload.get("movie")
    if isinstance(movie_value, dict):
        value = movie_value.get("path")
        if isinstance(value, str) and value.strip():
            return _normalize_path(value)

    movie_file = payload.get("movieFile")
    if isinstance(movie_file, dict):
        value = movie_file.get("path")
        if isinstance(value, str) and value.strip():
            return _normalize_path(value)

    for key in ("path", "folderPath", "folder"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize_path(value)

    return ""


def _extract_series_event_path(payload: dict[str, Any]) -> str:
    series_value = payload.get("series")
    if isinstance(series_value, dict):
        value = series_value.get("path")
        if isinstance(value, str) and value.strip():
            return _normalize_path(value)

    episode_file = payload.get("episodeFile")
    if isinstance(episode_file, dict):
        value = episode_file.get("path")
        if isinstance(value, str) and value.strip():
            return _normalize_path(value)

    for key in ("path", "folderPath", "folder"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize_path(value)

    return ""


def _normalize_path(path: str) -> str:
    normalized = str(path).strip().replace("\\", "/")
    if len(normalized) > 1:
        normalized = normalized.rstrip("/")
    return normalized
