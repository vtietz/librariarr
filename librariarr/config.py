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
    sync_enabled: bool = True
    auto_add_unmatched: bool = False
    auto_add_quality_profile_id: int | None = None
    auto_add_search_on_add: bool = False
    auto_add_monitored: bool = True


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
    custom_format_map: list[CustomFormatRule] = field(default_factory=list)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)


def _require(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise ValueError(f"Missing required config key: {key}")
    return data[key]


def load_config(path: str | Path) -> AppConfig:
    with Path(path).open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    paths = _require(raw, "paths")
    radarr = _require(raw, "radarr")

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
    radarr_url = os.getenv("LIBRARIARR_RADARR_URL", str(_require(radarr, "url")).rstrip("/"))
    radarr_api_key = os.getenv("LIBRARIARR_RADARR_API_KEY", str(_require(radarr, "api_key")))
    sync_enabled = bool(radarr.get("sync_enabled", True))
    auto_add_unmatched = bool(radarr.get("auto_add_unmatched", False))
    auto_add_quality_profile_raw = radarr.get("auto_add_quality_profile_id")
    auto_add_quality_profile_id = (
        int(auto_add_quality_profile_raw) if auto_add_quality_profile_raw is not None else None
    )
    auto_add_search_on_add = bool(radarr.get("auto_add_search_on_add", False))
    auto_add_monitored = bool(radarr.get("auto_add_monitored", True))

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
    delete_from_radarr_on_missing = bool(cleanup_raw.get("delete_from_radarr_on_missing", False))
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
            url=radarr_url,
            api_key=radarr_api_key,
            sync_enabled=sync_enabled,
            auto_add_unmatched=auto_add_unmatched,
            auto_add_quality_profile_id=auto_add_quality_profile_id,
            auto_add_search_on_add=auto_add_search_on_add,
            auto_add_monitored=auto_add_monitored,
        ),
        quality_map=quality_map,
        cleanup=CleanupConfig(
            remove_orphaned_links=bool(cleanup_raw.get("remove_orphaned_links", True)),
            unmonitor_on_delete=bool(cleanup_raw.get("unmonitor_on_delete", True)),
            delete_from_radarr_on_missing=delete_from_radarr_on_missing,
        ),
        runtime=runtime,
        custom_format_map=custom_format_map,
        analysis=analysis,
        ingest=ingest,
    )
