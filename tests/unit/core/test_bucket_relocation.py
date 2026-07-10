"""Arr-side root-folder reassignment ("move to another root folder") is
treated as a deliberate reclassification: the managed folder is relocated to
match. This needs two configured buckets (movie/series_root_mappings), unlike
the single-mapping fixtures in conftest.py, so it builds its own config.
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

from .conftest import FakeRadarr, FakeSonarr, hardlink, movie_payload, series_payload, write_file


@pytest.fixture
def buckets(tmp_path):
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
    for p in paths.values():
        p.mkdir(parents=True)
    return paths


@pytest.fixture
def multi_bucket_config(buckets):
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
def cache(tmp_path):
    return AdvisoryCache(tmp_path / "cache.json")


def move_same_filesystem(source, target):
    """Simulate Radarr/Sonarr's same-filesystem 'move files' -- inode preserved."""
    target.parent.mkdir(parents=True, exist_ok=True)
    os.link(source, target)
    source.unlink()


def test_movie_follows_radarr_root_folder_change_to_new_bucket(multi_bucket_config, cache, buckets):
    managed_file = write_file(buckets["managed_a"] / "Foo (2020)" / "Foo.mkv")
    old_lib_file = hardlink(managed_file, buckets["library_a"] / "Foo (2020)" / "Foo.mkv")
    cache.set_folder("radarr", 1, managed_file.parent)
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, old_lib_file.parent, old_lib_file)])
    engine = ReconcileEngine(multi_bucket_config, radarr=radarr, sonarr=None, cache=cache)
    engine.run(scope=SCOPE_FULL)

    # User changes the movie's Root Folder in Radarr to FSK16 ("Move files").
    new_lib_file = buckets["library_b"] / "Foo (2020)" / "Foo.mkv"
    move_same_filesystem(old_lib_file, new_lib_file)
    old_lib_file.parent.rmdir()
    radarr.movies[0]["path"] = str(new_lib_file.parent)
    radarr.movies[0]["movieFile"]["path"] = str(new_lib_file)

    report = engine.run(scope=SCOPE_FULL)

    new_managed_location = buckets["managed_b"] / "Foo (2020)" / "Foo.mkv"
    assert new_managed_location.exists(), "managed file must follow into the new bucket"
    assert not managed_file.exists(), "old bucket location must be gone (real move, not a copy)"
    assert new_managed_location.stat().st_ino == new_lib_file.stat().st_ino
    assert cache.get_folder("radarr", 1) == new_managed_location.parent
    assert any(a.kind == "relocate" for a in report.actions)
    assert not (buckets["managed_a"] / "Foo (2020)").exists(), "empty old folder is pruned"


def test_movie_relocation_preserves_user_custom_naming(multi_bucket_config, cache, buckets):
    # User nested it under a custom subfolder and gave it a name of their own.
    managed_file = write_file(
        buckets["managed_a"] / "Studio X" / "My Custom Name (2020)" / "Foo.mkv"
    )
    old_lib_file = hardlink(managed_file, buckets["library_a"] / "Foo (2020)" / "Foo.mkv")
    cache.set_folder("radarr", 1, managed_file.parent)
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, old_lib_file.parent, old_lib_file)])
    engine = ReconcileEngine(multi_bucket_config, radarr=radarr, sonarr=None, cache=cache)
    engine.run(scope=SCOPE_FULL)

    new_lib_file = buckets["library_b"] / "Foo (2020)" / "Foo.mkv"
    move_same_filesystem(old_lib_file, new_lib_file)
    old_lib_file.parent.rmdir()
    radarr.movies[0]["path"] = str(new_lib_file.parent)
    radarr.movies[0]["movieFile"]["path"] = str(new_lib_file)

    engine.run(scope=SCOPE_FULL)

    expected = buckets["managed_b"] / "Studio X" / "My Custom Name (2020)" / "Foo.mkv"
    assert expected.exists(), "custom subfolder structure and naming must be preserved verbatim"


def test_movie_relocation_refuses_to_clobber_existing_destination(
    multi_bucket_config, cache, buckets
):
    managed_file = write_file(buckets["managed_a"] / "Foo (2020)" / "Foo.mkv")
    old_lib_file = hardlink(managed_file, buckets["library_a"] / "Foo (2020)" / "Foo.mkv")
    cache.set_folder("radarr", 1, managed_file.parent)
    # Something already occupies the destination.
    write_file(buckets["managed_b"] / "Foo (2020)" / "unrelated.mkv")
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, old_lib_file.parent, old_lib_file)])
    engine = ReconcileEngine(multi_bucket_config, radarr=radarr, sonarr=None, cache=cache)
    engine.run(scope=SCOPE_FULL)

    new_lib_file = buckets["library_b"] / "Foo (2020)" / "Foo.mkv"
    move_same_filesystem(old_lib_file, new_lib_file)
    old_lib_file.parent.rmdir()
    radarr.movies[0]["path"] = str(new_lib_file.parent)
    radarr.movies[0]["movieFile"]["path"] = str(new_lib_file)

    report = engine.run(scope=SCOPE_FULL)

    assert managed_file.exists(), "original must be untouched when destination is occupied"
    assert not any(a.kind == "relocate" for a in report.actions)
    assert report.warnings


def test_movie_relocation_dry_run_reports_without_moving(multi_bucket_config, cache, buckets):
    managed_file = write_file(buckets["managed_a"] / "Foo (2020)" / "Foo.mkv")
    old_lib_file = hardlink(managed_file, buckets["library_a"] / "Foo (2020)" / "Foo.mkv")
    cache.set_folder("radarr", 1, managed_file.parent)
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, old_lib_file.parent, old_lib_file)])
    engine = ReconcileEngine(multi_bucket_config, radarr=radarr, sonarr=None, cache=cache)
    engine.run(scope=SCOPE_FULL)

    new_lib_file = buckets["library_b"] / "Foo (2020)" / "Foo.mkv"
    move_same_filesystem(old_lib_file, new_lib_file)
    old_lib_file.parent.rmdir()
    radarr.movies[0]["path"] = str(new_lib_file.parent)
    radarr.movies[0]["movieFile"]["path"] = str(new_lib_file)

    report = engine.run(scope=SCOPE_FULL, dry_run=True)

    assert managed_file.exists(), "dry-run must not move anything"
    assert not (buckets["managed_b"] / "Foo (2020)").exists()
    assert any(a.kind == "relocate" for a in report.actions)


def test_series_follows_sonarr_root_folder_change_to_new_bucket(
    multi_bucket_config, cache, buckets
):
    managed_ep = write_file(
        buckets["series_managed_a"] / "Show (2020)" / "Season 01" / "Show.S01E01.mkv"
    )
    old_shadow_ep = hardlink(
        managed_ep, buckets["series_shadow_a"] / "Show (2020)" / "Season 01" / "Show.S01E01.mkv"
    )
    cache.set_folder("sonarr", 1, managed_ep.parent.parent)
    sonarr = FakeSonarr(
        [series_payload(1, "Show", 2020, buckets["series_shadow_a"] / "Show (2020)")],
        {1: [{"path": str(old_shadow_ep), "relativePath": "Season 01/Show.S01E01.mkv"}]},
    )
    engine = ReconcileEngine(multi_bucket_config, radarr=None, sonarr=sonarr, cache=cache)
    engine.run(scope=SCOPE_FULL)

    new_shadow_ep = buckets["series_shadow_b"] / "Show (2020)" / "Season 01" / "Show.S01E01.mkv"
    move_same_filesystem(old_shadow_ep, new_shadow_ep)
    sonarr.series[0]["path"] = str(new_shadow_ep.parent.parent)
    sonarr.episode_files[1] = [
        {"path": str(new_shadow_ep), "relativePath": "Season 01/Show.S01E01.mkv"}
    ]

    report = engine.run(scope=SCOPE_FULL)

    new_managed_ep = buckets["series_managed_b"] / "Show (2020)" / "Season 01" / "Show.S01E01.mkv"
    assert new_managed_ep.exists(), "managed episode must follow into the new bucket"
    assert not managed_ep.exists()
    assert new_managed_ep.stat().st_ino == new_shadow_ep.stat().st_ino
    assert cache.get_folder("sonarr", 1) == new_managed_ep.parent.parent
    assert any(a.kind == "relocate" for a in report.actions)
