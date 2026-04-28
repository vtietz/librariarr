"""Ingest fs-e2e tests.

Scenarios for moving files/folders from library_root to managed_root:
folder-level ingest, file-level ingest, phantom prevention, cross-mapping
safety, and config toggles.
"""

from pathlib import Path

import pytest

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    IngestConfig,
    MovieRootMapping,
    PathsConfig,
    RadarrConfig,
    RuntimeConfig,
)
from librariarr.service import LibrariArrService

from .conftest import FakeRadarr, make_movie, make_radarr_config, make_roots


@pytest.mark.fs_e2e
def test_ingest_does_not_create_phantom_folder_on_name_mismatch(tmp_path: Path) -> None:
    """When Radarr's canonical name differs from the actual managed folder name,
    the ingest flow must NOT create a second folder in managed_root."""
    managed_root, library_root = make_roots(tmp_path, "ingest_no_phantom")

    real_managed = managed_root / "Amadeus (1984) Director's Cut FSK12"
    real_managed.mkdir(parents=True)
    source_file = real_managed / "Amadeus.1984.Directors.Cut.1080p.mkv"
    source_file.write_text("stub-amadeus", encoding="utf-8")

    canonical_library = library_root / "Amadeus (1984)"

    config = make_radarr_config(
        managed_root=managed_root, library_root=library_root, sync_enabled=True
    )

    service = LibrariArrService(config)
    service.radarr = FakeRadarr(movies=[make_movie(1, "Amadeus", 1984, canonical_library)])

    service.reconcile()

    phantom = managed_root / "Amadeus (1984)"
    assert not phantom.exists(), (
        f"Phantom folder {phantom} was created in managed_root! "
        "Ingest should not create folders when names don't match."
    )
    assert real_managed.exists()
    assert source_file.exists()


@pytest.mark.fs_e2e
def test_ingest_moves_matching_folder_from_library_to_managed(tmp_path: Path) -> None:
    """When Radarr downloads a movie into library_root and no managed equivalent
    exists, the ingest flow should move it to managed_root."""
    managed_root, library_root = make_roots(tmp_path, "ingest_move_match")

    downloaded = library_root / "New Movie (2024)"
    downloaded.mkdir(parents=True)
    video_file = downloaded / "New.Movie.2024.1080p.mkv"
    video_file.write_text("new-movie-content", encoding="utf-8")

    config = make_radarr_config(
        managed_root=managed_root, library_root=library_root, sync_enabled=True
    )

    service = LibrariArrService(config)
    service.radarr = FakeRadarr(movies=[make_movie(1, "New Movie", 2024, downloaded)])

    service.reconcile()

    ingested = managed_root / "New Movie (2024)"
    assert ingested.exists(), "Ingest should move matching folder to managed_root"
    assert (ingested / video_file.name).exists()

    assert not downloaded.exists() or (downloaded / video_file.name).exists()


@pytest.mark.fs_e2e
def test_ingest_file_level_when_managed_folder_exists(tmp_path: Path) -> None:
    """When the managed folder already exists, file-level ingest should move
    new files from library into the managed folder."""
    managed_root, library_root = make_roots(tmp_path, "ingest_file_level")

    managed_folder = managed_root / "Upgraded Movie (2023)"
    managed_folder.mkdir(parents=True)
    original_file = managed_folder / "Upgraded.Movie.2023.720p.mkv"
    original_file.write_text("original-720p", encoding="utf-8")

    library_folder = library_root / "Upgraded Movie (2023)"
    library_folder.mkdir(parents=True)
    new_file = library_folder / "Upgraded.Movie.2023.1080p.mkv"
    new_file.write_text("upgraded-1080p", encoding="utf-8")

    config = make_radarr_config(
        managed_root=managed_root, library_root=library_root, sync_enabled=True
    )

    service = LibrariArrService(config)
    service.radarr = FakeRadarr(movies=[make_movie(1, "Upgraded Movie", 2023, library_folder)])

    service.reconcile()

    ingested_file = managed_folder / "Upgraded.Movie.2023.1080p.mkv"
    assert ingested_file.exists(), "File-level ingest should move new file to managed folder"


@pytest.mark.fs_e2e
def test_ingest_disabled_does_not_move_folders(tmp_path: Path) -> None:
    """When ingest is disabled, folders under library_root should NOT be moved."""
    managed_root, library_root = make_roots(tmp_path, "ingest_disabled")

    downloaded = library_root / "Downloaded Movie (2024)"
    downloaded.mkdir(parents=True)
    (downloaded / "Downloaded.Movie.2024.1080p.mkv").write_text("stub", encoding="utf-8")

    config = make_radarr_config(
        managed_root=managed_root,
        library_root=library_root,
        sync_enabled=True,
        ingest_enabled=False,
    )

    service = LibrariArrService(config)
    service.radarr = FakeRadarr(movies=[make_movie(1, "Downloaded Movie", 2024, downloaded)])

    service.reconcile()

    assert not (managed_root / "Downloaded Movie (2024)").exists()
    assert downloaded.exists()


@pytest.mark.fs_e2e
def test_ingest_with_name_mismatch_and_projection_no_phantom(tmp_path: Path) -> None:
    """Full 'Amadeus' bug scenario across multiple reconcile cycles: managed folder
    has decorated name, Radarr path points to managed root. After two reconciles
    (projection then ingest), no phantom folder should appear."""
    managed_root, library_root = make_roots(tmp_path, "full_name_mismatch_flow")

    real_managed = managed_root / "Amadeus (1984) Director's Cut"
    real_managed.mkdir(parents=True)
    source = real_managed / "Amadeus.1984.DC.2160p.mkv"
    source.write_text("amadeus-dc", encoding="utf-8")

    config = make_radarr_config(
        managed_root=managed_root, library_root=library_root, sync_enabled=True
    )

    service = LibrariArrService(config)
    service.radarr = FakeRadarr(movies=[make_movie(1, "Amadeus", 1984, real_managed)])

    service.reconcile()

    projected = library_root / "Amadeus (1984)" / source.name
    assert projected.exists(), "Projection should create hardlinks in library root"
    assert projected.samefile(source)

    service.reconcile()

    phantom = managed_root / "Amadeus (1984)"
    assert not phantom.exists(), (
        f"Phantom folder {phantom} appeared after second reconcile! "
        "Ingest should not re-ingest projected hardlink folders."
    )
    assert real_managed.exists(), "Original managed folder must remain"


@pytest.mark.fs_e2e
def test_multiple_managed_roots_no_cross_ingest(tmp_path: Path) -> None:
    """Folders from library_root_a should only ingest to managed_root_a."""
    base = tmp_path / "cross_ingest"
    managed_a = base / "managed_a"
    managed_b = base / "managed_b"
    library_a = base / "library_a"
    library_b = base / "library_b"

    downloaded = library_a / "Cross Movie (2024)"
    downloaded.mkdir(parents=True)
    (downloaded / "Cross.Movie.2024.mkv").write_text("stub", encoding="utf-8")

    config = AppConfig(
        paths=PathsConfig(
            series_root_mappings=[],
            movie_root_mappings=[
                MovieRootMapping(managed_root=str(managed_a), library_root=str(library_a)),
                MovieRootMapping(managed_root=str(managed_b), library_root=str(library_b)),
            ],
        ),
        radarr=RadarrConfig(url="http://radarr:7878", api_key="test", sync_enabled=True),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
        ingest=IngestConfig(enabled=True),
    )

    service = LibrariArrService(config)
    service.radarr = FakeRadarr(movies=[make_movie(1, "Cross Movie", 2024, downloaded)])

    service.reconcile()

    expected = managed_a / "Cross Movie (2024)"
    assert expected.exists(), "Ingest should move to the correct managed root"

    cross = managed_b / "Cross Movie (2024)"
    assert not cross.exists(), "Ingest must not cross-map to wrong managed root"


@pytest.mark.fs_e2e
def test_ingest_skips_when_destination_already_exists(tmp_path: Path) -> None:
    """When managed_root already has a same-named folder, folder-level ingest
    should be skipped but file-level ingest should add new files."""
    managed_root, library_root = make_roots(tmp_path, "ingest_skip_existing")

    existing = managed_root / "Existing Movie (2023)"
    existing.mkdir(parents=True)
    (existing / "Existing.Movie.2023.720p.mkv").write_text("original", encoding="utf-8")

    library_folder = library_root / "Existing Movie (2023)"
    library_folder.mkdir(parents=True)
    (library_folder / "Existing.Movie.2023.1080p.mkv").write_text("upgraded", encoding="utf-8")

    config = make_radarr_config(
        managed_root=managed_root, library_root=library_root, sync_enabled=True
    )

    service = LibrariArrService(config)
    service.radarr = FakeRadarr(movies=[make_movie(1, "Existing Movie", 2023, library_folder)])

    service.reconcile()

    assert existing.exists()
    assert (existing / "Existing.Movie.2023.720p.mkv").exists()
    assert (existing / "Existing.Movie.2023.1080p.mkv").exists(), (
        "File-level ingest should have added the new file"
    )


@pytest.mark.fs_e2e
def test_ingest_no_duplicate_when_nested_movie_has_projections(tmp_path: Path) -> None:
    """Bug regression: when a movie lives in a nested managed subfolder and
    projection creates a flat canonical folder in library_root, ingest must NOT
    move the projection folder back to managed_root as a duplicate.

    Scenario:
    1. Movie lives at managed_root/Filmreihe/Movie FSK6/
    2. First reconcile: projection creates library_root/Movie (2024)/ with hardlinks
    3. Radarr path is updated to library_root/Movie (2024)/
    4. Second reconcile: ingest sees the projection folder — must NOT create
       managed_root/Movie (2024)/ (a duplicate alongside the nested original)
    """
    managed_root, library_root = make_roots(tmp_path, "nested_no_duplicate")

    # Nested managed folder (non-canonical name)
    nested_managed = managed_root / "Filmreihe" / "Movie FSK6"
    nested_managed.mkdir(parents=True)
    video = nested_managed / "Movie.2024.1080p.mkv"
    video.write_text("movie-content", encoding="utf-8")

    config = make_radarr_config(
        managed_root=managed_root, library_root=library_root, sync_enabled=True
    )

    # First reconcile: movie path points to managed folder, projection runs
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(movies=[make_movie(1, "Movie", 2024, nested_managed)])

    service.reconcile()

    projected = library_root / "Movie (2024)" / video.name
    assert projected.exists(), "Projection should create hardlinks in library root"
    assert projected.samefile(video), "Projected file should be a hardlink to original"

    # Simulate Radarr now reporting the library path (as it would after path update)
    library_folder = library_root / "Movie (2024)"
    service.radarr = FakeRadarr(movies=[make_movie(1, "Movie", 2024, library_folder)])

    service.reconcile()

    phantom = managed_root / "Movie (2024)"
    assert not phantom.exists(), (
        f"Duplicate folder {phantom} was created! "
        "Ingest must not move projection folders back to managed_root."
    )
    assert nested_managed.exists(), "Original nested managed folder must remain"
    assert video.exists(), "Original video file must remain"
