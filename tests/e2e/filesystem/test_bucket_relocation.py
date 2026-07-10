"""Scenario 11: Arr-side root-folder reassignment (bucket move).

Needs two configured buckets, unlike the single-mapping fixtures shared by
the rest of the fs-e2e suite, so this builds its own two-mapping config —
otherwise identical in spirit: fake Arr clients, real filesystem, real
hardlinks.
"""

from __future__ import annotations

import os

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
from librariarr.core.engine import SCOPE_FULL, ReconcileEngine
from librariarr.core.index import AdvisoryCache

from .conftest import FakeRadarr, FakeSonarr, hardlink, write_file

pytestmark = pytest.mark.fs_e2e


def move_same_filesystem(source, target):
    """Simulate Radarr/Sonarr's same-filesystem 'move files' -- inode preserved."""
    target.parent.mkdir(parents=True, exist_ok=True)
    os.link(source, target)
    source.unlink()


@pytest.fixture
def two_bucket_config(tmp_path):
    roots = {
        "managed_a": tmp_path / "movies" / "FSK12",
        "library_a": tmp_path / "radarr_library" / "FSK12",
        "managed_b": tmp_path / "movies" / "FSK16",
        "library_b": tmp_path / "radarr_library" / "FSK16",
        "series_managed_a": tmp_path / "series" / "FSK12",
        "series_shadow_a": tmp_path / "sonarr_library" / "FSK12",
        "series_managed_b": tmp_path / "series" / "FSK16",
        "series_shadow_b": tmp_path / "sonarr_library" / "FSK16",
    }
    for p in roots.values():
        p.mkdir(parents=True)
    config = AppConfig(
        paths=PathsConfig(
            movie_root_mappings=[
                MovieRootMapping(
                    managed_root=str(roots["managed_a"]), library_root=str(roots["library_a"])
                ),
                MovieRootMapping(
                    managed_root=str(roots["managed_b"]), library_root=str(roots["library_b"])
                ),
            ],
            series_root_mappings=[
                RootMapping(
                    managed_root=str(roots["series_managed_a"]),
                    library_root=str(roots["series_shadow_a"]),
                ),
                RootMapping(
                    managed_root=str(roots["series_managed_b"]),
                    library_root=str(roots["series_shadow_b"]),
                ),
            ],
            exclude_paths=list(DEFAULT_EXCLUDE_PATH_PATTERNS),
        ),
        radarr=RadarrConfig(url="http://radarr:7878", api_key="x"),
        sonarr=SonarrConfig(enabled=True, url="http://sonarr:8989", api_key="x"),
        runtime=RuntimeConfig(),
        ingest=IngestConfig(),
    )
    return config, roots


@pytest.fixture
def cache(tmp_path):
    return AdvisoryCache(tmp_path / "cache.json")


def test_s11_radarr_root_folder_change_relocates_managed_movie(two_bucket_config, cache):
    config, roots = two_bucket_config
    managed_file = write_file(roots["managed_a"] / "Foo (2020)" / "Foo.mkv")
    old_lib_file = hardlink(managed_file, roots["library_a"] / "Foo (2020)" / "Foo.mkv")
    cache.set_folder("radarr", 1, managed_file.parent)
    radarr = FakeRadarr(
        [
            {
                "id": 1,
                "title": "Foo",
                "year": 2020,
                "path": str(old_lib_file.parent),
                "movieFile": {"path": str(old_lib_file)},
            }
        ]
    )
    engine = ReconcileEngine(config, radarr=radarr, sonarr=None, cache=cache)
    engine.run(scope=SCOPE_FULL)

    # Real-world trigger: user does "Edit Movie -> Root Folder -> FSK16" in
    # Radarr with "Move files" checked.
    new_lib_file = roots["library_b"] / "Foo (2020)" / "Foo.mkv"
    move_same_filesystem(old_lib_file, new_lib_file)
    old_lib_file.parent.rmdir()
    radarr.movies[0]["path"] = str(new_lib_file.parent)
    radarr.movies[0]["movieFile"]["path"] = str(new_lib_file)

    report = engine.run(scope=SCOPE_FULL)

    relocated = roots["managed_b"] / "Foo (2020)" / "Foo.mkv"
    assert relocated.exists(), "managed folder must follow the movie into its new bucket"
    assert not managed_file.exists(), "old bucket location is gone (moved, not duplicated)"
    assert relocated.stat().st_ino == new_lib_file.stat().st_ino
    assert any(a.kind == "relocate" for a in report.actions)

    # Idempotent: a repeat full pass makes no further changes.
    second = engine.run(scope=SCOPE_FULL)
    assert not any(a.kind == "relocate" for a in second.actions)


def test_s11_sonarr_root_folder_change_relocates_managed_series(two_bucket_config, cache):
    config, roots = two_bucket_config
    managed_ep = write_file(
        roots["series_managed_a"] / "Show (2020)" / "Season 01" / "Show.S01E01.mkv"
    )
    old_shadow_ep = hardlink(
        managed_ep, roots["series_shadow_a"] / "Show (2020)" / "Season 01" / "Show.S01E01.mkv"
    )
    cache.set_folder("sonarr", 1, managed_ep.parent.parent)
    sonarr = FakeSonarr(
        [
            {
                "id": 1,
                "title": "Show",
                "year": 2020,
                "path": str(roots["series_shadow_a"] / "Show (2020)"),
                "statistics": {"episodeFileCount": 1},
            }
        ],
        {1: [{"path": str(old_shadow_ep), "relativePath": "Season 01/Show.S01E01.mkv"}]},
    )
    engine = ReconcileEngine(config, radarr=None, sonarr=sonarr, cache=cache)
    engine.run(scope=SCOPE_FULL)

    # Real-world trigger: user moves the series to a different Sonarr root folder.
    new_shadow_ep = roots["series_shadow_b"] / "Show (2020)" / "Season 01" / "Show.S01E01.mkv"
    move_same_filesystem(old_shadow_ep, new_shadow_ep)
    sonarr.series[0]["path"] = str(new_shadow_ep.parent.parent)
    sonarr.episode_files[1] = [
        {"path": str(new_shadow_ep), "relativePath": "Season 01/Show.S01E01.mkv"}
    ]

    report = engine.run(scope=SCOPE_FULL)

    relocated = roots["series_managed_b"] / "Show (2020)" / "Season 01" / "Show.S01E01.mkv"
    assert relocated.exists(), "managed episode must follow the series into its new bucket"
    assert not managed_ep.exists()
    assert relocated.stat().st_ino == new_shadow_ep.stat().st_ino
    assert any(a.kind == "relocate" for a in report.actions)

    second = engine.run(scope=SCOPE_FULL)
    assert not any(a.kind == "relocate" for a in second.actions)
