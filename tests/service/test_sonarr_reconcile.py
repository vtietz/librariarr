from pathlib import Path

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    PathsConfig,
    RadarrConfig,
    RootMapping,
    RuntimeConfig,
    SonarrConfig,
)
from librariarr.service import LibrariArrService


class FakeSonarr:
    def __init__(
        self,
        series: list[dict] | None = None,
        quality_profiles: list[dict] | None = None,
        language_profiles: list[dict] | None = None,
        lookup_results: list[dict] | None = None,
        add_series_result: dict | None = None,
        root_folders: list[dict] | None = None,
    ) -> None:
        self.series = series or []
        self.quality_profiles = quality_profiles or []
        self.language_profiles = language_profiles or []
        self.lookup_results = lookup_results or []
        self.add_series_result = add_series_result or {}
        self.root_folders = root_folders
        self.updated_paths: list[tuple[int, str]] = []
        self.refreshed: list[int] = []
        self.lookup_terms: list[str] = []
        self.added_series: list[dict] = []
        self.get_series_calls = 0

    def get_series(self) -> list[dict]:
        self.get_series_calls += 1
        return self.series

    def get_system_status(self) -> dict:
        return {"appName": "Sonarr", "version": "0.0.0-test"}

    def get_quality_profiles(self) -> list[dict]:
        return self.quality_profiles

    def get_language_profiles(self) -> list[dict]:
        return self.language_profiles

    def get_root_folders(self) -> list[dict]:
        if self.root_folders is None:
            raise NotImplementedError
        return self.root_folders

    def lookup_series(self, term: str) -> list[dict]:
        self.lookup_terms.append(term)
        return self.lookup_results

    def add_series_from_lookup(
        self,
        lookup_series: dict,
        path: str,
        root_folder_path: str,
        quality_profile_id: int,
        language_profile_id: int | None,
        monitored: bool,
        season_folder: bool,
        search_for_missing_episodes: bool,
    ) -> dict:
        self.added_series.append(
            {
                "lookup_series": lookup_series,
                "path": path,
                "root_folder_path": root_folder_path,
                "quality_profile_id": quality_profile_id,
                "language_profile_id": language_profile_id,
                "monitored": monitored,
                "season_folder": season_folder,
                "search_for_missing_episodes": search_for_missing_episodes,
            }
        )
        return self.add_series_result

    def update_series_path(self, series: dict, new_path: str) -> bool:
        if series.get("path") == new_path:
            return False
        self.updated_paths.append((int(series["id"]), new_path))
        series["path"] = new_path
        return True

    def refresh_series(self, series_id: int, force: bool = False) -> None:
        del force
        self.refreshed.append(series_id)

    def unmonitor_movie(self, movie: dict) -> None:
        del movie

    def delete_movie(
        self,
        movie_id: int,
        delete_files: bool = False,
        add_import_exclusion: bool = False,
    ) -> None:
        del movie_id
        del delete_files
        del add_import_exclusion

    def refresh_movie(self, movie_id: int, force: bool = False) -> bool:
        self.refresh_series(movie_id, force=force)
        return True


def _make_config(
    nested_root: Path,
    shadow_root: Path,
    *,
    sonarr_sync_enabled: bool,
    sonarr_auto_add_unmatched: bool = False,
) -> AppConfig:
    return AppConfig(
        paths=PathsConfig(
            root_mappings=[RootMapping(nested_root=str(nested_root), shadow_root=str(shadow_root))]
        ),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            sync_enabled=False,
        ),
        sonarr=SonarrConfig(
            enabled=True,
            url="http://sonarr:8989",
            api_key="test",
            sync_enabled=sonarr_sync_enabled,
            auto_add_unmatched=sonarr_auto_add_unmatched,
        ),
        quality_map=[],
        cleanup=CleanupConfig(remove_orphaned_links=True, unmonitor_on_delete=True),
        runtime=RuntimeConfig(
            debounce_seconds=1,
            maintenance_interval_minutes=60,
            arr_root_poll_interval_minutes=0,
        ),
    )


def test_reconcile_syncs_sonarr_series_when_enabled(tmp_path: Path) -> None:
    nested_root = tmp_path / "series"
    shadow_root = tmp_path / "sonarr_library"
    series_dir = nested_root / "Fixture Show (2020)"
    season_one = series_dir / "Season 01"
    season_one.mkdir(parents=True)
    (season_one / "Fixture.Show.S01E01.1080p.mkv").write_text("x", encoding="utf-8")

    config = _make_config(nested_root, shadow_root, sonarr_sync_enabled=True)
    service = LibrariArrService(config)

    fake = FakeSonarr(
        series=[
            {
                "id": 1,
                "title": "Fixture Show",
                "year": 2020,
                "path": "/old/path",
                "monitored": True,
            }
        ]
    )
    service.sonarr = fake

    service.reconcile()

    link = shadow_root / "Fixture Show (2020)"
    assert link.is_symlink()
    assert fake.get_series_calls == 1
    assert fake.updated_paths and fake.updated_paths[0][0] == 1
    assert fake.refreshed == [1]


def test_reconcile_skips_sonarr_when_sync_disabled(tmp_path: Path) -> None:
    nested_root = tmp_path / "series"
    shadow_root = tmp_path / "sonarr_library"
    series_dir = nested_root / "Fixture Show (2020)"
    season_one = series_dir / "Season 01"
    season_one.mkdir(parents=True)
    (season_one / "Fixture.Show.S01E01.1080p.mkv").write_text("x", encoding="utf-8")

    config = _make_config(nested_root, shadow_root, sonarr_sync_enabled=False)
    service = LibrariArrService(config)

    fake = FakeSonarr(
        series=[
            {
                "id": 1,
                "title": "Fixture Show",
                "year": 2020,
                "path": "/old/path",
                "monitored": True,
            }
        ]
    )
    service.sonarr = fake

    service.reconcile()

    link = shadow_root / "Fixture Show (2020)"
    assert link.is_symlink()
    assert fake.get_series_calls == 0
    assert fake.updated_paths == []
    assert fake.refreshed == []


def test_reconcile_auto_adds_unmatched_series(tmp_path: Path) -> None:
    nested_root = tmp_path / "series"
    shadow_root = tmp_path / "sonarr_library"
    series_dir = nested_root / "Fixture Show - Alias (2020)"
    season_one = series_dir / "Season 01"
    season_one.mkdir(parents=True)
    (season_one / "Fixture.Show.S01E01.1080p.mkv").write_text("x", encoding="utf-8")

    config = _make_config(
        nested_root,
        shadow_root,
        sonarr_sync_enabled=True,
        sonarr_auto_add_unmatched=True,
    )
    config.runtime.arr_root_poll_interval_minutes = 1
    service = LibrariArrService(config)

    fake = FakeSonarr(
        series=[],
        quality_profiles=[{"id": 3, "name": "HD-1080p"}],
        language_profiles=[{"id": 1, "name": "English"}],
        lookup_results=[{"title": "Fixture Show", "year": 2020, "tvdbId": 12345}],
        add_series_result={
            "id": 10,
            "title": "Fixture Show",
            "year": 2020,
            "path": str(shadow_root / "Fixture Show (2020)"),
            "monitored": True,
        },
    )
    service.sonarr = fake

    service.reconcile()

    link = shadow_root / "Fixture Show (2020)"
    assert link.is_symlink()
    assert fake.lookup_terms == ["fixture show - alias 2020"]
    assert fake.added_series
    assert fake.added_series[0]["quality_profile_id"] == 3
    assert fake.refreshed == [10]


def test_reconcile_skips_sonarr_auto_add_when_root_is_missing(tmp_path: Path) -> None:
    nested_root = tmp_path / "series"
    shadow_root = tmp_path / "sonarr_library"
    series_dir = nested_root / "Fixture Show - Alias (2020)"
    season_one = series_dir / "Season 01"
    season_one.mkdir(parents=True)
    (season_one / "Fixture.Show.S01E01.1080p.mkv").write_text("x", encoding="utf-8")

    config = _make_config(
        nested_root,
        shadow_root,
        sonarr_sync_enabled=True,
        sonarr_auto_add_unmatched=True,
    )
    service = LibrariArrService(config)

    fake = FakeSonarr(
        series=[],
        quality_profiles=[{"id": 3, "name": "HD-1080p"}],
        language_profiles=[{"id": 1, "name": "English"}],
        lookup_results=[{"title": "Fixture Show", "year": 2020, "tvdbId": 12345}],
        add_series_result={
            "id": 10,
            "title": "Fixture Show",
            "year": 2020,
            "path": str(shadow_root / "Fixture Show (2020)"),
            "monitored": True,
        },
        root_folders=[],
    )
    service.sonarr = fake
    service._update_arr_root_folder_availability(force=True)

    service.reconcile()

    assert fake.lookup_terms == []
    assert fake.added_series == []
    assert (shadow_root / "Fixture Show - Alias (2020)").is_symlink()
