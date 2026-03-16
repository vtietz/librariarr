from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..clients.radarr import RadarrClient
from ..clients.sonarr import SonarrClient
from ..config import AppConfig
from .mapped_cache import MappedDirectoriesCache
from .state_store import PersistentStateStore

PATH_MAPPING_STATUS_SNAPSHOT = "path_mapping_status"
PATH_MAPPING_STATUS_LIMIT = 5000


def _normalize_media_path(path: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/")
    if len(normalized) > 1:
        normalized = normalized.rstrip("/")
    return normalized


def _normalize_real_path(path: str) -> str:
    value = str(path or "").strip()
    if not value:
        return ""
    return str(Path(value).resolve(strict=False))


def _read_status_items(state_store: PersistentStateStore | None) -> dict[str, dict[str, Any]]:
    if state_store is None:
        return {}
    snapshot = state_store.load_cache_snapshot(PATH_MAPPING_STATUS_SNAPSHOT)
    if not isinstance(snapshot, dict):
        return {}
    items = snapshot.get("items")
    if not isinstance(items, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for raw_path, raw_payload in items.items():
        if not isinstance(raw_payload, dict):
            continue
        out[str(raw_path)] = dict(raw_payload)
    return out


def _write_status_items(
    state_store: PersistentStateStore,
    items: dict[str, dict[str, Any]],
) -> None:
    state_store.save_cache_snapshot(
        PATH_MAPPING_STATUS_SNAPSHOT,
        {
            "items": items,
            "updated_at_ms": int(time.time() * 1000),
        },
    )


def _trim_status_items(items: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if len(items) <= PATH_MAPPING_STATUS_LIMIT:
        return items
    ordered = sorted(
        items.items(),
        key=lambda pair: int(pair[1].get("updated_at_ms") or 0),
        reverse=True,
    )
    return dict(ordered[:PATH_MAPPING_STATUS_LIMIT])


def record_path_mapping_outcome(
    *,
    state_store: PersistentStateStore | None,
    real_path: str,
    outcome: dict[str, Any],
) -> None:
    if state_store is None:
        return
    normalized_path = _normalize_real_path(real_path)
    if not normalized_path:
        return
    items = _read_status_items(state_store)
    items[normalized_path] = {
        "status": str(outcome.get("status") or "unknown"),
        "arr": str(outcome.get("arr") or "none"),
        "message": str(outcome.get("message") or ""),
        "movie_id": outcome.get("movie_id") if isinstance(outcome.get("movie_id"), int) else None,
        "series_id": (
            outcome.get("series_id") if isinstance(outcome.get("series_id"), int) else None
        ),
        "updated_at_ms": int(time.time() * 1000),
    }
    _write_status_items(state_store, _trim_status_items(items))


def apply_path_mapping_outcomes(
    items: list[dict[str, Any]],
    *,
    state_store: PersistentStateStore | None,
) -> list[dict[str, Any]]:
    status_items = _read_status_items(state_store)
    if not status_items:
        return items

    for entry in items:
        real_path = _normalize_real_path(str(entry.get("real_path") or ""))
        if not real_path:
            continue
        payload = status_items.get(real_path)
        if payload is None:
            continue
        entry["last_reconcile_status"] = payload.get("status")
        entry["last_reconcile_arr"] = payload.get("arr")
        entry["last_reconcile_message"] = payload.get("message")
        entry["last_reconcile_movie_id"] = payload.get("movie_id")
        entry["last_reconcile_series_id"] = payload.get("series_id")
        entry["last_reconcile_updated_at_ms"] = payload.get("updated_at_ms")
    return items


def build_path_mapping_outcome(
    *,
    real_path: str,
    config: AppConfig,
    mapped_cache: MappedDirectoriesCache,
) -> dict[str, Any]:
    normalized_real_path = _normalize_real_path(real_path)
    if not normalized_real_path:
        return {
            "status": "invalid_path",
            "arr": "none",
            "message": "Path is empty.",
            "movie_id": None,
            "series_id": None,
        }

    snapshot = mapped_cache.snapshot()
    virtual_paths = {
        _normalize_media_path(str(entry.get("virtual_path") or ""))
        for entry in snapshot.get("items", [])
        if _normalize_real_path(str(entry.get("real_path") or "")) == normalized_real_path
    }
    virtual_paths.discard("")

    if not virtual_paths:
        return {
            "status": "not_mapped",
            "arr": "none",
            "message": "No virtual mapping exists for this path.",
            "movie_id": None,
            "series_id": None,
        }

    arr_errors: list[str] = []

    if config.radarr.enabled:
        try:
            radarr_client = RadarrClient(
                config.radarr.url,
                config.radarr.api_key,
                refresh_debounce_seconds=config.radarr.refresh_debounce_seconds,
            )
            for movie in radarr_client.get_movies():
                movie_path = _normalize_media_path(str(movie.get("path") or ""))
                if movie_path in virtual_paths:
                    return {
                        "status": "success",
                        "arr": "radarr",
                        "message": str(movie.get("title") or "Found in Radarr."),
                        "movie_id": movie.get("id") if isinstance(movie.get("id"), int) else None,
                        "series_id": None,
                    }
        except Exception as exc:
            arr_errors.append(f"Radarr: {exc}")

    if config.sonarr.enabled:
        try:
            sonarr_client = SonarrClient(
                config.sonarr.url,
                config.sonarr.api_key,
                refresh_debounce_seconds=config.sonarr.refresh_debounce_seconds,
            )
            for series in sonarr_client.get_series():
                series_path = _normalize_media_path(str(series.get("path") or ""))
                if series_path in virtual_paths:
                    return {
                        "status": "success",
                        "arr": "sonarr",
                        "message": str(series.get("title") or "Found in Sonarr."),
                        "movie_id": None,
                        "series_id": (
                            series.get("id") if isinstance(series.get("id"), int) else None
                        ),
                    }
        except Exception as exc:
            arr_errors.append(f"Sonarr: {exc}")

    if arr_errors:
        return {
            "status": "arr_unreachable",
            "arr": "both" if config.radarr.enabled and config.sonarr.enabled else "unknown",
            "message": "; ".join(arr_errors),
            "movie_id": None,
            "series_id": None,
        }

    target_arr = (
        "radarr" if config.radarr.enabled else "sonarr" if config.sonarr.enabled else "none"
    )
    return {
        "status": "not_found_in_arr",
        "arr": target_arr,
        "message": "Mapped path exists, but no Radarr/Sonarr item was found.",
        "movie_id": None,
        "series_id": None,
    }
