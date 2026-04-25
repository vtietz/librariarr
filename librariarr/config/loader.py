from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .defaults import DEFAULT_SCAN_VIDEO_EXTENSIONS
from .models import (
    AnalysisConfig,
    AppConfig,
    CleanupConfig,
    CustomFormatRule,
    MovieRootMapping,
    PathsConfig,
    ProfileRule,
    QualityRule,
    RadarrConfig,
    RadarrMappingConfig,
    RadarrProjectionConfig,
    RootMapping,
    RuntimeConfig,
    SonarrConfig,
    SonarrMappingConfig,
    SonarrProjectionConfig,
)


def _require(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise ValueError(f"Missing required config key: {key}")
    return data[key]


def _env_or_default(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    if not value.strip():
        return default
    return value


def _normalize_extensions(
    raw_value: Any,
    *,
    key_name: str,
    default_values: list[str],
) -> list[str]:
    if raw_value is None:
        return list(default_values)
    if not isinstance(raw_value, list):
        raise ValueError(f"{key_name} must be a list of file extensions")
    return [
        f".{text}" for text in (str(item).strip().lower().lstrip(".") for item in raw_value) if text
    ]


def _paths_overlap(left: Path, right: Path) -> bool:
    if left == right:
        return True
    try:
        left.relative_to(right)
        return True
    except ValueError:
        pass
    try:
        right.relative_to(left)
        return True
    except ValueError:
        return False


def _validate_movie_root_mappings(mappings: list[MovieRootMapping]) -> None:
    managed_to_library: dict[str, str] = {}
    for mapping in mappings:
        managed_root = Path(mapping.managed_root)
        library_root = Path(mapping.library_root)
        if not managed_root.is_absolute():
            raise ValueError("paths.movie_root_mappings[].managed_root must be an absolute path")
        if not library_root.is_absolute():
            raise ValueError("paths.movie_root_mappings[].library_root must be an absolute path")
        if _paths_overlap(managed_root, library_root):
            raise ValueError(
                "paths.movie_root_mappings entries must not overlap: managed_root and "
                "library_root must be distinct, non-nested paths"
            )

        managed_key = str(managed_root)
        library_value = str(library_root)
        existing_library = managed_to_library.get(managed_key)
        if existing_library is not None and existing_library != library_value:
            raise ValueError(
                "Each managed_root may map to exactly one library_root in paths.movie_root_mappings"
            )
        managed_to_library[managed_key] = library_value


def load_config(path: str | Path) -> AppConfig:  # noqa: C901
    with Path(path).open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    paths = _require(raw, "paths")
    has_radarr = "radarr" in raw
    has_sonarr = "sonarr" in raw
    if not has_radarr and not has_sonarr:
        raise ValueError("At least one config section is required: radarr or sonarr")

    radarr = raw.get("radarr") or {}
    sonarr = raw.get("sonarr") or {}
    radarr_enabled = bool(radarr.get("enabled", True if has_radarr else False))
    sonarr_enabled = bool(sonarr.get("enabled", False if has_sonarr else False))
    radarr_mapping_raw = radarr.get("mapping") if isinstance(radarr.get("mapping"), dict) else {}
    sonarr_mapping_raw = sonarr.get("mapping") if isinstance(sonarr.get("mapping"), dict) else {}
    projection_raw = radarr.get("projection") if isinstance(radarr.get("projection"), dict) else {}
    sonarr_projection_raw = (
        sonarr.get("projection") if isinstance(sonarr.get("projection"), dict) else {}
    )

    if "quality_map" in raw or "custom_format_map" in raw:
        raise ValueError(
            "Top-level quality_map/custom_format_map is no longer supported. "
            "Use radarr.mapping.quality_map and radarr.mapping.custom_format_map."
        )

    series_root_mappings_raw = paths.get("series_root_mappings") or []

    if not isinstance(series_root_mappings_raw, list):
        raise ValueError("paths.series_root_mappings must be a list")

    series_root_mappings = [
        RootMapping(
            nested_root=str(_require(item, "nested_root")),
            shadow_root=str(_require(item, "shadow_root")),
        )
        for item in series_root_mappings_raw
    ]

    movie_root_mappings_raw = paths.get("movie_root_mappings") or []
    if not isinstance(movie_root_mappings_raw, list):
        raise ValueError("paths.movie_root_mappings must be a list")
    movie_root_mappings = [
        MovieRootMapping(
            managed_root=str(_require(item, "managed_root")),
            library_root=str(_require(item, "library_root")),
        )
        for item in movie_root_mappings_raw
    ]
    if radarr_enabled and not movie_root_mappings:
        raise ValueError("paths.movie_root_mappings is required when Radarr is enabled")

    _validate_movie_root_mappings(movie_root_mappings)

    if sonarr_enabled and not series_root_mappings:
        raise ValueError("paths.series_root_mappings is required when Sonarr is enabled")
    exclude_paths_raw = paths.get("exclude_paths", [])
    if exclude_paths_raw is None:
        exclude_paths_raw = []
    if not isinstance(exclude_paths_raw, list):
        raise ValueError("paths.exclude_paths must be a list of glob-style path patterns")
    exclude_paths = [str(item).strip() for item in exclude_paths_raw if str(item).strip()]

    radarr_default_url = str(_require(radarr, "url")).rstrip("/") if has_radarr else ""
    radarr_default_api_key = str(_require(radarr, "api_key")) if has_radarr else ""
    radarr_url = _env_or_default("LIBRARIARR_RADARR_URL", radarr_default_url)
    radarr_api_key = _env_or_default("LIBRARIARR_RADARR_API_KEY", radarr_default_api_key)
    sync_enabled = radarr_enabled and bool(
        radarr.get("sync_enabled", True if has_radarr else False)
    )
    auto_add_unmatched = radarr_enabled and bool(radarr.get("auto_add_unmatched", False))
    auto_add_quality_profile_raw = radarr.get("auto_add_quality_profile_id")
    auto_add_quality_profile_id = (
        int(auto_add_quality_profile_raw) if auto_add_quality_profile_raw is not None else None
    )
    request_timeout_seconds = max(1, int(radarr.get("request_timeout_seconds", 30)))
    request_retry_attempts = max(0, int(radarr.get("request_retry_attempts", 2)))
    request_retry_backoff_seconds = max(
        0.0,
        float(radarr.get("request_retry_backoff_seconds", 0.5)),
    )
    auto_add_search_on_add = bool(radarr.get("auto_add_search_on_add", False))
    auto_add_monitored = bool(radarr.get("auto_add_monitored", True))
    refresh_debounce_seconds = max(0, int(radarr.get("refresh_debounce_seconds", 15)))

    sonarr_default_url = str(_require(sonarr, "url")).rstrip("/") if has_sonarr else ""
    sonarr_default_api_key = str(_require(sonarr, "api_key")) if has_sonarr else ""
    sonarr_url = _env_or_default("LIBRARIARR_SONARR_URL", sonarr_default_url)
    sonarr_api_key = _env_or_default("LIBRARIARR_SONARR_API_KEY", sonarr_default_api_key)
    sonarr_sync_enabled = bool(sonarr.get("sync_enabled", True if has_sonarr else False))
    sonarr_auto_add_unmatched = bool(sonarr.get("auto_add_unmatched", False))
    sonarr_auto_add_quality_profile_raw = sonarr.get("auto_add_quality_profile_id")
    sonarr_auto_add_quality_profile_id = (
        int(sonarr_auto_add_quality_profile_raw)
        if sonarr_auto_add_quality_profile_raw is not None
        else None
    )
    sonarr_auto_add_language_profile_raw = sonarr.get("auto_add_language_profile_id")
    sonarr_auto_add_language_profile_id = (
        int(sonarr_auto_add_language_profile_raw)
        if sonarr_auto_add_language_profile_raw is not None
        else None
    )
    sonarr_auto_add_search_on_add = bool(sonarr.get("auto_add_search_on_add", False))
    sonarr_auto_add_monitored = bool(sonarr.get("auto_add_monitored", True))
    sonarr_auto_add_season_folder = bool(sonarr.get("auto_add_season_folder", True))
    sonarr_request_timeout_seconds = max(1, int(sonarr.get("request_timeout_seconds", 30)))
    sonarr_request_retry_attempts = max(0, int(sonarr.get("request_retry_attempts", 2)))
    sonarr_request_retry_backoff_seconds = max(
        0.0,
        float(sonarr.get("request_retry_backoff_seconds", 0.5)),
    )
    sonarr_refresh_debounce_seconds = max(0, int(sonarr.get("refresh_debounce_seconds", 15)))

    quality_map_raw = radarr_mapping_raw.get("quality_map", [])
    for item in quality_map_raw:
        if "target_id" not in item:
            raise ValueError(
                "radarr.mapping.quality_map entries must define target_id; "
                "legacy 'id' is not supported"
            )
    quality_map = [
        QualityRule(
            match=item.get("match", []),
            target_id=int(item["target_id"]),
        )
        for item in quality_map_raw
    ]

    custom_format_map_raw = radarr_mapping_raw.get("custom_format_map", [])
    for item in custom_format_map_raw:
        if "format_id" not in item:
            raise ValueError(
                "radarr.mapping.custom_format_map entries must define format_id; "
                "legacy 'format' is not supported"
            )
    custom_format_map = [
        CustomFormatRule(
            match=item.get("match", []),
            format_id=int(item["format_id"]),
        )
        for item in custom_format_map_raw
    ]

    sonarr_quality_profile_map_raw = sonarr_mapping_raw.get("quality_profile_map", [])
    for item in sonarr_quality_profile_map_raw:
        if "profile_id" not in item:
            raise ValueError(
                "sonarr.mapping.quality_profile_map entries must define profile_id; "
                "legacy 'id' is not supported"
            )
    sonarr_quality_profile_map = [
        ProfileRule(
            match=item.get("match", []),
            profile_id=int(item["profile_id"]),
        )
        for item in sonarr_quality_profile_map_raw
    ]

    sonarr_language_profile_map_raw = sonarr_mapping_raw.get("language_profile_map", [])
    for item in sonarr_language_profile_map_raw:
        if "profile_id" not in item:
            raise ValueError(
                "sonarr.mapping.language_profile_map entries must define profile_id; "
                "legacy 'id' is not supported"
            )
    sonarr_language_profile_map = [
        ProfileRule(
            match=item.get("match", []),
            profile_id=int(item["profile_id"]),
        )
        for item in sonarr_language_profile_map_raw
    ]

    cleanup_raw = raw.get("cleanup", {})
    configured_sonarr_action = str(cleanup_raw.get("sonarr_action_on_missing", "")).strip().lower()
    if configured_sonarr_action and configured_sonarr_action not in {"none", "unmonitor", "delete"}:
        raise ValueError("cleanup.sonarr_action_on_missing must be one of: none, unmonitor, delete")

    resolved_sonarr_missing_action = configured_sonarr_action or "unmonitor"

    missing_grace_seconds = max(0, int(cleanup_raw.get("missing_grace_seconds", 3600)))
    runtime_raw = raw.get("runtime", {})
    normalized_scan_video_extensions = _normalize_extensions(
        runtime_raw.get("scan_video_extensions"),
        key_name="runtime.scan_video_extensions",
        default_values=list(DEFAULT_SCAN_VIDEO_EXTENSIONS),
    )

    managed_video_extensions = _normalize_extensions(
        projection_raw.get("managed_video_extensions"),
        key_name="radarr.projection.managed_video_extensions",
        default_values=list(DEFAULT_SCAN_VIDEO_EXTENSIONS),
    )
    managed_extras_allowlist_raw = projection_raw.get("managed_extras_allowlist")
    if managed_extras_allowlist_raw is None:
        managed_extras_allowlist = ["*.srt", "*.sub", "movie.nfo", "poster.jpg", "fanart.jpg"]
    elif isinstance(managed_extras_allowlist_raw, list):
        managed_extras_allowlist = [
            str(item).strip() for item in managed_extras_allowlist_raw if str(item).strip()
        ]
    else:
        raise ValueError("radarr.projection.managed_extras_allowlist must be a list")

    movie_folder_name_source = str(
        projection_raw.get("movie_folder_name_source", "managed")
    ).strip()
    if movie_folder_name_source not in {"managed", "radarr"}:
        raise ValueError(
            "radarr.projection.movie_folder_name_source must be one of: managed, radarr"
        )

    preserve_unknown_files = bool(projection_raw.get("preserve_unknown_files", True))
    if not preserve_unknown_files:
        preserve_unknown_files = True

    sonarr_managed_video_extensions = _normalize_extensions(
        sonarr_projection_raw.get("managed_video_extensions"),
        key_name="sonarr.projection.managed_video_extensions",
        default_values=list(DEFAULT_SCAN_VIDEO_EXTENSIONS),
    )
    sonarr_managed_extras_allowlist_raw = sonarr_projection_raw.get("managed_extras_allowlist")
    if sonarr_managed_extras_allowlist_raw is None:
        sonarr_managed_extras_allowlist = [
            "*.srt",
            "*.ass",
            "*.sub",
            "series.nfo",
            "tvshow.nfo",
            "poster.jpg",
            "fanart.jpg",
        ]
    elif isinstance(sonarr_managed_extras_allowlist_raw, list):
        sonarr_managed_extras_allowlist = [
            str(item).strip() for item in sonarr_managed_extras_allowlist_raw if str(item).strip()
        ]
    else:
        raise ValueError("sonarr.projection.managed_extras_allowlist must be a list")

    series_folder_name_source = str(
        sonarr_projection_raw.get("series_folder_name_source", "managed")
    ).strip()
    if series_folder_name_source not in {"managed", "sonarr"}:
        raise ValueError(
            "sonarr.projection.series_folder_name_source must be one of: managed, sonarr"
        )

    sonarr_preserve_unknown_files = bool(sonarr_projection_raw.get("preserve_unknown_files", True))
    if not sonarr_preserve_unknown_files:
        sonarr_preserve_unknown_files = True

    periodic_reconcile_minutes = runtime_raw.get(
        "periodic_reconcile_minutes",
        runtime_raw.get("maintenance_interval_minutes", 1440),
    )

    runtime = RuntimeConfig(
        debounce_seconds=int(runtime_raw.get("debounce_seconds", 8)),
        maintenance_interval_minutes=int(periodic_reconcile_minutes),
        arr_root_poll_interval_minutes=int(runtime_raw.get("arr_root_poll_interval_minutes", 1)),
        auto_add_batch_size=max(1, int(runtime_raw.get("auto_add_batch_size", 150))),
        scan_video_extensions=normalized_scan_video_extensions,
    )

    analysis_raw = raw.get("analysis", {})
    analysis = AnalysisConfig(
        use_nfo=bool(analysis_raw.get("use_nfo", False)),
        use_media_probe=bool(analysis_raw.get("use_media_probe", False)),
        media_probe_bin=str(analysis_raw.get("media_probe_bin", "ffprobe")),
    )

    if "ingest" in raw:
        raise ValueError("ingest section is no longer supported in projection-only mode")

    return AppConfig(
        paths=PathsConfig(
            series_root_mappings=series_root_mappings,
            movie_root_mappings=movie_root_mappings,
            exclude_paths=exclude_paths,
        ),
        radarr=RadarrConfig(
            enabled=radarr_enabled,
            url=radarr_url,
            api_key=radarr_api_key,
            sync_enabled=sync_enabled,
            refresh_debounce_seconds=refresh_debounce_seconds,
            auto_add_unmatched=auto_add_unmatched,
            auto_add_quality_profile_id=auto_add_quality_profile_id,
            auto_add_search_on_add=auto_add_search_on_add,
            auto_add_monitored=auto_add_monitored,
            request_timeout_seconds=request_timeout_seconds,
            request_retry_attempts=request_retry_attempts,
            request_retry_backoff_seconds=request_retry_backoff_seconds,
            projection=RadarrProjectionConfig(
                managed_video_extensions=managed_video_extensions,
                managed_extras_allowlist=managed_extras_allowlist,
                preserve_unknown_files=preserve_unknown_files,
                delete_managed_files=bool(projection_raw.get("delete_managed_files", True)),
                provenance_file=str(
                    projection_raw.get("provenance_file", ".librariarr-provenance.json")
                ).strip()
                or ".librariarr-provenance.json",
                hash_max_file_size_mb=max(
                    1,
                    int(projection_raw.get("hash_max_file_size_mb", 256)),
                ),
                movie_folder_name_source=movie_folder_name_source,
            ),
            mapping=RadarrMappingConfig(
                quality_map=quality_map,
                custom_format_map=custom_format_map,
            ),
        ),
        sonarr=SonarrConfig(
            enabled=sonarr_enabled,
            url=sonarr_url,
            api_key=sonarr_api_key,
            sync_enabled=sonarr_sync_enabled,
            refresh_debounce_seconds=sonarr_refresh_debounce_seconds,
            auto_add_unmatched=sonarr_auto_add_unmatched,
            auto_add_quality_profile_id=sonarr_auto_add_quality_profile_id,
            auto_add_language_profile_id=sonarr_auto_add_language_profile_id,
            auto_add_search_on_add=sonarr_auto_add_search_on_add,
            auto_add_monitored=sonarr_auto_add_monitored,
            auto_add_season_folder=sonarr_auto_add_season_folder,
            request_timeout_seconds=sonarr_request_timeout_seconds,
            request_retry_attempts=sonarr_request_retry_attempts,
            request_retry_backoff_seconds=sonarr_request_retry_backoff_seconds,
            projection=SonarrProjectionConfig(
                managed_video_extensions=sonarr_managed_video_extensions,
                managed_extras_allowlist=sonarr_managed_extras_allowlist,
                preserve_unknown_files=sonarr_preserve_unknown_files,
                delete_managed_files=bool(sonarr_projection_raw.get("delete_managed_files", True)),
                provenance_file=str(
                    sonarr_projection_raw.get(
                        "provenance_file",
                        ".librariarr-sonarr-provenance.json",
                    )
                ).strip()
                or ".librariarr-sonarr-provenance.json",
                hash_max_file_size_mb=max(
                    1,
                    int(sonarr_projection_raw.get("hash_max_file_size_mb", 256)),
                ),
                series_folder_name_source=series_folder_name_source,
            ),
            mapping=SonarrMappingConfig(
                quality_profile_map=sonarr_quality_profile_map,
                language_profile_map=sonarr_language_profile_map,
            ),
        ),
        cleanup=CleanupConfig(
            remove_orphaned_links=bool(cleanup_raw.get("remove_orphaned_links", True)),
            sonarr_action_on_missing=resolved_sonarr_missing_action,
            missing_grace_seconds=missing_grace_seconds,
        ),
        runtime=runtime,
        analysis=analysis,
    )
