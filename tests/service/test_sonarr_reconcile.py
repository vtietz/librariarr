from pathlib import Path

import requests

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    PathsConfig,
    RadarrConfig,
    RootMapping,
    RuntimeConfig,
    SonarrConfig,
)
from librariarr.projection import get_sonarr_webhook_queue
from librariarr.service import LibrariArrService


class FakeSonarr:
    def __init__(self, series: list[dict] | None = None) -> None:
        self.series = series or []
        self.get_series_calls = 0

    def get_series(self) -> list[dict]:
        self.get_series_calls += 1
        return self.series

    def get_system_status(self) -> dict:
        return {"appName": "Sonarr", "version": "0.0.0-test"}

    def get_root_folders(self) -> list[dict]:
        return []


class TimeoutSonarr(FakeSonarr):
    def get_series(self) -> list[dict]:
        raise requests.Timeout("read timed out")


class AutoAddFakeSonarr(FakeSonarr):
    def __init__(self, series: list[dict] | None = None) -> None:
        super().__init__(series=series)
        self.lookup_results: list[dict] = []
        self.added_series: list[dict] = []

    def lookup_series(self, term: str) -> list[dict]:
        del term
        return self.lookup_results

    def add_series_from_lookup(
        self,
        lookup_series: dict,
        *,
        path: str,
        root_folder_path: str,
        quality_profile_id: int,
        language_profile_id: int | None,
        monitored: bool,
        season_folder: bool,
        search_for_missing_episodes: bool,
    ) -> dict:
        payload = {
            "lookup_series": lookup_series,
            "path": path,
            "root_folder_path": root_folder_path,
            "quality_profile_id": quality_profile_id,
            "language_profile_id": language_profile_id,
            "monitored": monitored,
            "season_folder": season_folder,
            "search_for_missing_episodes": search_for_missing_episodes,
        }
        self.added_series.append(payload)
        return {
            "id": 903,
            "title": lookup_series.get("title", "Auto Added"),
            "path": path,
        }

    def get_quality_profiles(self) -> list[dict]:
        return [{"id": 8, "name": "HD-1080p"}]

    def get_language_profiles(self) -> list[dict]:
        return [{"id": 3, "name": "German"}]


def _make_config(
    managed_root: Path,
    library_root: Path,
    *,
    sonarr_sync_enabled: bool,
) -> AppConfig:
    return AppConfig(
        paths=PathsConfig(
            series_root_mappings=[
                RootMapping(
                    nested_root=str(managed_root),
                    shadow_root=str(library_root),
                )
            ]
        ),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            enabled=False,
            sync_enabled=False,
        ),
        sonarr=SonarrConfig(
            enabled=True,
            url="http://sonarr:8989",
            api_key="test",
            sync_enabled=sonarr_sync_enabled,
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(
            debounce_seconds=1,
            maintenance_interval_minutes=60,
            arr_root_poll_interval_minutes=0,
        ),
    )


def test_reconcile_projects_sonarr_series_files_when_enabled(tmp_path: Path) -> None:
    managed_root = tmp_path / "series"
    library_root = tmp_path / "sonarr_library"
    series_dir = managed_root / "Fixture Show (2020)"
    season_one = series_dir / "Season 01"
    season_one.mkdir(parents=True)
    source_file = season_one / "Fixture.Show.S01E01.1080p.mkv"
    source_file.write_text("x", encoding="utf-8")

    config = _make_config(managed_root, library_root, sonarr_sync_enabled=True)
    service = LibrariArrService(config)

    fake = FakeSonarr(
        series=[
            {
                "id": 101,
                "title": "Fixture Show",
                "year": 2020,
                "path": str(series_dir),
                "monitored": True,
            }
        ]
    )
    service.sonarr = fake

    service.reconcile()

    projected = library_root / "Fixture Show (2020)" / "Season 01" / source_file.name
    assert projected.exists()
    assert projected.is_file()
    assert source_file.stat().st_ino == projected.stat().st_ino
    assert fake.get_series_calls == 1


def test_reconcile_skips_sonarr_projection_when_sync_disabled(tmp_path: Path) -> None:
    managed_root = tmp_path / "series"
    library_root = tmp_path / "sonarr_library"
    series_dir = managed_root / "Fixture Show (2020)"
    season_one = series_dir / "Season 01"
    season_one.mkdir(parents=True)
    source_file = season_one / "Fixture.Show.S01E01.1080p.mkv"
    source_file.write_text("x", encoding="utf-8")

    config = _make_config(managed_root, library_root, sonarr_sync_enabled=False)
    service = LibrariArrService(config)

    fake = FakeSonarr(
        series=[
            {
                "id": 101,
                "title": "Fixture Show",
                "year": 2020,
                "path": str(series_dir),
                "monitored": True,
            }
        ]
    )
    service.sonarr = fake

    service.reconcile()

    projected = library_root / "Fixture Show (2020)" / "Season 01" / source_file.name
    assert not projected.exists()
    assert fake.get_series_calls == 0


def test_reconcile_continues_when_sonarr_series_fetch_times_out(tmp_path: Path, caplog) -> None:
    managed_root = tmp_path / "series"
    library_root = tmp_path / "sonarr_library"
    series_dir = managed_root / "Fixture Show (2020)"
    season_one = series_dir / "Season 01"
    season_one.mkdir(parents=True)
    (season_one / "Fixture.Show.S01E01.1080p.mkv").write_text("x", encoding="utf-8")

    config = _make_config(managed_root, library_root, sonarr_sync_enabled=True)
    service = LibrariArrService(config)

    service.sonarr = TimeoutSonarr()
    caplog.set_level("WARNING", logger="librariarr.service")

    service.reconcile()

    assert "Continuing reconcile without Sonarr projection" in caplog.text


def test_reconcile_scopes_sonarr_projection_via_webhook_queue(tmp_path: Path) -> None:
    managed_root = tmp_path / "series"
    library_root = tmp_path / "sonarr_library"

    folder_a = managed_root / "Series A (2020)" / "Season 01"
    folder_b = managed_root / "Series B (2021)" / "Season 01"
    folder_a.mkdir(parents=True)
    folder_b.mkdir(parents=True)
    source_a = folder_a / "Series.A.S01E01.1080p.mkv"
    source_b = folder_b / "Series.B.S01E01.1080p.mkv"
    source_a.write_text("a", encoding="utf-8")
    source_b.write_text("b", encoding="utf-8")

    config = _make_config(managed_root, library_root, sonarr_sync_enabled=True)
    service = LibrariArrService(config)

    fake = FakeSonarr(
        series=[
            {
                "id": 201,
                "title": "Series A",
                "year": 2020,
                "path": str(managed_root / "Series A (2020)"),
            },
            {
                "id": 202,
                "title": "Series B",
                "year": 2021,
                "path": str(managed_root / "Series B (2021)"),
            },
        ]
    )
    service.sonarr = fake

    queue = get_sonarr_webhook_queue()
    queue.consume_series_ids()
    queue.enqueue(series_id=202, event_type="EpisodeFile", normalized_path=str(source_b))

    service.reconcile()

    projected_a = library_root / "Series A (2020)" / "Season 01" / source_a.name
    projected_b = library_root / "Series B (2021)" / "Season 01" / source_b.name
    assert not projected_a.exists()
    assert projected_b.exists()


def test_reconcile_logs_scope_resolution_for_sonarr_webhook_scope(tmp_path: Path, caplog) -> None:
    managed_root = tmp_path / "series"
    library_root = tmp_path / "sonarr_library"

    folder = managed_root / "Series B (2021)" / "Season 01"
    folder.mkdir(parents=True)
    source = folder / "Series.B.S01E01.1080p.mkv"
    source.write_text("b", encoding="utf-8")

    config = _make_config(managed_root, library_root, sonarr_sync_enabled=True)
    service = LibrariArrService(config)
    service.sonarr = FakeSonarr(
        series=[
            {
                "id": 202,
                "title": "Series B",
                "year": 2021,
                "path": str(managed_root / "Series B (2021)"),
            },
        ]
    )

    queue = get_sonarr_webhook_queue()
    queue.consume_series_ids()
    queue.enqueue(series_id=202, event_type="EpisodeFile", normalized_path=str(source))

    caplog.set_level("INFO", logger="librariarr.service")
    service.reconcile()

    assert "Reconcile scope resolved:" in caplog.text
    assert "series_scope_kind=scoped" in caplog.text
    assert "series_ids_webhook_count=1" in caplog.text
    assert "Projection dispatch: arr=sonarr" in caplog.text


def test_reconcile_uses_sonarr_title_for_library_folder_when_configured(tmp_path: Path) -> None:
    managed_root = tmp_path / "series"
    library_root = tmp_path / "sonarr_library"
    managed_folder = managed_root / "Fixture Show - Alias (2020)"
    season_one = managed_folder / "Season 01"
    season_one.mkdir(parents=True)
    source_file = season_one / "Fixture.Show.S01E01.1080p.mkv"
    source_file.write_text("x", encoding="utf-8")

    config = _make_config(managed_root, library_root, sonarr_sync_enabled=True)
    config.sonarr.projection.series_folder_name_source = "sonarr"
    service = LibrariArrService(config)

    fake = FakeSonarr(
        series=[
            {
                "id": 301,
                "title": "Fixture Show",
                "year": 2020,
                "path": str(managed_folder),
                "monitored": True,
            }
        ]
    )
    service.sonarr = fake

    service.reconcile()

    projected = library_root / "Fixture Show (2020)" / "Season 01" / source_file.name
    assert projected.exists()


def test_reconcile_auto_adds_unmatched_series_folder_when_enabled(tmp_path: Path) -> None:
    managed_root = tmp_path / "series"
    library_root = tmp_path / "sonarr_library"
    season_one = managed_root / "Fixture Auto Series (2022)" / "Season 01"
    season_one.mkdir(parents=True)
    (season_one / "Fixture.Auto.Series.S01E01.1080p.mkv").write_text("x", encoding="utf-8")

    config = _make_config(managed_root, library_root, sonarr_sync_enabled=True)
    config.sonarr.auto_add_unmatched = True
    config.sonarr.auto_add_quality_profile_id = 8
    config.sonarr.auto_add_language_profile_id = 3
    service = LibrariArrService(config)

    fake = AutoAddFakeSonarr(series=[])
    fake.lookup_results = [{"title": "Fixture Auto Series", "year": 2022, "tvdbId": 1203}]
    service.sonarr = fake

    service.reconcile()

    assert fake.added_series
    assert fake.added_series[0]["quality_profile_id"] == 8
    assert fake.added_series[0]["language_profile_id"] == 3
