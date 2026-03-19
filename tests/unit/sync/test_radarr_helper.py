import logging
import time
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
        lookup_results: list[dict] | None = None,
        add_movie_result: dict | None = None,
    ) -> None:
        self.quality_profiles = quality_profiles or []
        self.quality_definitions = quality_definitions or []
        self.parse_results = parse_results or {}
        self.lookup_results = lookup_results or []
        self.add_movie_result = add_movie_result or {}
        self.lookup_terms: list[str] = []

    def get_quality_profiles(self) -> list[dict]:
        return self.quality_profiles

    def get_quality_definitions(self) -> list[dict]:
        return self.quality_definitions

    def parse_title(self, title: str) -> dict:
        return self.parse_results.get(title, {})

    def lookup_movies(self, term: str) -> list[dict]:
        self.lookup_terms.append(term)
        return self.lookup_results

    def add_movie_from_lookup(
        self,
        lookup_movie: dict,
        path: str,
        root_folder_path: str,
        quality_profile_id: int,
        monitored: bool,
        search_for_movie: bool,
    ) -> dict:
        del lookup_movie
        del path
        del root_folder_path
        del quality_profile_id
        del monitored
        del search_for_movie
        return self.add_movie_result


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
            series_root_mappings=[
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


def test_canonical_name_from_movie_uses_folder_name(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    helper = RadarrSyncHelper(
        config=config,
        logger=logging.getLogger(__name__),
        get_radarr_client=lambda: FakeRadarr(),
    )

    canonical_name = helper._canonical_name_from_movie(
        {"title": "Face/Off\\Redux", "year": 1997},
        tmp_path / "Face Off Source (1997)",
    )

    assert canonical_name == "Face Off Source (1997)"


def test_auto_add_no_safe_lookup_logs_once_for_unchanged_folder(
    tmp_path: Path,
    caplog,
) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    folder = nested_root / "Unknown Title (2020)"
    folder.mkdir(parents=True)
    (folder / "Unknown.Title.2020.mkv").write_text("x", encoding="utf-8")

    config = _make_config(tmp_path)
    config.radarr.auto_add_quality_profile_id = 7

    fake = FakeRadarr(lookup_results=[])
    helper = RadarrSyncHelper(
        config=config,
        logger=logging.getLogger("librariarr.service"),
        get_radarr_client=lambda: fake,
    )
    caplog.set_level("WARNING", logger="librariarr.service")

    helper.auto_add_movie_for_folder(folder, shadow_root)
    helper.auto_add_movie_for_folder(folder, shadow_root)

    no_safe_matches = [
        record
        for record in caplog.records
        if "No safe Radarr lookup match for folder" in record.getMessage()
    ]
    assert len(no_safe_matches) == 1
    assert fake.lookup_terms == ["unknown title 2020"]


def test_auto_add_retries_no_safe_lookup_when_folder_changes(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    folder = nested_root / "Unknown Title (2020)"
    folder.mkdir(parents=True)
    (folder / "Unknown.Title.2020.mkv").write_text("x", encoding="utf-8")

    config = _make_config(tmp_path)
    config.radarr.auto_add_quality_profile_id = 7

    fake = FakeRadarr(lookup_results=[])
    helper = RadarrSyncHelper(
        config=config,
        logger=logging.getLogger(__name__),
        get_radarr_client=lambda: fake,
    )

    helper.auto_add_movie_for_folder(folder, shadow_root)
    helper.auto_add_movie_for_folder(folder, shadow_root)

    time.sleep(0.01)
    (folder / "new-file.nfo").write_text("changed", encoding="utf-8")

    helper.auto_add_movie_for_folder(folder, shadow_root)

    assert fake.lookup_terms == [
        "unknown title 2020",
        "unknown title 2020",
    ]
