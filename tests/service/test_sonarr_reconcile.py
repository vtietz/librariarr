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


def _make_config(
    managed_root: Path,
    library_root: Path,
    *,
    sonarr_sync_enabled: bool,
) -> AppConfig:
    return AppConfig(
        paths=PathsConfig(
            root_mappings=[
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
