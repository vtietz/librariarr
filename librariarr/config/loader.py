from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .defaults import DEFAULT_EXCLUDE_PATH_PATTERNS, DEFAULT_SCAN_VIDEO_EXTENSIONS
from .models import (
    AppConfig,
    IngestConfig,
    MovieRootMapping,
    PathsConfig,
    RadarrConfig,
    RadarrProjectionConfig,
    RootMapping,
    RuntimeConfig,
    SonarrConfig,
    SonarrProjectionConfig,
)


def _require(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise ValueError(f"Missing required config key: {key}")
    return data[key]


def _require_any(data: dict[str, Any], primary: str, legacy: str) -> Any:
    if primary in data:
        return data[primary]
    if legacy in data:
        return data[legacy]
    raise ValueError(f"Missing required config key: {primary}")


def _env_or_default(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value


def _normalize_extensions(raw_value: Any, *, key_name: str) -> list[str]:
    if raw_value is None:
        return list(DEFAULT_SCAN_VIDEO_EXTENSIONS)
    if not isinstance(raw_value, list):
        raise ValueError(f"{key_name} must be a list of file extensions")
    return [
        f".{text}" for text in (str(item).strip().lower().lstrip(".") for item in raw_value) if text
    ]


def _extras_allowlist(raw_value: Any, *, key_name: str, defaults: list[str]) -> list[str]:
    if raw_value is None:
        return list(defaults)
    if not isinstance(raw_value, list):
        raise ValueError(f"{key_name} must be a list")
    return [str(item).strip() for item in raw_value if str(item).strip()]


def _paths_overlap(left: Path, right: Path) -> bool:
    if left == right:
        return True
    for one, other in ((left, right), (right, left)):
        try:
            one.relative_to(other)
            return True
        except ValueError:
            continue
    return False


def _validate_root_mappings(
    mappings: list[MovieRootMapping] | list[RootMapping], *, key_name: str
) -> None:
    managed_to_library: dict[str, str] = {}
    for mapping in mappings:
        managed_root = Path(mapping.managed_root)
        library_root = Path(mapping.library_root)
        if not managed_root.is_absolute():
            raise ValueError(f"paths.{key_name}[].managed_root must be an absolute path")
        if not library_root.is_absolute():
            raise ValueError(f"paths.{key_name}[].library_root must be an absolute path")
        if _paths_overlap(managed_root, library_root):
            raise ValueError(
                f"paths.{key_name} entries must not overlap: managed_root and "
                "library_root must be distinct, non-nested paths"
            )
        existing = managed_to_library.get(str(managed_root))
        if existing is not None and existing != str(library_root):
            raise ValueError(
                f"Each managed_root may map to exactly one library_root in paths.{key_name}"
            )
        managed_to_library[str(managed_root)] = str(library_root)


def _load_paths(raw: dict[str, Any], radarr_enabled: bool, sonarr_enabled: bool) -> PathsConfig:
    paths = _require(raw, "paths")

    series_raw = paths.get("series_root_mappings") or []
    if not isinstance(series_raw, list):
        raise ValueError("paths.series_root_mappings must be a list")
    series_root_mappings = [
        RootMapping(
            managed_root=str(_require_any(item, "managed_root", "nested_root")),
            library_root=str(_require_any(item, "library_root", "shadow_root")),
        )
        for item in series_raw
    ]

    movie_raw = paths.get("movie_root_mappings") or []
    if not isinstance(movie_raw, list):
        raise ValueError("paths.movie_root_mappings must be a list")
    movie_root_mappings = [
        MovieRootMapping(
            managed_root=str(_require(item, "managed_root")),
            library_root=str(_require(item, "library_root")),
        )
        for item in movie_raw
    ]
    if radarr_enabled and not movie_root_mappings:
        raise ValueError("paths.movie_root_mappings is required when Radarr is enabled")
    _validate_root_mappings(movie_root_mappings, key_name="movie_root_mappings")
    if sonarr_enabled and not series_root_mappings:
        raise ValueError("paths.series_root_mappings is required when Sonarr is enabled")
    _validate_root_mappings(series_root_mappings, key_name="series_root_mappings")

    exclude_raw = paths.get("exclude_paths") or []
    if not isinstance(exclude_raw, list):
        raise ValueError("paths.exclude_paths must be a list of glob-style path patterns")
    exclude_paths = [str(item).strip() for item in exclude_raw if str(item).strip()]
    configured = {item.lower() for item in exclude_paths}
    for pattern in DEFAULT_EXCLUDE_PATH_PATTERNS:
        if pattern.lower() not in configured:
            exclude_paths.append(pattern)

    return PathsConfig(
        series_root_mappings=series_root_mappings,
        movie_root_mappings=movie_root_mappings,
        exclude_paths=exclude_paths,
    )


def _load_radarr(raw: dict[str, Any], has_radarr: bool) -> RadarrConfig:
    radarr = raw.get("radarr") or {}
    enabled = bool(radarr.get("enabled", has_radarr))
    default_url = str(_require(radarr, "url")).rstrip("/") if has_radarr else ""
    default_api_key = str(_require(radarr, "api_key")) if has_radarr else ""
    projection_raw = radarr.get("projection") if isinstance(radarr.get("projection"), dict) else {}
    profile_raw = radarr.get("auto_add_quality_profile_id")
    return RadarrConfig(
        enabled=enabled,
        url=_env_or_default("LIBRARIARR_RADARR_URL", default_url),
        api_key=_env_or_default("LIBRARIARR_RADARR_API_KEY", default_api_key),
        sync_enabled=enabled and bool(radarr.get("sync_enabled", has_radarr)),
        refresh_debounce_seconds=max(0, int(radarr.get("refresh_debounce_seconds", 15))),
        auto_add_unmatched=enabled and bool(radarr.get("auto_add_unmatched", False)),
        auto_add_quality_profile_id=int(profile_raw) if profile_raw is not None else None,
        auto_add_search_on_add=bool(radarr.get("auto_add_search_on_add", False)),
        auto_add_monitored=bool(radarr.get("auto_add_monitored", True)),
        request_timeout_seconds=max(1, int(radarr.get("request_timeout_seconds", 120))),
        request_retry_attempts=max(0, int(radarr.get("request_retry_attempts", 1))),
        request_retry_backoff_seconds=max(
            0.0, float(radarr.get("request_retry_backoff_seconds", 1.0))
        ),
        projection=RadarrProjectionConfig(
            managed_video_extensions=_normalize_extensions(
                projection_raw.get("managed_video_extensions"),
                key_name="radarr.projection.managed_video_extensions",
            ),
            managed_extras_allowlist=_extras_allowlist(
                projection_raw.get("managed_extras_allowlist"),
                key_name="radarr.projection.managed_extras_allowlist",
                defaults=["*.srt", "*.sub", "movie.nfo", "poster.jpg", "fanart.jpg"],
            ),
        ),
    )


def _load_sonarr(raw: dict[str, Any], has_sonarr: bool) -> SonarrConfig:
    sonarr = raw.get("sonarr") or {}
    default_url = str(_require(sonarr, "url")).rstrip("/") if has_sonarr else ""
    default_api_key = str(_require(sonarr, "api_key")) if has_sonarr else ""
    projection_raw = sonarr.get("projection") if isinstance(sonarr.get("projection"), dict) else {}
    quality_raw = sonarr.get("auto_add_quality_profile_id")
    language_raw = sonarr.get("auto_add_language_profile_id")
    return SonarrConfig(
        enabled=bool(sonarr.get("enabled", False)),
        url=_env_or_default("LIBRARIARR_SONARR_URL", default_url),
        api_key=_env_or_default("LIBRARIARR_SONARR_API_KEY", default_api_key),
        sync_enabled=bool(sonarr.get("sync_enabled", has_sonarr)),
        refresh_debounce_seconds=max(0, int(sonarr.get("refresh_debounce_seconds", 15))),
        auto_add_unmatched=bool(sonarr.get("auto_add_unmatched", False)),
        auto_add_quality_profile_id=int(quality_raw) if quality_raw is not None else None,
        auto_add_language_profile_id=int(language_raw) if language_raw is not None else None,
        auto_add_search_on_add=bool(sonarr.get("auto_add_search_on_add", False)),
        auto_add_monitored=bool(sonarr.get("auto_add_monitored", True)),
        auto_add_season_folder=bool(sonarr.get("auto_add_season_folder", True)),
        request_timeout_seconds=max(1, int(sonarr.get("request_timeout_seconds", 30))),
        request_retry_attempts=max(0, int(sonarr.get("request_retry_attempts", 2))),
        request_retry_backoff_seconds=max(
            0.0, float(sonarr.get("request_retry_backoff_seconds", 0.5))
        ),
        projection=SonarrProjectionConfig(
            managed_video_extensions=_normalize_extensions(
                projection_raw.get("managed_video_extensions"),
                key_name="sonarr.projection.managed_video_extensions",
            ),
            managed_extras_allowlist=_extras_allowlist(
                projection_raw.get("managed_extras_allowlist"),
                key_name="sonarr.projection.managed_extras_allowlist",
                defaults=[
                    "*.srt",
                    "*.ass",
                    "*.sub",
                    "series.nfo",
                    "tvshow.nfo",
                    "poster.jpg",
                    "fanart.jpg",
                ],
            ),
        ),
    )


def _load_runtime(raw: dict[str, Any]) -> RuntimeConfig:
    runtime_raw = raw.get("runtime") or {}
    raw_scope = runtime_raw.get("startup_scope", "full")
    if raw_scope is False:  # YAML parses a bare `off` as boolean
        raw_scope = "off"
    startup_scope = str(raw_scope).strip().lower() or "full"
    if startup_scope not in {"full", "consistency", "off"}:
        raise ValueError("runtime.startup_scope must be one of: full, consistency, off")
    return RuntimeConfig(
        debounce_seconds=max(0, int(runtime_raw.get("debounce_seconds", 8))),
        consistency_interval_seconds=max(
            30, int(runtime_raw.get("consistency_interval_seconds", 300))
        ),
        full_interval_minutes=max(1, int(runtime_raw.get("full_interval_minutes", 1440))),
        startup_scope=startup_scope,
    )


def _load_ingest(raw: dict[str, Any]) -> IngestConfig:
    ingest_raw = raw.get("ingest") or {}
    if not isinstance(ingest_raw, dict):
        raise ValueError("ingest must be a mapping")
    mode = str(ingest_raw.get("replacement_delete_mode", "soft")).strip().lower()
    if mode not in {"soft", "hard"}:
        raise ValueError("ingest.replacement_delete_mode must be 'soft' or 'hard'")
    return IngestConfig(
        enabled=bool(ingest_raw.get("enabled", True)),
        replacement_delete_mode=mode,
    )


def load_config(path: str | Path) -> AppConfig:
    with Path(path).open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    has_radarr = "radarr" in raw
    has_sonarr = "sonarr" in raw
    if not has_radarr and not has_sonarr:
        raise ValueError("At least one config section is required: radarr or sonarr")

    radarr = _load_radarr(raw, has_radarr)
    sonarr = _load_sonarr(raw, has_sonarr)
    return AppConfig(
        paths=_load_paths(raw, radarr.enabled, sonarr.enabled),
        radarr=radarr,
        sonarr=sonarr,
        runtime=_load_runtime(raw),
        ingest=_load_ingest(raw),
    )
