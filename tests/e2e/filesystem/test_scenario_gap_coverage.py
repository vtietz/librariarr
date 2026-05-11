"""Filesystem e2e tests for previously identified scenario coverage gaps."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    IngestConfig,
    MovieRootMapping,
    PathsConfig,
    RadarrConfig,
    RootMapping,
    RuntimeConfig,
    SonarrConfig,
)
from librariarr.config.models import SonarrProjectionConfig
from librariarr.runtime.loop import ReconcileSchedule, RuntimeSyncLoop
from librariarr.service import LibrariArrService


def _movie(movie_id: int, title: str, year: int, path: Path) -> dict:
    return {
        "id": movie_id,
        "title": title,
        "year": year,
        "path": str(path),
        "movieFile": {"id": movie_id * 10},
        "monitored": True,
    }


def _series(series_id: int, title: str, year: int, path: Path) -> dict:
    return {
        "id": series_id,
        "title": title,
        "year": year,
        "path": str(path),
        "monitored": True,
    }


class AutoAddFakeRadarr:
    def __init__(self, movies: list[dict], lookup_sequences: list[list[dict]]) -> None:
        self.movies = movies
        self.lookup_sequences = list(lookup_sequences)
        self.lookup_calls = 0
        self.added_movies: list[dict] = []

    def get_movies(self) -> list[dict]:
        return self.movies

    def get_movies_by_ids(self, movie_ids: list[int] | set[int]) -> list[dict]:
        wanted = {int(mid) for mid in movie_ids}
        return [item for item in self.movies if int(item.get("id", -1)) in wanted]

    def lookup_movies(self, _term: str) -> list[dict]:
        self.lookup_calls += 1
        if self.lookup_sequences:
            return self.lookup_sequences.pop(0)
        return []

    def add_movie_from_lookup(
        self,
        lookup_movie: dict,
        path: str,
        root_folder_path: str,
        quality_profile_id: int,
        monitored: bool,
        search_for_movie: bool,
    ) -> dict:
        del root_folder_path, quality_profile_id, monitored, search_for_movie
        movie_id = int(lookup_movie.get("tmdbId") or (1000 + len(self.movies) + 1))
        title = str(lookup_movie.get("title") or "Auto Added")
        year = int(lookup_movie.get("year") or 0)
        added = {
            "id": movie_id,
            "title": title,
            "year": year,
            "path": path,
            "movieFile": {"id": movie_id * 10},
            "monitored": True,
        }
        self.movies.append(added)
        self.added_movies.append(added)
        return added

    def update_movie_path(self, movie: dict, new_path: str) -> bool:
        movie["path"] = new_path
        return True

    def refresh_movie(self, movie_id: int) -> bool:
        del movie_id
        return True

    def refresh_movies(self, movie_ids: set[int]) -> int:
        return len(movie_ids)


class AutoAddFakeSonarr:
    def __init__(self, series: list[dict], lookup_sequences: list[list[dict]]) -> None:
        self.series = series
        self.lookup_sequences = list(lookup_sequences)
        self.lookup_calls = 0
        self.added_series: list[dict] = []

    def get_series(self) -> list[dict]:
        return self.series

    def get_series_by_ids(self, series_ids: list[int] | set[int]) -> list[dict]:
        wanted = {int(sid) for sid in series_ids}
        return [item for item in self.series if int(item.get("id", -1)) in wanted]

    def lookup_series(self, _term: str) -> list[dict]:
        self.lookup_calls += 1
        if self.lookup_sequences:
            return self.lookup_sequences.pop(0)
        return []

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
        del root_folder_path, quality_profile_id, language_profile_id, monitored
        del season_folder, search_for_missing_episodes
        series_id = int(lookup_series.get("tvdbId") or (2000 + len(self.series) + 1))
        title = str(lookup_series.get("title") or "Auto Added")
        year = int(lookup_series.get("year") or 0)
        added = {
            "id": series_id,
            "title": title,
            "year": year,
            "path": path,
            "monitored": True,
        }
        self.series.append(added)
        self.added_series.append(added)
        return added

    def update_series_path(self, series: dict, new_path: str) -> bool:
        series["path"] = new_path
        return True

    def get_quality_profiles(self) -> list[dict]:
        return [{"id": 8, "name": "HD-1080p"}]

    def get_language_profiles(self) -> list[dict]:
        return [{"id": 3, "name": "German"}]


def _radarr_auto_add_config(managed_root: Path, library_root: Path) -> AppConfig:
    return AppConfig(
        paths=PathsConfig(
            series_root_mappings=[],
            movie_root_mappings=[
                MovieRootMapping(managed_root=str(managed_root), library_root=str(library_root))
            ],
        ),
        radarr=RadarrConfig(
            enabled=True,
            url="http://radarr:7878",
            api_key="test",
            sync_enabled=True,
            auto_add_unmatched=True,
            auto_add_quality_profile_id=7,
        ),
        sonarr=SonarrConfig(enabled=False),
        cleanup=CleanupConfig(),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
        ingest=IngestConfig(enabled=True),
    )


def _sonarr_auto_add_config(
    nested_root: Path,
    shadow_root: Path,
    *,
    projection: SonarrProjectionConfig | None = None,
    ingest_enabled: bool = False,
    ingest_replacement_delete_mode: str = "soft",
) -> AppConfig:
    return AppConfig(
        paths=PathsConfig(
            series_root_mappings=[
                RootMapping(nested_root=str(nested_root), shadow_root=str(shadow_root)),
            ],
            movie_root_mappings=[],
        ),
        radarr=RadarrConfig(enabled=False, url="http://radarr:7878", api_key="test"),
        sonarr=SonarrConfig(
            enabled=True,
            url="http://sonarr:8989",
            api_key="test",
            sync_enabled=True,
            auto_add_unmatched=True,
            auto_add_quality_profile_id=8,
            auto_add_language_profile_id=3,
            projection=projection or SonarrProjectionConfig(),
        ),
        cleanup=CleanupConfig(),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
        ingest=IngestConfig(
            enabled=ingest_enabled,
            replacement_delete_mode=ingest_replacement_delete_mode,
        ),
    )


@pytest.mark.fs_e2e
def test_radarr_auto_add_success_projects_immediately(tmp_path: Path) -> None:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"
    movie_folder = managed_root / "Auto Add Movie (2024)"
    movie_folder.mkdir(parents=True)
    source = movie_folder / "Auto.Add.Movie.2024.1080p.mkv"
    source.write_text("x", encoding="utf-8")

    config = _radarr_auto_add_config(managed_root, library_root)
    service = LibrariArrService(config)
    service.radarr = AutoAddFakeRadarr(
        movies=[],
        lookup_sequences=[[{"title": "Auto Add Movie", "year": 2024, "tmdbId": 12345}]],
    )

    service.reconcile()

    projected = library_root / "Auto Add Movie (2024)" / source.name
    assert projected.exists()
    assert projected.samefile(source)
    assert len(service.radarr.added_movies) == 1


@pytest.mark.fs_e2e
def test_radarr_auto_add_no_match_retries_after_folder_change(tmp_path: Path) -> None:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"
    movie_folder = managed_root / "Retry Movie (2024)"
    movie_folder.mkdir(parents=True)
    source = movie_folder / "Retry.Movie.2024.1080p.mkv"
    source.write_text("x", encoding="utf-8")

    config = _radarr_auto_add_config(managed_root, library_root)
    service = LibrariArrService(config)
    service.radarr = AutoAddFakeRadarr(
        movies=[],
        lookup_sequences=[
            [],
            [{"title": "Retry Movie", "year": 2024, "tmdbId": 22222}],
        ],
    )

    service.reconcile()
    assert len(service.radarr.added_movies) == 0
    assert service.radarr.lookup_calls == 1

    # No folder change: Radarr helper should skip repeated no-match lookup.
    service.reconcile()
    assert len(service.radarr.added_movies) == 0
    assert service.radarr.lookup_calls == 1

    # Folder timestamp changes -> retry should occur.
    (movie_folder / "touch.marker").write_text("changed", encoding="utf-8")
    service.reconcile()

    projected = library_root / "Retry Movie (2024)" / source.name
    assert projected.exists()
    assert projected.samefile(source)
    assert len(service.radarr.added_movies) == 1
    assert service.radarr.lookup_calls == 2


@pytest.mark.fs_e2e
def test_sonarr_auto_add_success_projects_immediately(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    series_folder = nested_root / "Auto Series (2021)"
    season_one = series_folder / "Season 01"
    season_one.mkdir(parents=True)
    source = season_one / "Auto.Series.S01E01.1080p.mkv"
    source.write_text("x", encoding="utf-8")

    config = _sonarr_auto_add_config(nested_root, shadow_root)
    service = LibrariArrService(config)
    service.sonarr = AutoAddFakeSonarr(
        series=[],
        lookup_sequences=[[{"title": "Auto Series", "year": 2021, "tvdbId": 33333}]],
    )

    service.reconcile()

    projected = shadow_root / "Auto Series (2021)" / "Season 01" / source.name
    assert projected.exists()
    assert projected.samefile(source)
    assert len(service.sonarr.added_series) == 1


@pytest.mark.fs_e2e
def test_sonarr_auto_add_no_match_retries_next_cycle(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    series_folder = nested_root / "Retry Series (2022)"
    season_one = series_folder / "Season 01"
    season_one.mkdir(parents=True)
    source = season_one / "Retry.Series.S01E01.1080p.mkv"
    source.write_text("x", encoding="utf-8")

    config = _sonarr_auto_add_config(nested_root, shadow_root)
    service = LibrariArrService(config)
    service.sonarr = AutoAddFakeSonarr(
        series=[],
        lookup_sequences=[[], [{"title": "Retry Series", "year": 2022, "tvdbId": 44444}]],
    )

    service.reconcile()
    assert len(service.sonarr.added_series) == 0
    assert service.sonarr.lookup_calls == 1

    service.reconcile()
    projected = shadow_root / "Retry Series (2022)" / "Season 01" / source.name
    assert projected.exists()
    assert projected.samefile(source)
    assert len(service.sonarr.added_series) == 1
    assert service.sonarr.lookup_calls == 2


@pytest.mark.fs_e2e
def test_sonarr_relink_on_source_replace(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    series_folder = nested_root / "Relink Series (2020)"
    season_one = series_folder / "Season 01"
    season_one.mkdir(parents=True)
    source = season_one / "Relink.Series.S01E01.1080p.mkv"
    source.write_text("original", encoding="utf-8")

    config = _sonarr_auto_add_config(nested_root, shadow_root)
    config.sonarr.auto_add_unmatched = False
    service = LibrariArrService(config)
    service.sonarr = AutoAddFakeSonarr(
        series=[_series(10, "Relink Series", 2020, series_folder)],
        lookup_sequences=[],
    )

    service.reconcile()

    projected = shadow_root / "Relink Series (2020)" / "Season 01" / source.name
    assert projected.exists()
    assert projected.samefile(source)
    original_inode = source.stat().st_ino

    source.unlink()
    source.write_text("upgraded", encoding="utf-8")
    assert source.stat().st_ino != original_inode

    service.reconcile()
    assert projected.exists()
    assert projected.samefile(source)
    assert projected.read_text(encoding="utf-8") == "upgraded"


@pytest.mark.fs_e2e
def test_sonarr_preserve_unknown_true_keeps_existing_dest(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    series_folder = nested_root / "Unknown Policy (2020)"
    season_one = series_folder / "Season 01"
    season_one.mkdir(parents=True)
    source = season_one / "Unknown.Policy.S01E01.1080p.mkv"
    source.write_text("source", encoding="utf-8")

    dest_folder = shadow_root / "Unknown Policy (2020)" / "Season 01"
    dest_folder.mkdir(parents=True)
    existing = dest_folder / source.name
    existing.write_text("user-file", encoding="utf-8")

    config = _sonarr_auto_add_config(
        nested_root,
        shadow_root,
        projection=SonarrProjectionConfig(),
    )
    config.sonarr.auto_add_unmatched = False
    service = LibrariArrService(config)
    service.sonarr = AutoAddFakeSonarr(
        series=[_series(20, "Unknown Policy", 2020, series_folder)],
        lookup_sequences=[],
    )

    service.reconcile()

    assert existing.exists()
    assert existing.samefile(source)


@pytest.mark.fs_e2e
def test_managed_rename_chain_keeps_projection_and_refreshes_stale_state(tmp_path: Path) -> None:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"

    old_folder = managed_root / "Collection A" / "Rename Movie (2024)"
    old_folder.mkdir(parents=True)
    source = old_folder / "Rename.Movie.2024.1080p.mkv"
    source.write_text("x", encoding="utf-8")

    config = _radarr_auto_add_config(managed_root, library_root)
    config.radarr.auto_add_unmatched = False
    service = LibrariArrService(config)
    movie = _movie(31, "Rename Movie", 2024, old_folder)
    service.radarr = AutoAddFakeRadarr(movies=[movie], lookup_sequences=[])

    service.reconcile()
    projected = library_root / "Rename Movie (2024)" / source.name
    assert projected.exists()
    assert projected.samefile(source)

    # Simulate user-managed rename/move while keeping the same inode.
    new_folder_parent = managed_root / "Collection B"
    new_folder_parent.mkdir(parents=True)
    new_folder = new_folder_parent / "Rename Movie (2024)"
    old_folder.rename(new_folder)
    new_source = new_folder / source.name
    movie["path"] = str(new_folder)

    service.reconcile()

    assert projected.exists(), "Projection must survive managed-folder rename flow"
    assert projected.samefile(new_source)


@pytest.mark.fs_e2e
def test_sonarr_full_reconcile_ingests_shadow_folder_to_nested_root(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"

    imported_dir = shadow_root / "Imported Series (2024)"
    imported_dir.mkdir(parents=True)
    imported_file = imported_dir / "Imported.Series.S01E01.1080p.mkv"
    imported_file.write_text("x", encoding="utf-8")

    config = _sonarr_auto_add_config(nested_root, shadow_root, ingest_enabled=True)
    config.sonarr.auto_add_unmatched = False
    service = LibrariArrService(config)
    service.sonarr = AutoAddFakeSonarr(
        series=[_series(99, "Imported Series", 2024, imported_dir)],
        lookup_sequences=[],
    )

    service.reconcile_full()

    nested_file = nested_root / "Imported Series (2024)" / imported_file.name
    assert nested_file.exists()
    assert nested_file.read_text(encoding="utf-8") == "x"


@pytest.mark.fs_e2e
def test_sonarr_file_level_ingest_moves_shadow_files_into_nested_series(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    series_folder = nested_root / "Series Ingest (2021)"
    season_folder = series_folder / "Season 01"
    season_folder.mkdir(parents=True)
    source = season_folder / "Series.Ingest.S01E01.1080p.mkv"
    source.write_text("orig", encoding="utf-8")

    config = _sonarr_auto_add_config(nested_root, shadow_root, ingest_enabled=True)
    config.sonarr.auto_add_unmatched = False
    service = LibrariArrService(config)
    series = _series(101, "Series Ingest", 2021, series_folder)
    service.sonarr = AutoAddFakeSonarr(series=[series], lookup_sequences=[])

    service.reconcile()

    projected_folder = shadow_root / "Series Ingest (2021)" / "Season 01"
    projected_file = projected_folder / source.name
    assert projected_file.exists()
    assert projected_file.samefile(source)

    # Simulate Sonarr still pointing at projection path and a user dropping a new episode there.
    series["path"] = str(shadow_root / "Series Ingest (2021)")
    shadow_new_episode = projected_folder / "Series.Ingest.S01E02.1080p.mkv"
    shadow_new_episode.write_text("new", encoding="utf-8")

    service.reconcile()

    managed_new_episode = season_folder / "Series.Ingest.S01E02.1080p.mkv"
    assert managed_new_episode.exists()
    assert managed_new_episode.read_text(encoding="utf-8") == "new"


@pytest.mark.fs_e2e
def test_sonarr_duplicate_guard_keeps_projection_folder_in_shadow(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    series_folder = nested_root / "No Duplicate (2020)"
    season_folder = series_folder / "Season 01"
    season_folder.mkdir(parents=True)
    source = season_folder / "No.Duplicate.S01E01.1080p.mkv"
    source.write_text("orig", encoding="utf-8")

    config = _sonarr_auto_add_config(nested_root, shadow_root, ingest_enabled=True)
    config.sonarr.auto_add_unmatched = False
    service = LibrariArrService(config)
    series = _series(102, "No Duplicate", 2020, series_folder)
    service.sonarr = AutoAddFakeSonarr(series=[series], lookup_sequences=[])

    service.reconcile()

    projected_folder = shadow_root / "No Duplicate (2020)" / "Season 01"
    projected_file = projected_folder / source.name
    assert projected_file.exists()
    assert projected_file.samefile(source)

    # Simulate Sonarr reporting the shadow path; ingest must not move the folder back.
    series["path"] = str(shadow_root / "No Duplicate (2020)")
    service.reconcile()

    assert series_folder.exists()
    assert projected_folder.exists()
    assert not (series_folder / "No Duplicate (2020)").exists()
    assert len(list(series_folder.rglob("*.mkv"))) == 1


@pytest.mark.fs_e2e
def test_sonarr_nested_shadow_path_is_normalized_to_canonical_shadow_folder(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    managed_folder = nested_root / "Series Alias Folder"
    season_one = managed_folder / "Season 01"
    season_one.mkdir(parents=True)
    source_file = season_one / "Nested.Path.S01E01.1080p.mkv"
    source_file.write_text("x", encoding="utf-8")

    nested_shadow_path = shadow_root / "FSK12" / "Nested Path (2020)"
    nested_shadow_path.mkdir(parents=True)

    config = _sonarr_auto_add_config(nested_root, shadow_root)
    config.sonarr.auto_add_unmatched = False
    service = LibrariArrService(config)
    series = _series(103, "Nested Path", 2020, nested_shadow_path)
    service.sonarr = AutoAddFakeSonarr(series=[series], lookup_sequences=[])
    service.sonarr_projection.state_store.set_managed_series_folder(103, managed_folder)

    service.reconcile()

    canonical_shadow = shadow_root / "Nested Path (2020)"
    projected = canonical_shadow / "Season 01" / source_file.name
    assert projected.exists()
    assert projected.samefile(source_file)
    assert series["path"] == str(canonical_shadow)


@pytest.mark.fs_e2e
def test_startup_full_reconcile_projects_sonarr_series(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    series_folder = nested_root / "Startup Series (2024)"
    season_one = series_folder / "Season 01"
    season_one.mkdir(parents=True)
    source = season_one / "Startup.Series.S01E01.1080p.mkv"
    source.write_text("x", encoding="utf-8")

    config = _sonarr_auto_add_config(nested_root, shadow_root)
    config.sonarr.auto_add_unmatched = False
    service = LibrariArrService(config)
    service.sonarr = AutoAddFakeSonarr(
        series=[_series(104, "Startup Series", 2024, series_folder)],
        lookup_sequences=[],
    )

    loop = RuntimeSyncLoop(
        nested_roots=[nested_root],
        shadow_roots=[shadow_root],
        schedule=ReconcileSchedule(debounce_seconds=1, maintenance_interval_seconds=None),
        reconcile=service.reconcile,
        on_reconcile_error=lambda exc: (_ for _ in ()).throw(exc),
        logger=logging.getLogger("tests.fs_e2e.startup.sonarr"),
        startup_reconcile_mode="full",
    )

    loop._run_startup_reconcile_cycle()

    projected = shadow_root / "Startup Series (2024)" / "Season 01" / source.name
    assert projected.exists()
    assert projected.samefile(source)
