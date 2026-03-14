import logging
from pathlib import Path

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    CustomFormatRule,
    PathsConfig,
    QualityRule,
    RadarrConfig,
    RadarrMappingConfig,
    RootMapping,
    RuntimeConfig,
)
from librariarr.sync.radarr_helper import RadarrSyncHelper


class FakeRadarr:
    def __init__(
        self,
        *,
        quality_profiles: list[dict] | None = None,
        quality_definitions: list[dict] | None = None,
        parse_results: dict[str, dict] | None = None,
    ) -> None:
        self.quality_profiles = quality_profiles or []
        self.quality_definitions = quality_definitions or []
        self.parse_results = parse_results or {}

    def get_quality_profiles(self) -> list[dict]:
        return self.quality_profiles

    def get_quality_definitions(self) -> list[dict]:
        return self.quality_definitions

    def parse_title(self, title: str) -> dict:
        return self.parse_results.get(title, {})


def _make_config(
    tmp_path: Path,
    *,
    quality_map: list[QualityRule] | None = None,
    custom_format_map: list[CustomFormatRule] | None = None,
) -> AppConfig:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir(parents=True, exist_ok=True)
    shadow_root.mkdir(parents=True, exist_ok=True)

    return AppConfig(
        paths=PathsConfig(
            root_mappings=[
                RootMapping(
                    nested_root=str(nested_root),
                    shadow_root=str(shadow_root),
                )
            ]
        ),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test-key",
            sync_enabled=True,
            auto_add_unmatched=True,
            mapping=RadarrMappingConfig(
                quality_map=quality_map or [],
                custom_format_map=custom_format_map or [],
            ),
        ),
        cleanup=CleanupConfig(),
        runtime=RuntimeConfig(),
    )


def test_resolve_auto_add_profile_prefers_custom_format_signal(tmp_path: Path) -> None:
    folder = tmp_path / "Fixture Title - Variant (2017)"
    folder.mkdir()
    (folder / "Fixture.Title.2017.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = _make_config(
        tmp_path,
        quality_map=[QualityRule(match=["1080p", "x265"], target_id=7)],
    )
    fake = FakeRadarr(
        quality_profiles=[
            {
                "id": 1,
                "name": "Any",
                "formatItems": [{"format": 42, "score": 10}],
                "items": [{"quality": {"id": 7}, "allowed": True}],
                "cutoff": {"id": 7},
            },
            {
                "id": 8,
                "name": "Preferred",
                "formatItems": [{"format": 42, "score": 100}],
                "items": [{"quality": {"id": 7}, "allowed": True}],
                "cutoff": {"id": 7},
            },
        ],
        quality_definitions=[{"quality": {"id": 7, "name": "Bluray-1080p"}}],
        parse_results={
            "Fixture Title - Variant (2017)": {
                "customFormats": [{"id": 42, "name": "German Audio"}],
            }
        },
    )
    helper = RadarrSyncHelper(
        config=config,
        logger=logging.getLogger(__name__),
        get_radarr_client=lambda: fake,
    )

    profile_id = helper._resolve_auto_add_quality_profile_id(folder)

    assert profile_id == 8


def test_resolve_auto_add_profile_falls_back_to_lowest_without_signals(tmp_path: Path) -> None:
    folder = tmp_path / "Unknown Title (2020)"
    folder.mkdir()
    (folder / "Unknown.Title.2020.mkv").write_text("x", encoding="utf-8")

    config = _make_config(tmp_path)
    fake = FakeRadarr(
        quality_profiles=[
            {"id": 7, "name": "Profile 7"},
            {"id": 3, "name": "Profile 3"},
        ],
    )
    helper = RadarrSyncHelper(
        config=config,
        logger=logging.getLogger(__name__),
        get_radarr_client=lambda: fake,
    )

    profile_id = helper._resolve_auto_add_quality_profile_id(folder)

    assert profile_id == 3


def test_resolve_auto_add_profile_uses_parse_quality_when_maps_empty(tmp_path: Path) -> None:
    folder = tmp_path / "Fixture Parse Quality (2014)"
    folder.mkdir()
    (folder / "Fixture Parse Quality.2014.1080p.BluRay.mkv").write_text("x", encoding="utf-8")

    config = _make_config(tmp_path)
    fake = FakeRadarr(
        quality_profiles=[
            {
                "id": 3,
                "name": "HD Fallback",
                "cutoff": {"id": 5},
                "items": [{"quality": {"id": 5}, "allowed": True}],
            },
            {
                "id": 7,
                "name": "1080p Profile",
                "cutoff": {"id": 7},
                "items": [{"quality": {"id": 7}, "allowed": True}],
            },
        ],
        quality_definitions=[
            {"quality": {"id": 5, "name": "WEBDL-720p"}},
            {"quality": {"id": 7, "name": "Bluray-1080p"}},
        ],
        parse_results={
            "Fixture Parse Quality (2014)": {
                "quality": {
                    "quality": {"id": 7, "name": "Bluray-1080p"},
                }
            }
        },
    )
    helper = RadarrSyncHelper(
        config=config,
        logger=logging.getLogger(__name__),
        get_radarr_client=lambda: fake,
    )

    profile_id = helper._resolve_auto_add_quality_profile_id(folder)

    assert profile_id == 7


def test_resolve_auto_add_profile_does_not_pick_incompatible_sd_profile(tmp_path: Path) -> None:
    folder = tmp_path / "Localized Fixture (2006)"
    folder.mkdir()
    (folder / "Localized.Fixture.2006.1080p.h265.AC3.mkv").write_text("x", encoding="utf-8")

    config = _make_config(tmp_path)
    fake = FakeRadarr(
        quality_profiles=[
            {
                "id": 2,
                "name": "SD",
                "formatItems": [{"format": 42, "score": 200}],
                "items": [{"quality": {"id": 1}, "allowed": True}],
                "cutoff": {"id": 1},
            },
            {
                "id": 7,
                "name": "1080p German x265",
                "formatItems": [{"format": 42, "score": 100}],
                "items": [{"quality": {"id": 7}, "allowed": True}],
                "cutoff": {"id": 7},
            },
        ],
        quality_definitions=[
            {"quality": {"id": 1, "name": "SDTV"}},
            {"quality": {"id": 7, "name": "Bluray-1080p"}},
        ],
        parse_results={
            "Localized Fixture (2006)": {
                "customFormats": [{"id": 42, "name": "German DL"}],
                "quality": {
                    "quality": {"id": 7, "name": "Bluray-1080p"},
                },
            }
        },
    )
    helper = RadarrSyncHelper(
        config=config,
        logger=logging.getLogger(__name__),
        get_radarr_client=lambda: fake,
    )

    profile_id = helper._resolve_auto_add_quality_profile_id(folder)

    assert profile_id == 7


def test_canonical_name_from_movie_sanitizes_path_separators(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    helper = RadarrSyncHelper(
        config=config,
        logger=logging.getLogger(__name__),
        get_radarr_client=lambda: FakeRadarr(),
    )

    canonical_name = helper._canonical_name_from_movie(
        {"title": "Face/Off\\Redux", "year": 1997},
        tmp_path / "fallback",
    )

    assert canonical_name == "Face-Off-Redux (1997)"
