from __future__ import annotations

import os
from pathlib import Path

import pytest

from librariarr.config.defaults import DEFAULT_EXCLUDE_PATH_PATTERNS
from librariarr.config.models import (
    AppConfig,
    IngestConfig,
    MovieRootMapping,
    PathsConfig,
    RadarrConfig,
    RootMapping,
    RuntimeConfig,
    SonarrConfig,
)
from librariarr.core.index import AdvisoryCache


class FakeRadarr:
    def __init__(self, movies: list[dict] | None = None) -> None:
        self.movies = movies or []
        self.refreshed: list[int] = []
        self.lookup_results: list[dict] = []
        self.added: list[dict] = []
        self.calls: list[str] = []
        self._next_id = 1000

    def get_movies(self) -> list[dict]:
        self.calls.append("get_movies")
        return self.movies

    def get_movies_by_ids(self, movie_ids) -> list[dict]:
        wanted = {int(movie_id) for movie_id in movie_ids}
        self.calls.append(f"get_movies_by_ids:{sorted(wanted)}")
        return [movie for movie in self.movies if int(movie["id"]) in wanted]

    def refresh_movie(self, movie_id: int, force: bool = False) -> bool:
        self.refreshed.append(int(movie_id))
        return True

    def lookup_movies(self, term: str) -> list[dict]:
        return self.lookup_results

    def add_movie_from_lookup(
        self,
        lookup_movie,
        path,
        root_folder_path,
        quality_profile_id,
        monitored,
        search_for_movie,
    ) -> dict:
        self._next_id += 1
        added = dict(lookup_movie)
        added.update({"id": self._next_id, "path": path, "monitored": monitored})
        self.added.append(added)
        self.movies.append(added)
        return added


class FakeSonarr:
    def __init__(
        self, series: list[dict] | None = None, episode_files: dict[int, list[dict]] | None = None
    ) -> None:
        self.series = series or []
        self.episode_files = episode_files or {}
        self.refreshed: list[int] = []
        self.lookup_results: list[dict] = []
        self.added: list[dict] = []
        self.calls: list[str] = []
        self._next_id = 2000

    def get_series(self) -> list[dict]:
        self.calls.append("get_series")
        return self.series

    def get_series_by_ids(self, series_ids) -> list[dict]:
        wanted = {int(series_id) for series_id in series_ids}
        self.calls.append(f"get_series_by_ids:{sorted(wanted)}")
        return [series for series in self.series if int(series["id"]) in wanted]

    def get_episode_files(self, series_id: int) -> list[dict]:
        return self.episode_files.get(int(series_id), [])

    def refresh_series(self, series_id: int, force: bool = False) -> bool:
        self.refreshed.append(int(series_id))
        return True

    def lookup_series(self, term: str) -> list[dict]:
        return self.lookup_results

    def add_series_from_lookup(
        self,
        lookup_series,
        path,
        root_folder_path,
        quality_profile_id,
        language_profile_id,
        monitored,
        season_folder,
        search_for_missing_episodes,
    ) -> dict:
        self._next_id += 1
        added = dict(lookup_series)
        added.update({"id": self._next_id, "path": path})
        self.added.append(added)
        self.series.append(added)
        return added


@pytest.fixture
def roots(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "managed_movies": tmp_path / "movies",
        "library_movies": tmp_path / "radarr_library",
        "managed_series": tmp_path / "series",
        "shadow_series": tmp_path / "sonarr_library",
    }
    for path in paths.values():
        path.mkdir(parents=True)
    return paths


@pytest.fixture
def config(roots: dict[str, Path]) -> AppConfig:
    return AppConfig(
        paths=PathsConfig(
            movie_root_mappings=[
                MovieRootMapping(
                    managed_root=str(roots["managed_movies"]),
                    library_root=str(roots["library_movies"]),
                )
            ],
            series_root_mappings=[
                RootMapping(
                    managed_root=str(roots["managed_series"]),
                    library_root=str(roots["shadow_series"]),
                )
            ],
            exclude_paths=list(DEFAULT_EXCLUDE_PATH_PATTERNS),
        ),
        radarr=RadarrConfig(url="http://radarr:7878", api_key="x"),
        sonarr=SonarrConfig(enabled=True, url="http://sonarr:8989", api_key="x"),
        runtime=RuntimeConfig(),
        ingest=IngestConfig(),
    )


@pytest.fixture
def buckets(tmp_path: Path) -> dict[str, Path]:
    """Two configured buckets per Arr — the shape a bucket move needs."""
    paths = {
        "managed_a": tmp_path / "movies" / "FSK12",
        "library_a": tmp_path / "radarr_library" / "FSK12",
        "managed_b": tmp_path / "movies" / "FSK16",
        "library_b": tmp_path / "radarr_library" / "FSK16",
        "series_managed_a": tmp_path / "series" / "FSK12",
        "series_shadow_a": tmp_path / "sonarr_library" / "FSK12",
        "series_managed_b": tmp_path / "series" / "FSK16",
        "series_shadow_b": tmp_path / "sonarr_library" / "FSK16",
    }
    for path in paths.values():
        path.mkdir(parents=True)
    return paths


@pytest.fixture
def multi_bucket_config(buckets: dict[str, Path]) -> AppConfig:
    return AppConfig(
        paths=PathsConfig(
            movie_root_mappings=[
                MovieRootMapping(
                    managed_root=str(buckets["managed_a"]), library_root=str(buckets["library_a"])
                ),
                MovieRootMapping(
                    managed_root=str(buckets["managed_b"]), library_root=str(buckets["library_b"])
                ),
            ],
            series_root_mappings=[
                RootMapping(
                    managed_root=str(buckets["series_managed_a"]),
                    library_root=str(buckets["series_shadow_a"]),
                ),
                RootMapping(
                    managed_root=str(buckets["series_managed_b"]),
                    library_root=str(buckets["series_shadow_b"]),
                ),
            ],
            exclude_paths=list(DEFAULT_EXCLUDE_PATH_PATTERNS),
        ),
        radarr=RadarrConfig(url="http://radarr:7878", api_key="x"),
        sonarr=SonarrConfig(enabled=True, url="http://sonarr:8989", api_key="x"),
        runtime=RuntimeConfig(),
        ingest=IngestConfig(),
    )


@pytest.fixture
def cache(tmp_path: Path) -> AdvisoryCache:
    return AdvisoryCache(tmp_path / "idcache.json")


def move_same_filesystem(source: Path, target: Path) -> Path:
    """Simulate Radarr/Sonarr's same-filesystem 'move files' -- inode preserved."""
    target.parent.mkdir(parents=True, exist_ok=True)
    os.link(source, target)
    source.unlink()
    return target


def write_file(path: Path, content: str = "data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def hardlink(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    os.link(source, target)
    return target


def movie_payload(
    movie_id: int,
    title: str,
    year: int,
    folder: Path,
    file_path: Path | None,
    date_added: str | None = None,
) -> dict:
    payload: dict = {"id": movie_id, "title": title, "year": year, "path": str(folder)}
    if file_path is not None:
        payload["movieFile"] = {"path": str(file_path)}
        if date_added is not None:
            payload["movieFile"]["dateAdded"] = date_added
    return payload


def series_payload(
    series_id: int, title: str, year: int, folder: Path, episode_file_count: int = 1
) -> dict:
    return {
        "id": series_id,
        "title": title,
        "year": year,
        "path": str(folder),
        "statistics": {"episodeFileCount": episode_file_count},
    }
