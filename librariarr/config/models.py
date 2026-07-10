from __future__ import annotations

from dataclasses import dataclass, field

from .defaults import DEFAULT_SCAN_VIDEO_EXTENSIONS


@dataclass
class RuntimeConfig:
    """Loop cadence. Consistency passes are cheap (no tree walk); full passes
    walk the managed roots once and additionally run discovery + prune."""

    debounce_seconds: int = 8
    consistency_interval_seconds: int = 300
    full_interval_minutes: int = 60
    startup_scope: str = "full"  # full | consistency | off


@dataclass
class IngestConfig:
    enabled: bool = True
    replacement_delete_mode: str = "soft"  # soft (quarantine) | hard (delete)


@dataclass
class RadarrProjectionConfig:
    managed_video_extensions: list[str] = field(
        default_factory=lambda: list(DEFAULT_SCAN_VIDEO_EXTENSIONS)
    )
    managed_extras_allowlist: list[str] = field(
        default_factory=lambda: ["*.srt", "*.sub", "movie.nfo", "poster.jpg", "fanart.jpg"]
    )


@dataclass
class SonarrProjectionConfig:
    managed_video_extensions: list[str] = field(
        default_factory=lambda: list(DEFAULT_SCAN_VIDEO_EXTENSIONS)
    )
    managed_extras_allowlist: list[str] = field(
        default_factory=lambda: [
            "*.srt",
            "*.ass",
            "*.sub",
            "series.nfo",
            "tvshow.nfo",
            "poster.jpg",
            "fanart.jpg",
        ]
    )


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
    request_timeout_seconds: int = 120
    request_retry_attempts: int = 1
    request_retry_backoff_seconds: float = 1.0
    projection: RadarrProjectionConfig = field(default_factory=RadarrProjectionConfig)


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
    request_timeout_seconds: int = 120
    request_retry_attempts: int = 2
    request_retry_backoff_seconds: float = 0.5
    projection: SonarrProjectionConfig = field(default_factory=SonarrProjectionConfig)


@dataclass
class RootMapping:
    nested_root: str
    shadow_root: str


@dataclass
class MovieRootMapping:
    managed_root: str
    library_root: str


@dataclass
class PathsConfig:
    series_root_mappings: list[RootMapping] = field(default_factory=list)
    movie_root_mappings: list[MovieRootMapping] = field(default_factory=list)
    exclude_paths: list[str] = field(default_factory=list)


@dataclass
class AppConfig:
    paths: PathsConfig
    radarr: RadarrConfig
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)
    sonarr: SonarrConfig = field(default_factory=SonarrConfig)
