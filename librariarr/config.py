from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class QualityRule:
    match: list[str]
    target_id: int
    name: str = ""


@dataclass
class CustomFormatRule:
    match: list[str]
    format_id: int
    name: str = ""


@dataclass
class CleanupConfig:
    remove_orphaned_links: bool = True
    unmonitor_on_delete: bool = True
    delete_from_radarr_on_missing: bool = False
    radarr_action_on_missing: str = "unmonitor"
    delete_from_sonarr_on_missing: bool = False
    sonarr_action_on_missing: str = "unmonitor"
    missing_grace_seconds: int = 3600


@dataclass
class RuntimeConfig:
    debounce_seconds: int = 8
    maintenance_interval_minutes: int = 1440
    scan_video_extensions: list[str] | None = None


@dataclass
class AnalysisConfig:
    use_nfo: bool = False
    use_media_probe: bool = False
    media_probe_bin: str = "ffprobe"


@dataclass
class IngestConfig:
    enabled: bool = False
    min_age_seconds: int = 30
    collision_policy: str = "qualify"
    quarantine_root: str = ""


@dataclass
class RadarrConfig:
    url: str
    api_key: str
    enabled: bool = True
    sync_enabled: bool = True
    refresh_debounce_seconds: int = 15
    auto_add_unmatched: bool = False
    auto_add_quality_profile_id: int | None = None
    auto_add_search_on_add: bool = False
    auto_add_monitored: bool = True


@dataclass
class SonarrConfig:
    enabled: bool = False
    url: str = ""
    api_key: str = ""
    sync_enabled: bool = True
    refresh_debounce_seconds: int = 15
    auto_add_unmatched: bool = False
    auto_add_quality_profile_id: int | None = None
    auto_add_language_profile_id: int | None = None
    auto_add_search_on_add: bool = False
    auto_add_monitored: bool = True
    auto_add_season_folder: bool = True


@dataclass
class PathsConfig:
    root_mappings: list[RootMapping] = field(default_factory=list)


@dataclass
class RootMapping:
    nested_root: str
    shadow_root: str


@dataclass
class AppConfig:
    paths: PathsConfig
    radarr: RadarrConfig
    quality_map: list[QualityRule]
    cleanup: CleanupConfig
    runtime: RuntimeConfig
    sonarr: SonarrConfig = field(default_factory=SonarrConfig)
    custom_format_map: list[CustomFormatRule] = field(default_factory=list)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)


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


def _resolve_missing_action(
    cleanup_raw: dict[str, Any],
    action_key: str,
    legacy_delete_key: str,
    unmonitor_on_delete: bool,
) -> tuple[str, bool]:
    configured_action = str(cleanup_raw.get(action_key, "")).strip().lower()
    if configured_action:
        if configured_action not in {"none", "unmonitor", "delete"}:
            raise ValueError(f"cleanup.{action_key} must be one of: none, unmonitor, delete")
        return configured_action, configured_action == "delete"

    delete_on_missing = bool(cleanup_raw.get(legacy_delete_key, False))
    if not unmonitor_on_delete:
        return "none", delete_on_missing
    if delete_on_missing:
        return "delete", delete_on_missing
    return "unmonitor", delete_on_missing


def load_config(path: str | Path) -> AppConfig:
    with Path(path).open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    paths = _require(raw, "paths")
    has_radarr = "radarr" in raw
    has_sonarr = "sonarr" in raw
    if not has_radarr and not has_sonarr:
        raise ValueError("At least one config section is required: radarr or sonarr")

    radarr = raw.get("radarr") or {}
    sonarr = raw.get("sonarr") or {}

    root_mappings_raw = paths.get("root_mappings")
    if not root_mappings_raw:
        raise ValueError(
            "paths.root_mappings is required. The legacy paths.nested_roots mode "
            "has been removed; use paths.root_mappings with per-root shadow_root values."
        )
    root_mappings = [
        RootMapping(
            nested_root=str(_require(item, "nested_root")),
            shadow_root=str(_require(item, "shadow_root")),
        )
        for item in root_mappings_raw
    ]

    # Deployment-only overrides: allow URL and API key from env.
    radarr_default_url = str(_require(radarr, "url")).rstrip("/") if has_radarr else ""
    radarr_default_api_key = str(_require(radarr, "api_key")) if has_radarr else ""
    radarr_url = _env_or_default("LIBRARIARR_RADARR_URL", radarr_default_url)
    radarr_api_key = _env_or_default("LIBRARIARR_RADARR_API_KEY", radarr_default_api_key)
    radarr_enabled = bool(radarr.get("enabled", True if has_radarr else False))
    sync_enabled = radarr_enabled and bool(
        radarr.get("sync_enabled", True if has_radarr else False)
    )
    auto_add_unmatched = radarr_enabled and bool(radarr.get("auto_add_unmatched", False))
    auto_add_quality_profile_raw = radarr.get("auto_add_quality_profile_id")
    auto_add_quality_profile_id = (
        int(auto_add_quality_profile_raw) if auto_add_quality_profile_raw is not None else None
    )
    auto_add_search_on_add = bool(radarr.get("auto_add_search_on_add", False))
    auto_add_monitored = bool(radarr.get("auto_add_monitored", True))
    refresh_debounce_seconds = max(0, int(radarr.get("refresh_debounce_seconds", 15)))

    sonarr_default_url = str(_require(sonarr, "url")).rstrip("/") if has_sonarr else ""
    sonarr_default_api_key = str(_require(sonarr, "api_key")) if has_sonarr else ""
    sonarr_url = _env_or_default("LIBRARIARR_SONARR_URL", sonarr_default_url)
    sonarr_api_key = _env_or_default("LIBRARIARR_SONARR_API_KEY", sonarr_default_api_key)
    sonarr_enabled = bool(sonarr.get("enabled", False if has_sonarr else False))
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
    sonarr_refresh_debounce_seconds = max(0, int(sonarr.get("refresh_debounce_seconds", 15)))

    quality_map = [
        QualityRule(
            match=item.get("match", []),
            target_id=int(item["target_id"] if "target_id" in item else item["id"]),
            name=item.get("name", ""),
        )
        for item in raw.get("quality_map", [])
    ]

    custom_format_map = [
        CustomFormatRule(
            match=item.get("match", []),
            format_id=int(item["format_id"] if "format_id" in item else item["format"]),
            name=item.get("name", ""),
        )
        for item in raw.get("custom_format_map", [])
    ]

    cleanup_raw = raw.get("cleanup", {})
    configured_radarr_action = str(cleanup_raw.get("radarr_action_on_missing", "")).strip().lower()
    configured_sonarr_action = str(cleanup_raw.get("sonarr_action_on_missing", "")).strip().lower()
    if "unmonitor_on_delete" in cleanup_raw:
        unmonitor_on_delete = bool(cleanup_raw.get("unmonitor_on_delete", True))
    elif configured_radarr_action or configured_sonarr_action:
        selected_actions = [
            action for action in (configured_radarr_action, configured_sonarr_action) if action
        ]
        unmonitor_on_delete = any(action in {"unmonitor", "delete"} for action in selected_actions)
    else:
        unmonitor_on_delete = True

    resolved_missing_action, delete_from_radarr_on_missing = _resolve_missing_action(
        cleanup_raw=cleanup_raw,
        action_key="radarr_action_on_missing",
        legacy_delete_key="delete_from_radarr_on_missing",
        unmonitor_on_delete=unmonitor_on_delete,
    )
    resolved_sonarr_missing_action, delete_from_sonarr_on_missing = _resolve_missing_action(
        cleanup_raw=cleanup_raw,
        action_key="sonarr_action_on_missing",
        legacy_delete_key="delete_from_sonarr_on_missing",
        unmonitor_on_delete=unmonitor_on_delete,
    )

    missing_grace_seconds = max(0, int(cleanup_raw.get("missing_grace_seconds", 3600)))
    runtime_raw = raw.get("runtime", {})

    runtime = RuntimeConfig(
        debounce_seconds=int(runtime_raw.get("debounce_seconds", 8)),
        maintenance_interval_minutes=int(runtime_raw.get("maintenance_interval_minutes", 1440)),
        scan_video_extensions=runtime_raw.get("scan_video_extensions"),
    )

    analysis_raw = raw.get("analysis", {})
    analysis = AnalysisConfig(
        use_nfo=bool(analysis_raw.get("use_nfo", False)),
        use_media_probe=bool(analysis_raw.get("use_media_probe", False)),
        media_probe_bin=str(analysis_raw.get("media_probe_bin", "ffprobe")),
    )

    ingest_raw = raw.get("ingest", {})
    collision_policy = str(ingest_raw.get("collision_policy", "qualify")).strip().lower()
    if collision_policy not in {"qualify", "skip"}:
        raise ValueError("ingest.collision_policy must be one of: qualify, skip")

    if "selector" in ingest_raw:
        raise ValueError(
            "ingest.selector is no longer supported; ingest requires a 1:1 "
            "mapping between each shadow root and nested root"
        )

    ingest = IngestConfig(
        enabled=bool(ingest_raw.get("enabled", False)),
        min_age_seconds=max(0, int(ingest_raw.get("min_age_seconds", 30))),
        collision_policy=collision_policy,
        quarantine_root=str(ingest_raw.get("quarantine_root", "")).strip(),
    )

    return AppConfig(
        paths=PathsConfig(root_mappings=root_mappings),
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
        ),
        quality_map=quality_map,
        cleanup=CleanupConfig(
            remove_orphaned_links=bool(cleanup_raw.get("remove_orphaned_links", True)),
            unmonitor_on_delete=unmonitor_on_delete,
            delete_from_radarr_on_missing=delete_from_radarr_on_missing,
            radarr_action_on_missing=resolved_missing_action,
            delete_from_sonarr_on_missing=delete_from_sonarr_on_missing,
            sonarr_action_on_missing=resolved_sonarr_missing_action,
            missing_grace_seconds=missing_grace_seconds,
        ),
        runtime=runtime,
        custom_format_map=custom_format_map,
        analysis=analysis,
        ingest=ingest,
    )
