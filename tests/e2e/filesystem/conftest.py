from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    IngestConfig,
    MovieRootMapping,
    PathsConfig,
    RadarrConfig,
    RadarrProjectionConfig,
    RootMapping,
    RuntimeConfig,
    SonarrConfig,
)

# ---------------------------------------------------------------------------
# Fake Arr clients
# ---------------------------------------------------------------------------


class FakeRadarr:
    def __init__(self, movies: list[dict]) -> None:
        self.movies = movies

    def get_movies(self) -> list[dict]:
        return self.movies

    def get_movies_by_ids(self, movie_ids: list[int]) -> list[dict]:
        ids = set(movie_ids)
        return [movie for movie in self.movies if int(movie.get("id", -1)) in ids]

    def update_movie_path(self, movie: dict, new_path: str) -> bool:
        movie["path"] = new_path
        return True

    def refresh_movie(self, movie_id: int) -> bool:
        return True

    def refresh_movies(self, movie_ids: set[int]) -> int:
        return len(movie_ids)


class FakeSonarr:
    def __init__(self, series: list[dict]) -> None:
        self.series = series

    def get_series(self) -> list[dict]:
        return self.series

    def get_series_by_ids(self, series_ids: set[int]) -> list[dict]:
        ids = set(series_ids)
        return [s for s in self.series if int(s.get("id", -1)) in ids]

    def update_series_path(self, series: dict, new_path: str) -> bool:
        series["path"] = new_path
        return True


# ---------------------------------------------------------------------------
# Data factories
# ---------------------------------------------------------------------------


def make_movie(movie_id: int, title: str, year: int, path: Path) -> dict:
    return {
        "id": movie_id,
        "title": title,
        "year": year,
        "path": str(path),
        "movieFile": {"id": movie_id * 10},
        "monitored": True,
    }


def make_series(series_id: int, title: str, year: int, path: Path) -> dict:
    return {
        "id": series_id,
        "title": title,
        "year": year,
        "path": str(path),
        "monitored": True,
    }


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def make_roots(tmp_path: Path, case_name: str) -> tuple[Path, Path]:
    persist_root = os.getenv("LIBRARIARR_E2E_PERSIST_ROOT")
    if not persist_root:
        return tmp_path / "managed", tmp_path / "library"

    case_root = Path(persist_root) / case_name
    try:
        if case_root.exists():
            shutil.rmtree(case_root)
        managed_root = case_root / "managed"
        library_root = case_root / "library"
        managed_root.mkdir(parents=True, exist_ok=True)
        library_root.mkdir(parents=True, exist_ok=True)
        return managed_root, library_root
    except OSError:
        fallback_root = tmp_path / case_name
        if fallback_root.exists():
            shutil.rmtree(fallback_root)
        managed_root = fallback_root / "managed"
        library_root = fallback_root / "library"
        managed_root.mkdir(parents=True, exist_ok=True)
        library_root.mkdir(parents=True, exist_ok=True)
        return managed_root, library_root


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

_DEFAULT_RUNTIME = RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60)
_DEFAULT_CLEANUP = CleanupConfig(remove_orphaned_links=True)


def make_radarr_config(
    *,
    managed_root: Path,
    library_root: Path,
    sync_enabled: bool = False,
    ingest_enabled: bool = True,
    projection: RadarrProjectionConfig | None = None,
    exclude_paths: list[str] | None = None,
    radarr_enabled: bool = True,
) -> AppConfig:
    radarr_kwargs: dict = {
        "url": "http://radarr:7878",
        "api_key": "test",
        "enabled": radarr_enabled,
        "sync_enabled": sync_enabled,
    }
    if projection is not None:
        radarr_kwargs["projection"] = projection
    return AppConfig(
        paths=PathsConfig(
            series_root_mappings=[],
            movie_root_mappings=[
                MovieRootMapping(managed_root=str(managed_root), library_root=str(library_root))
            ],
            exclude_paths=exclude_paths or [],
        ),
        radarr=RadarrConfig(**radarr_kwargs),
        cleanup=_DEFAULT_CLEANUP,
        runtime=_DEFAULT_RUNTIME,
        ingest=IngestConfig(enabled=ingest_enabled),
    )


def make_sonarr_config(
    *,
    nested_root: Path,
    shadow_root: Path,
) -> AppConfig:
    return AppConfig(
        paths=PathsConfig(
            series_root_mappings=[
                RootMapping(nested_root=str(nested_root), shadow_root=str(shadow_root)),
            ],
            movie_root_mappings=[],
        ),
        radarr=RadarrConfig(
            enabled=False, url="http://radarr:7878", api_key="test", sync_enabled=False
        ),
        sonarr=SonarrConfig(enabled=True, url="http://sonarr:8989", api_key="test"),
        cleanup=_DEFAULT_CLEANUP,
        runtime=_DEFAULT_RUNTIME,
    )


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_radarr():
    return FakeRadarr


@pytest.fixture
def movie_factory():
    return make_movie
