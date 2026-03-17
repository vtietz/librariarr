from __future__ import annotations

from dataclasses import dataclass, field

from .defaults import DEFAULT_SCAN_VIDEO_EXTENSIONS


@dataclass
class QualityRule:
    match: list[str]
    target_id: int


@dataclass
class CustomFormatRule:
    match: list[str]
    format_id: int


@dataclass
class ProfileRule:
    match: list[str]
    profile_id: int


@dataclass
class RadarrMappingConfig:
    quality_map: list[QualityRule] = field(default_factory=list)
    custom_format_map: list[CustomFormatRule] = field(default_factory=list)


@dataclass
class SonarrMappingConfig:
    quality_profile_map: list[ProfileRule] = field(default_factory=list)
    language_profile_map: list[ProfileRule] = field(default_factory=list)


@dataclass
class CleanupConfig:
    remove_orphaned_links: bool = True
    radarr_action_on_missing: str = "unmonitor"
    sonarr_action_on_missing: str = "unmonitor"
    missing_grace_seconds: int = 3600


@dataclass
class RuntimeConfig:
    debounce_seconds: int = 8
    maintenance_interval_minutes: int = 1440
    arr_root_poll_interval_minutes: int = 1
    scan_video_extensions: list[str] | None = field(
        default_factory=lambda: list(DEFAULT_SCAN_VIDEO_EXTENSIONS)
    )


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
    path_update_match_policy: str = "default"
    mapping: RadarrMappingConfig = field(default_factory=RadarrMappingConfig)


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
    mapping: SonarrMappingConfig = field(default_factory=SonarrMappingConfig)


@dataclass
class RootMapping:
    nested_root: str
    shadow_root: str


@dataclass
class PathsConfig:
    root_mappings: list[RootMapping] = field(default_factory=list)
    exclude_paths: list[str] = field(default_factory=list)


@dataclass
class AppConfig:
    paths: PathsConfig
    radarr: RadarrConfig
    cleanup: CleanupConfig
    runtime: RuntimeConfig
    sonarr: SonarrConfig = field(default_factory=SonarrConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)

    def effective_radarr_quality_map(self) -> list[QualityRule]:
        return self.radarr.mapping.quality_map

    def effective_radarr_custom_format_map(self) -> list[CustomFormatRule]:
        return self.radarr.mapping.custom_format_map

    def effective_sonarr_quality_profile_map(self) -> list[ProfileRule]:
        return self.sonarr.mapping.quality_profile_map

    def effective_sonarr_language_profile_map(self) -> list[ProfileRule]:
        return self.sonarr.mapping.language_profile_map
