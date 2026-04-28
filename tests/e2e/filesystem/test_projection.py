"""Radarr projection fs-e2e tests.

Core hardlink projection scenarios: layout, mappings, webhook scoping,
nested-path flattening, name mismatch, and shadow-folder safety.
"""

from pathlib import Path

import pytest

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    MovieRootMapping,
    PathsConfig,
    RadarrConfig,
    RootMapping,
    RuntimeConfig,
)
from librariarr.projection import get_radarr_webhook_queue
from librariarr.service import LibrariArrService

from .conftest import FakeRadarr, make_movie, make_radarr_config, make_roots


@pytest.mark.fs_e2e
def test_projection_creates_expected_hardlink_layout(tmp_path: Path) -> None:
    managed_root, library_root = make_roots(tmp_path, "projection_hardlink_layout")

    movie_a = managed_root / "age_12" / "Blender" / "Fixture Catalog A (2008)"
    movie_b = managed_root / "age_16" / "OpenFilms" / "Sintel (2010)"
    movie_a.mkdir(parents=True)
    movie_b.mkdir(parents=True)

    source_a = movie_a / "Big.Buck.Bunny.2008.1080p.x265.mkv"
    source_b = movie_b / "Sintel.2010.2160p.REMUX.mkv"
    source_a.write_text("stub", encoding="utf-8")
    source_b.write_text("stub", encoding="utf-8")

    config = make_radarr_config(managed_root=managed_root, library_root=library_root)

    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        movies=[
            make_movie(1, "Fixture Catalog A", 2008, movie_a),
            make_movie(2, "Sintel", 2010, movie_b),
        ]
    )

    service.reconcile()

    projected_a = library_root / "Fixture Catalog A (2008)" / source_a.name
    projected_b = library_root / "Sintel (2010)" / source_b.name

    assert projected_a.exists()
    assert projected_b.exists()
    assert projected_a.samefile(source_a)
    assert projected_b.samefile(source_b)


@pytest.mark.fs_e2e
def test_projection_respects_movie_root_mappings(tmp_path: Path) -> None:
    base = tmp_path / "mapping"
    managed_a = base / "managed_a"
    managed_b = base / "managed_b"
    library_a = base / "library_a"
    library_b = base / "library_b"

    movie_a = managed_a / "Movie A (2020)"
    movie_b = managed_b / "Movie B (2021)"
    movie_a.mkdir(parents=True)
    movie_b.mkdir(parents=True)

    source_a = movie_a / "Movie.A.2020.1080p.x265.mkv"
    source_b = movie_b / "Movie.B.2021.1080p.x265.mkv"
    source_a.write_text("stub", encoding="utf-8")
    source_b.write_text("stub", encoding="utf-8")

    config = AppConfig(
        paths=PathsConfig(
            series_root_mappings=[],
            movie_root_mappings=[
                MovieRootMapping(managed_root=str(managed_a), library_root=str(library_a)),
                MovieRootMapping(managed_root=str(managed_b), library_root=str(library_b)),
            ],
        ),
        radarr=RadarrConfig(url="http://radarr:7878", api_key="test", sync_enabled=False),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )

    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        movies=[
            make_movie(1, "Movie A", 2020, movie_a),
            make_movie(2, "Movie B", 2021, movie_b),
        ]
    )

    service.reconcile()

    assert (library_a / "Movie A (2020)" / source_a.name).exists()
    assert (library_b / "Movie B (2021)" / source_b.name).exists()
    assert not (library_b / "Movie A (2020)").exists()
    assert not (library_a / "Movie B (2021)").exists()


@pytest.mark.fs_e2e
def test_projection_scopes_to_webhook_movie_ids(tmp_path: Path) -> None:
    managed_root, library_root = make_roots(tmp_path, "projection_scoped_webhook")

    movie_a = managed_root / "Fixture Catalog A (2008)"
    movie_b = managed_root / "Fixture Catalog B (2009)"
    movie_a.mkdir(parents=True)
    movie_b.mkdir(parents=True)

    source_a = movie_a / "a.mkv"
    source_b = movie_b / "b.mkv"
    source_a.write_text("a", encoding="utf-8")
    source_b.write_text("b", encoding="utf-8")

    config = make_radarr_config(managed_root=managed_root, library_root=library_root)

    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        movies=[
            make_movie(1, "Fixture Catalog A", 2008, movie_a),
            make_movie(2, "Fixture Catalog B", 2009, movie_b),
        ]
    )

    queue = get_radarr_webhook_queue()
    queue.consume_movie_ids()
    queue.enqueue(movie_id=2, event_type="Test", normalized_path=str(movie_b))

    service.reconcile()

    assert not (library_root / "Fixture Catalog A (2008)" / source_a.name).exists()
    assert (library_root / "Fixture Catalog B (2009)" / source_b.name).exists()

    queue.consume_movie_ids()


@pytest.mark.fs_e2e
def test_projection_flattens_nested_library_path(tmp_path: Path) -> None:
    """When Radarr's stored path is nested under library_root, the planner should
    still produce a flat ``Title (Year)`` library folder and the orchestrator should
    update the Radarr path to match."""
    managed_root, library_root = make_roots(tmp_path, "flatten_nested_library")

    movie_dir = managed_root / "Film Collection" / "Great Movie (2024)"
    movie_dir.mkdir(parents=True)
    source_file = movie_dir / "Great.Movie.2024.1080p.mkv"
    source_file.write_text("stub", encoding="utf-8")

    nested_library_path = library_root / "Film Collection" / "Great Movie (2024)"

    config = make_radarr_config(managed_root=managed_root, library_root=library_root)

    radarr = FakeRadarr(movies=[make_movie(1, "Great Movie", 2024, nested_library_path)])
    service = LibrariArrService(config)
    service.radarr = radarr

    service.reconcile()

    flat_projected = library_root / "Great Movie (2024)" / source_file.name
    assert flat_projected.exists(), f"Expected flat projection at {flat_projected}"
    assert flat_projected.samefile(source_file)
    assert not (nested_library_path / source_file.name).exists()


@pytest.mark.fs_e2e
def test_projection_does_not_ingest_shadow_folder(tmp_path: Path) -> None:
    managed_root, shadow_root = make_roots(tmp_path, "ingest_moves_shadow_to_nested")
    nested_root = managed_root / "age_12"
    mapped_shadow = shadow_root / "age_12"

    imported_dir = mapped_shadow / "Imported Movie (2024)"
    imported_dir.mkdir(parents=True)
    (imported_dir / "Imported.Movie.2024.1080p.mkv").write_text("stub", encoding="utf-8")

    config = AppConfig(
        paths=PathsConfig(
            series_root_mappings=[
                RootMapping(nested_root=str(nested_root), shadow_root=str(mapped_shadow)),
            ],
            movie_root_mappings=[],
        ),
        radarr=RadarrConfig(
            enabled=False, url="http://radarr:7878", api_key="test", sync_enabled=False
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )

    service = LibrariArrService(config)
    service.reconcile()

    destination = nested_root / "Imported Movie (2024)"
    assert not destination.exists()
    assert imported_dir.exists()
    assert imported_dir.is_dir()
    assert not imported_dir.is_symlink()


@pytest.mark.fs_e2e
def test_projection_name_mismatch_still_projects_correctly(tmp_path: Path) -> None:
    """When the managed folder is 'Title (Year) Extra Info' but Radarr's path
    points directly to that folder, projection should still create correct
    hardlinks at library_root/Title (Year)/."""
    managed_root, library_root = make_roots(tmp_path, "projection_name_mismatch")

    managed_folder = managed_root / "Blade Runner (1982) Final Cut"
    managed_folder.mkdir(parents=True)
    source_file = managed_folder / "Blade.Runner.1982.Final.Cut.2160p.mkv"
    source_file.write_text("blade-runner-content", encoding="utf-8")

    config = make_radarr_config(managed_root=managed_root, library_root=library_root)

    service = LibrariArrService(config)
    service.radarr = FakeRadarr(movies=[make_movie(1, "Blade Runner", 1982, managed_folder)])

    service.reconcile()

    projected = library_root / "Blade Runner (1982)" / source_file.name
    assert projected.exists(), f"Expected projection at {projected}"
    assert projected.samefile(source_file), "Projected file should be hardlink to source"

    phantom = managed_root / "Blade Runner (1982)"
    assert not phantom.exists(), (
        f"Phantom folder {phantom} created in managed_root — "
        "projection should never create folders in managed roots"
    )
    assert managed_folder.exists()
    assert source_file.exists()


@pytest.mark.fs_e2e
def test_missing_managed_folder_skips_projection(tmp_path: Path) -> None:
    """When the managed folder doesn't exist on disk, projection should skip
    that movie without errors."""
    managed_root, library_root = make_roots(tmp_path, "missing_managed")

    ghost_path = managed_root / "Ghost Movie (2024)"

    config = make_radarr_config(managed_root=managed_root, library_root=library_root)

    service = LibrariArrService(config)
    service.radarr = FakeRadarr(movies=[make_movie(1, "Ghost Movie", 2024, ghost_path)])

    service.reconcile()

    assert not (library_root / "Ghost Movie (2024)").exists()


@pytest.mark.fs_e2e
def test_empty_managed_folder_produces_no_library_output(tmp_path: Path) -> None:
    """A managed folder with no video/extras produces no library output."""
    managed_root, library_root = make_roots(tmp_path, "empty_managed")

    managed_folder = managed_root / "Empty Movie (2024)"
    managed_folder.mkdir(parents=True)
    (managed_folder / "readme.txt").write_text("not a video", encoding="utf-8")

    config = make_radarr_config(managed_root=managed_root, library_root=library_root)

    service = LibrariArrService(config)
    service.radarr = FakeRadarr(movies=[make_movie(1, "Empty Movie", 2024, managed_folder)])

    service.reconcile()

    assert not (library_root / "Empty Movie (2024)").exists()


@pytest.mark.fs_e2e
def test_radarr_disabled_skips_all_projection(tmp_path: Path) -> None:
    """With radarr.enabled=False, no movie projection should occur."""
    managed_root, library_root = make_roots(tmp_path, "radarr_disabled")

    managed_folder = managed_root / "Disabled Movie (2024)"
    managed_folder.mkdir(parents=True)
    (managed_folder / "Disabled.2024.mkv").write_text("stub", encoding="utf-8")

    config = make_radarr_config(
        managed_root=managed_root, library_root=library_root, radarr_enabled=False
    )

    service = LibrariArrService(config)
    service.reconcile()

    assert not (library_root / "Disabled Movie (2024)").exists()
