from __future__ import annotations

from dataclasses import dataclass
import os
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


@dataclass
class RuntimeConfig:
    debounce_seconds: int = 8
    maintenance_interval_minutes: int = 1440
    scan_video_extensions: list[str] | None = None


@dataclass
class RadarrConfig:
    url: str
    api_key: str
    shadow_root: str = "/data/radarr_library"


@dataclass
class PathsConfig:
    nested_roots: list[str]


@dataclass
class AppConfig:
    paths: PathsConfig
    radarr: RadarrConfig
    quality_map: list[QualityRule]
    cleanup: CleanupConfig
    runtime: RuntimeConfig


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

    env_nested_roots = os.getenv("LIBRARIARR_NESTED_ROOTS")
    if env_nested_roots:
        nested_roots = [part.strip() for part in env_nested_roots.split(",") if part.strip()]

    radarr_url = os.getenv("LIBRARIARR_RADARR_URL", str(_require(radarr, "url")).rstrip("/"))
    radarr_api_key = os.getenv("LIBRARIARR_RADARR_API_KEY", str(_require(radarr, "api_key")))
    shadow_root = os.getenv("LIBRARIARR_SHADOW_ROOT", str(radarr.get("shadow_root", "/data/radarr_library")))

    quality_map = [
        QualityRule(
            match=item.get("match", []),
            target_id=int(item["target_id"] if "target_id" in item else item["id"]),
            name=item.get("name", ""),
        )
        for item in raw.get("quality_map", [])
    ]

    cleanup_raw = raw.get("cleanup", {})
    runtime_raw = raw.get("runtime", {})

    runtime = RuntimeConfig(
        debounce_seconds=int(runtime_raw.get("debounce_seconds", 8)),
        maintenance_interval_minutes=int(runtime_raw.get("maintenance_interval_minutes", 1440)),
        scan_video_extensions=runtime_raw.get("scan_video_extensions"),
    )

    return AppConfig(
        paths=PathsConfig(nested_roots=list(nested_roots)),
        radarr=RadarrConfig(
            url=radarr_url,
            api_key=radarr_api_key,
            shadow_root=shadow_root,
        ),
        quality_map=quality_map,
        cleanup=CleanupConfig(
            remove_orphaned_links=bool(cleanup_raw.get("remove_orphaned_links", True)),
            unmonitor_on_delete=bool(cleanup_raw.get("unmonitor_on_delete", True)),
        ),
        runtime=runtime,
    )
