from __future__ import annotations

from pathlib import Path
from typing import Any

from ..clients.radarr import RadarrClient
from ..clients.sonarr import SonarrClient
from ..config import AppConfig


def _normalize_media_path(path: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/")
    if len(normalized) > 1:
        normalized = normalized.rstrip("/")
    return normalized


def _path_is_equal_or_child(path_text: str, parent_text: str) -> bool:
    path = Path(path_text)
    parent = Path(parent_text)
    if path == parent:
        return True
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_in_any_root(path_text: str, roots: list[str]) -> bool:
    return any(_path_is_equal_or_child(path_text, root) for root in roots)


def _arr_state_for_mapped_entry(
    *,
    virtual_path: str,
    real_path: str,
    target_exists: bool,
    movie: dict[str, Any] | None,
    in_radarr_scope: bool,
) -> str:
    if movie is not None:
        if not target_exists:
            return "missing_on_disk"
        return "ok"
    if in_radarr_scope:
        return "missing_in_arr"
    return "not_managed"


def enrich_mapped_directories_with_radarr_state(
    items: list[dict[str, Any]],
    *,
    config: AppConfig,
    selected_roots: set[str],
    lowered_search: str,
    include_missing_virtual_paths: bool = True,
) -> list[dict[str, Any]]:
    enriched = [dict(item) for item in items]

    if not config.radarr.enabled:
        for entry in enriched:
            entry.update(
                {
                    "arr_state": "not_managed",
                    "arr_movie_id": None,
                    "arr_title": None,
                    "arr_monitored": None,
                }
            )
        return enriched

    client = RadarrClient(
        config.radarr.url,
        config.radarr.api_key,
        refresh_debounce_seconds=config.radarr.refresh_debounce_seconds,
    )

    try:
        movies = client.get_movies()
        root_folders = client.get_root_folders()
    except Exception:
        for entry in enriched:
            entry.update(
                {
                    "arr_state": "arr_unreachable",
                    "arr_movie_id": None,
                    "arr_title": None,
                    "arr_monitored": None,
                }
            )
        return enriched

    radarr_roots = [
        _normalize_media_path(str(folder.get("path") or ""))
        for folder in root_folders
        if isinstance(folder, dict) and str(folder.get("path") or "").strip()
    ]
    movie_by_path = {
        _normalize_media_path(str(movie.get("path") or "")): movie
        for movie in movies
        if isinstance(movie, dict) and str(movie.get("path") or "").strip()
    }
    mapped_virtual_paths = {
        _normalize_media_path(str(entry.get("virtual_path") or ""))
        for entry in enriched
        if str(entry.get("virtual_path") or "").strip()
    }

    for entry in enriched:
        virtual_path = _normalize_media_path(str(entry.get("virtual_path") or ""))
        real_path = str(entry.get("real_path") or "")
        shadow_root = _normalize_media_path(str(entry.get("shadow_root") or ""))
        movie = movie_by_path.get(virtual_path)
        in_radarr_scope = bool(radarr_roots) and _is_in_any_root(shadow_root, radarr_roots)
        entry.update(
            {
                "arr_state": _arr_state_for_mapped_entry(
                    virtual_path=virtual_path,
                    real_path=real_path,
                    target_exists=bool(entry.get("target_exists")),
                    movie=movie,
                    in_radarr_scope=in_radarr_scope,
                ),
                "arr_movie_id": movie.get("id") if isinstance(movie, dict) else None,
                "arr_title": movie.get("title") if isinstance(movie, dict) else None,
                "arr_monitored": movie.get("monitored") if isinstance(movie, dict) else None,
            }
        )

    if include_missing_virtual_paths:
        selected_roots_list = list(selected_roots)
        for movie in movies:
            if not isinstance(movie, dict):
                continue
            virtual_path = _normalize_media_path(str(movie.get("path") or ""))
            if not virtual_path or virtual_path in mapped_virtual_paths:
                continue
            if not _is_in_any_root(virtual_path, selected_roots_list):
                continue
            if lowered_search and lowered_search not in virtual_path.lower():
                continue

            matching_roots = [
                root for root in selected_roots if _path_is_equal_or_child(virtual_path, root)
            ]
            shadow_root = (
                max(matching_roots, key=len) if matching_roots else str(Path(virtual_path).parent)
            )
            enriched.append(
                {
                    "shadow_root": shadow_root,
                    "virtual_path": virtual_path,
                    "real_path": "",
                    "target_exists": False,
                    "arr_state": "missing_virtual_path",
                    "arr_movie_id": movie.get("id"),
                    "arr_title": movie.get("title"),
                    "arr_monitored": movie.get("monitored"),
                }
            )

    return enriched


def _sonarr_arr_state(
    *,
    target_exists: bool,
    series: dict[str, Any] | None,
    in_sonarr_scope: bool,
) -> str:
    if series is not None:
        if not target_exists:
            return "missing_on_disk"
        return "ok"
    if in_sonarr_scope:
        return "missing_in_arr"
    return "not_managed"


def _append_missing_sonarr_virtual_paths(
    enriched: list[dict[str, Any]],
    all_series: list[dict[str, Any]],
    mapped_virtual_paths: set[str],
    selected_roots: set[str],
    lowered_search: str,
) -> None:
    selected_roots_list = list(selected_roots)
    for series in all_series:
        if not isinstance(series, dict):
            continue
        virtual_path = _normalize_media_path(str(series.get("path") or ""))
        if not virtual_path or virtual_path in mapped_virtual_paths:
            continue
        if not _is_in_any_root(virtual_path, selected_roots_list):
            continue
        if lowered_search and lowered_search not in virtual_path.lower():
            continue

        matching_roots = [
            root for root in selected_roots if _path_is_equal_or_child(virtual_path, root)
        ]
        shadow_root = (
            max(matching_roots, key=len) if matching_roots else str(Path(virtual_path).parent)
        )
        enriched.append(
            {
                "shadow_root": shadow_root,
                "virtual_path": virtual_path,
                "real_path": "",
                "target_exists": False,
                "arr_state": "missing_virtual_path",
                "arr_series_id": series.get("id"),
                "arr_title": series.get("title"),
                "arr_monitored": series.get("monitored"),
            }
        )


def enrich_mapped_directories_with_sonarr_state(
    items: list[dict[str, Any]],
    *,
    config: AppConfig,
    selected_roots: set[str],
    lowered_search: str,
    include_missing_virtual_paths: bool = True,
) -> list[dict[str, Any]]:
    """Enrich items that still have arr_state='not_managed' with Sonarr data."""
    enriched = [dict(item) for item in items]

    if not config.sonarr.enabled:
        return enriched

    client = SonarrClient(
        config.sonarr.url,
        config.sonarr.api_key,
        refresh_debounce_seconds=config.sonarr.refresh_debounce_seconds,
    )

    try:
        all_series = client.get_series()
        root_folders = client.get_root_folders()
    except Exception:
        for entry in enriched:
            if entry.get("arr_state") == "not_managed":
                entry["arr_state"] = "arr_unreachable"
        return enriched

    sonarr_roots = [
        _normalize_media_path(str(folder.get("path") or ""))
        for folder in root_folders
        if isinstance(folder, dict) and str(folder.get("path") or "").strip()
    ]
    series_by_path = {
        _normalize_media_path(str(s.get("path") or "")): s
        for s in all_series
        if isinstance(s, dict) and str(s.get("path") or "").strip()
    }
    mapped_virtual_paths = {
        _normalize_media_path(str(entry.get("virtual_path") or ""))
        for entry in enriched
        if str(entry.get("virtual_path") or "").strip()
    }

    for entry in enriched:
        if entry.get("arr_state") != "not_managed":
            continue
        virtual_path = _normalize_media_path(str(entry.get("virtual_path") or ""))
        shadow_root = _normalize_media_path(str(entry.get("shadow_root") or ""))
        series = series_by_path.get(virtual_path)
        in_sonarr_scope = bool(sonarr_roots) and _is_in_any_root(shadow_root, sonarr_roots)
        entry.update(
            {
                "arr_state": _sonarr_arr_state(
                    target_exists=bool(entry.get("target_exists")),
                    series=series,
                    in_sonarr_scope=in_sonarr_scope,
                ),
                "arr_series_id": series.get("id") if isinstance(series, dict) else None,
                "arr_title": (
                    series.get("title") if isinstance(series, dict) else entry.get("arr_title")
                ),
                "arr_monitored": (
                    series.get("monitored")
                    if isinstance(series, dict)
                    else entry.get("arr_monitored")
                ),
            }
        )

    if include_missing_virtual_paths:
        _append_missing_sonarr_virtual_paths(
            enriched, all_series, mapped_virtual_paths, selected_roots, lowered_search
        )

    return enriched


def enrich_mapped_directories_with_arr_state(
    items: list[dict[str, Any]],
    *,
    config: AppConfig,
    selected_roots: set[str],
    lowered_search: str,
    include_missing_virtual_paths: bool = True,
) -> list[dict[str, Any]]:
    """Enrich items with both Radarr and Sonarr state."""
    enriched = enrich_mapped_directories_with_radarr_state(
        items,
        config=config,
        selected_roots=selected_roots,
        lowered_search=lowered_search,
        include_missing_virtual_paths=include_missing_virtual_paths,
    )
    enriched = enrich_mapped_directories_with_sonarr_state(
        enriched,
        config=config,
        selected_roots=selected_roots,
        lowered_search=lowered_search,
        include_missing_virtual_paths=include_missing_virtual_paths,
    )
    return enriched
