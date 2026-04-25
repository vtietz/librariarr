import logging
from pathlib import Path

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    PathsConfig,
    ProfileRule,
    RadarrConfig,
    RootMapping,
    RuntimeConfig,
    SonarrConfig,
    SonarrMappingConfig,
)
from librariarr.sync.sonarr_helper import SonarrSyncHelper


class _FakeSonarr:
    def __init__(
        self,
        *,
        quality_profiles: list[dict] | None = None,
        language_profiles: list[dict] | None = None,
        lookup_results: list[dict] | None = None,
        series: list[dict] | None = None,
    ) -> None:
        self._quality_profiles = quality_profiles or []
        self._language_profiles = language_profiles or []
        self._lookup_results = lookup_results or []
        self._series = series or []
        self.add_calls: list[dict] = []
        self.update_calls: list[tuple[int, str]] = []

    def get_quality_profiles(self) -> list[dict]:
        return self._quality_profiles

    def get_language_profiles(self) -> list[dict]:
        return self._language_profiles

    def lookup_series(self, _term: str) -> list[dict]:
        return self._lookup_results

    def get_series(self) -> list[dict]:
        return self._series

    def update_series_path(self, series: dict, new_path: str) -> bool:
        self.update_calls.append((int(series.get("id") or 0), new_path))
        if str(series.get("path") or "").strip() == new_path:
            return False
        series["path"] = new_path
        return True

    def add_series_from_lookup(
        self,
        candidate: dict,
        *,
        path: str,
        root_folder_path: str,
        quality_profile_id: int,
        language_profile_id: int,
        monitored: bool,
        search_for_missing_episodes: bool,
        season_folder: bool,
    ) -> dict:
        self.add_calls.append(
            {
                "candidate": candidate,
                "path": path,
                "root_folder_path": root_folder_path,
                "quality_profile_id": quality_profile_id,
                "language_profile_id": language_profile_id,
                "monitored": monitored,
                "search_for_missing_episodes": search_for_missing_episodes,
                "season_folder": season_folder,
            }
        )
        payload = {
            "id": 999,
            "title": str(candidate.get("title") or ""),
            "path": path,
            "tvdbId": candidate.get("tvdbId"),
        }
        self._series.append(payload)
        return payload


def _make_config(
    tmp_path: Path,
    *,
    quality_map: list[ProfileRule] | None = None,
    language_map: list[ProfileRule] | None = None,
    auto_add_quality_profile_id: int | None = None,
    auto_add_language_profile_id: int | None = None,
) -> AppConfig:
    nested_root = tmp_path / "series"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir(parents=True, exist_ok=True)
    shadow_root.mkdir(parents=True, exist_ok=True)

    return AppConfig(
        paths=PathsConfig(
            series_root_mappings=[
                RootMapping(nested_root=str(nested_root), shadow_root=str(shadow_root))
            ]
        ),
        radarr=RadarrConfig(url="http://radarr:7878", api_key="test"),
        sonarr=SonarrConfig(
            enabled=True,
            url="http://sonarr:8989",
            api_key="test",
            auto_add_quality_profile_id=auto_add_quality_profile_id,
            auto_add_language_profile_id=auto_add_language_profile_id,
            mapping=SonarrMappingConfig(
                quality_profile_map=quality_map or [],
                language_profile_map=language_map or [],
            ),
        ),
        cleanup=CleanupConfig(),
        runtime=RuntimeConfig(),
    )


def test_resolve_language_profile_falls_back_when_mapped_id_unavailable(tmp_path: Path) -> None:
    folder = tmp_path / "Series German (2023)"
    folder.mkdir()

    config = _make_config(
        tmp_path,
        language_map=[ProfileRule(match=["german"], profile_id=6)],
    )
    fake = _FakeSonarr(
        quality_profiles=[{"id": 4, "name": "HD-1080p"}],
        language_profiles=[{"id": 1, "name": "Deprecated"}],
    )
    helper = SonarrSyncHelper(
        config=config,
        logger=logging.getLogger(__name__),
        get_sonarr_client=lambda: fake,
    )

    profile_id = helper._resolve_auto_add_language_profile_id(folder)

    assert profile_id == 1


def test_resolve_quality_profile_falls_back_when_mapped_id_unavailable(tmp_path: Path) -> None:
    folder = tmp_path / "Series 2160p x265 (2023)"
    folder.mkdir()

    config = _make_config(
        tmp_path,
        quality_map=[ProfileRule(match=["2160p", "x265"], profile_id=99)],
    )
    fake = _FakeSonarr(
        quality_profiles=[{"id": 4, "name": "HD-1080p"}, {"id": 5, "name": "Ultra-HD"}],
        language_profiles=[{"id": 1, "name": "Deprecated"}],
    )
    helper = SonarrSyncHelper(
        config=config,
        logger=logging.getLogger(__name__),
        get_sonarr_client=lambda: fake,
    )

    profile_id = helper._resolve_auto_add_quality_profile_id(folder)

    assert profile_id == 4


def test_resolve_language_profile_falls_back_when_configured_id_unavailable(tmp_path: Path) -> None:
    folder = tmp_path / "Series Alpha (2021)"
    folder.mkdir()

    config = _make_config(tmp_path, auto_add_language_profile_id=4)
    fake = _FakeSonarr(
        quality_profiles=[{"id": 4, "name": "HD-1080p"}],
        language_profiles=[{"id": 1, "name": "Deprecated"}],
    )
    helper = SonarrSyncHelper(
        config=config,
        logger=logging.getLogger(__name__),
        get_sonarr_client=lambda: fake,
    )

    profile_id = helper._resolve_auto_add_language_profile_id(folder)

    assert profile_id == 1


def test_auto_add_series_uses_shadow_target_path(tmp_path: Path) -> None:
    managed_root = tmp_path / "series"
    shadow_root = tmp_path / "shadow"
    folder = managed_root / "Fixture Auto Series (2022)"
    folder.mkdir(parents=True)
    shadow_root.mkdir(parents=True, exist_ok=True)

    config = _make_config(
        tmp_path,
        auto_add_quality_profile_id=4,
        auto_add_language_profile_id=1,
    )
    fake = _FakeSonarr(
        quality_profiles=[{"id": 4, "name": "HD-1080p"}],
        language_profiles=[{"id": 1, "name": "Deprecated"}],
        lookup_results=[{"title": "Fixture Auto Series", "year": 2022, "tvdbId": 1203}],
        series=[],
    )
    helper = SonarrSyncHelper(
        config=config,
        logger=logging.getLogger(__name__),
        get_sonarr_client=lambda: fake,
    )

    added = helper.auto_add_series_for_folder(folder, managed_root)

    assert isinstance(added, dict)
    assert len(fake.add_calls) == 1
    assert fake.add_calls[0]["path"] == str(shadow_root / folder.name)
    assert fake.add_calls[0]["root_folder_path"] == str(shadow_root)


def test_auto_add_series_skips_add_when_series_already_exists(tmp_path: Path) -> None:
    managed_root = tmp_path / "series"
    shadow_root = tmp_path / "shadow"
    folder = managed_root / "Fixture Auto Series (2022)"
    folder.mkdir(parents=True)
    shadow_root.mkdir(parents=True, exist_ok=True)

    existing = {
        "id": 77,
        "title": "Fixture Auto Series",
        "tvdbId": 1203,
        "path": str(shadow_root / folder.name),
    }
    config = _make_config(
        tmp_path,
        auto_add_quality_profile_id=4,
        auto_add_language_profile_id=1,
    )
    fake = _FakeSonarr(
        quality_profiles=[{"id": 4, "name": "HD-1080p"}],
        language_profiles=[{"id": 1, "name": "Deprecated"}],
        lookup_results=[{"title": "Fixture Auto Series", "year": 2022, "tvdbId": 1203}],
        series=[existing],
    )
    helper = SonarrSyncHelper(
        config=config,
        logger=logging.getLogger(__name__),
        get_sonarr_client=lambda: fake,
    )

    added = helper.auto_add_series_for_folder(folder, managed_root)

    assert added == existing
    assert fake.add_calls == []
    assert fake.update_calls == []


def test_auto_add_series_updates_existing_series_path_when_mismatched(tmp_path: Path) -> None:
    managed_root = tmp_path / "series"
    shadow_root = tmp_path / "shadow"
    folder = managed_root / "Fixture Auto Series (2022)"
    folder.mkdir(parents=True)
    shadow_root.mkdir(parents=True, exist_ok=True)

    existing = {
        "id": 77,
        "title": "Fixture Auto Series",
        "tvdbId": 1203,
        "path": "/data/sonarr_library/age_06/Fixture Auto Series (2022)",
    }
    config = _make_config(
        tmp_path,
        auto_add_quality_profile_id=4,
        auto_add_language_profile_id=1,
    )
    fake = _FakeSonarr(
        quality_profiles=[{"id": 4, "name": "HD-1080p"}],
        language_profiles=[{"id": 1, "name": "Deprecated"}],
        lookup_results=[{"title": "Fixture Auto Series", "year": 2022, "tvdbId": 1203}],
        series=[existing],
    )
    helper = SonarrSyncHelper(
        config=config,
        logger=logging.getLogger(__name__),
        get_sonarr_client=lambda: fake,
    )

    added = helper.auto_add_series_for_folder(folder, managed_root)

    assert isinstance(added, dict)
    assert added.get("path") == str(shadow_root / folder.name)
    assert fake.add_calls == []
    assert fake.update_calls == [(77, str(shadow_root / folder.name))]


def _make_multi_root_config(tmp_path: Path) -> AppConfig:
    """Config with two series managed roots in priority order: age_00 > age_06."""
    age_00 = tmp_path / "series" / "age_00"
    age_06 = tmp_path / "series" / "age_06"
    shadow_00 = tmp_path / "shadow" / "age_00"
    shadow_06 = tmp_path / "shadow" / "age_06"
    for d in (age_00, age_06, shadow_00, shadow_06):
        d.mkdir(parents=True, exist_ok=True)

    return AppConfig(
        paths=PathsConfig(
            series_root_mappings=[
                RootMapping(nested_root=str(age_00), shadow_root=str(shadow_00)),
                RootMapping(nested_root=str(age_06), shadow_root=str(shadow_06)),
            ],
        ),
        radarr=RadarrConfig(url="http://radarr:7878", api_key="test"),
        sonarr=SonarrConfig(
            enabled=True,
            url="http://sonarr:8989",
            api_key="test",
            auto_add_quality_profile_id=4,
            auto_add_language_profile_id=1,
        ),
        cleanup=CleanupConfig(),
        runtime=RuntimeConfig(),
    )


def test_auto_add_series_skips_path_update_when_existing_has_higher_root_priority(
    tmp_path: Path,
) -> None:
    """Duplicate series folder in age_06 must not flip the path away from age_00."""
    config = _make_multi_root_config(tmp_path)
    age_00_folder = tmp_path / "series" / "age_00" / "Fixture Series (2023)"
    age_06_folder = tmp_path / "series" / "age_06" / "Fixture Series (2023)"
    age_00_folder.mkdir(parents=True)
    age_06_folder.mkdir(parents=True)

    existing = {
        "id": 55,
        "title": "Fixture Series",
        "tvdbId": 4567,
        "path": str(age_00_folder),
    }
    fake = _FakeSonarr(
        quality_profiles=[{"id": 4, "name": "HD-1080p"}],
        language_profiles=[{"id": 1, "name": "Deprecated"}],
        lookup_results=[{"title": "Fixture Series", "year": 2023, "tvdbId": 4567}],
        series=[existing],
    )
    helper = SonarrSyncHelper(
        config=config,
        logger=logging.getLogger(__name__),
        get_sonarr_client=lambda: fake,
    )

    result = helper.auto_add_series_for_folder(age_06_folder, age_06_folder.parent)

    assert isinstance(result, dict)
    assert result.get("path") == str(age_00_folder)
    assert fake.update_calls == []
    assert fake.add_calls == []


def test_auto_add_series_updates_path_when_new_folder_has_higher_root_priority(
    tmp_path: Path,
) -> None:
    """When canonical age_00 folder appears, the path SHOULD be updated."""
    config = _make_multi_root_config(tmp_path)
    age_00_folder = tmp_path / "series" / "age_00" / "Fixture Series (2023)"
    age_06_folder = tmp_path / "series" / "age_06" / "Fixture Series (2023)"
    age_00_folder.mkdir(parents=True)
    age_06_folder.mkdir(parents=True)

    existing = {
        "id": 55,
        "title": "Fixture Series",
        "tvdbId": 4567,
        "path": str(age_06_folder),
    }
    fake = _FakeSonarr(
        quality_profiles=[{"id": 4, "name": "HD-1080p"}],
        language_profiles=[{"id": 1, "name": "Deprecated"}],
        lookup_results=[{"title": "Fixture Series", "year": 2023, "tvdbId": 4567}],
        series=[existing],
    )
    helper = SonarrSyncHelper(
        config=config,
        logger=logging.getLogger(__name__),
        get_sonarr_client=lambda: fake,
    )

    result = helper.auto_add_series_for_folder(age_00_folder, age_00_folder.parent)

    assert isinstance(result, dict)
    expected = tmp_path / "shadow" / "age_00" / "Fixture Series (2023)"
    assert result.get("path") == str(expected)
    assert fake.update_calls == [(55, str(expected))]
    assert fake.add_calls == []
