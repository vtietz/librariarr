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
class RadarrConfig:
    url: str
    api_key: str
    shadow_root: str = "/data/radarr_library"
    sync_enabled: bool = True


@dataclass
class PathsConfig:
    nested_roots: list[str] = field(default_factory=list)
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
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)


def _require(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise ValueError(f"Missing required config key: {key}")
    return data[key]


def load_config(path: str | Path) -> AppConfig:
    with Path(path).open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    paths = _require(raw, "paths")
    radarr = _require(raw, "radarr")

    nested_roots = paths.get("nested_roots", [])
    root_mappings_raw = paths.get("root_mappings", [])
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
    shadow_root = str(radarr.get("shadow_root", "/data/radarr_library"))
    sync_enabled = bool(radarr.get("sync_enabled", True))

    quality_map = [
        QualityRule(
            match=item.get("match", []),
            target_id=int(item["target_id"] if "target_id" in item else item["id"]),
            name=item.get("name", ""),
        )
        for item in raw.get("quality_map", [])
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

    return AppConfig(
        paths=PathsConfig(nested_roots=list(nested_roots), root_mappings=root_mappings),
        radarr=RadarrConfig(
            url=radarr_url,
            api_key=radarr_api_key,
            shadow_root=shadow_root,
            sync_enabled=sync_enabled,
        ),
        quality_map=quality_map,
        cleanup=CleanupConfig(
            remove_orphaned_links=bool(cleanup_raw.get("remove_orphaned_links", True)),
            unmonitor_on_delete=bool(cleanup_raw.get("unmonitor_on_delete", True)),
            delete_from_radarr_on_missing=delete_from_radarr_on_missing,
        ),
        runtime=runtime,
        analysis=analysis,
    )
