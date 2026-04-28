"""Config-variant fs-e2e tests.

These tests exercise how different configuration settings affect
the filesystem behaviour of projection and ingest.
"""

from pathlib import Path

import pytest

from librariarr.config import (
    RadarrProjectionConfig,
)
from librariarr.service import LibrariArrService

from .conftest import FakeRadarr, make_movie, make_radarr_config, make_roots

# ---------------------------------------------------------------------------
# preserve_unknown_files
# ---------------------------------------------------------------------------


@pytest.mark.fs_e2e
def test_preserve_unknown_files_keeps_unrecognized_dest(tmp_path: Path) -> None:
    """When preserve_unknown_files=True (default), existing files in library_root
    that are NOT tracked in the provenance DB must be left alone."""
    managed_root, library_root = make_roots(tmp_path, "preserve_unknown_true")

    managed_folder = managed_root / "Test Movie (2024)"
    managed_folder.mkdir(parents=True)
    source = managed_folder / "Test.Movie.2024.1080p.mkv"
    source.write_text("source-video", encoding="utf-8")

    lib_folder = library_root / "Test Movie (2024)"
    lib_folder.mkdir(parents=True)
    unknown_file = lib_folder / "Test.Movie.2024.1080p.mkv"
    unknown_file.write_text("user-placed-file", encoding="utf-8")

    config = make_radarr_config(managed_root=managed_root, library_root=library_root)

    service = LibrariArrService(config)
    service.radarr = FakeRadarr(movies=[make_movie(1, "Test Movie", 2024, managed_folder)])

    service.reconcile()

    assert unknown_file.exists()
    assert unknown_file.read_text(encoding="utf-8") == "user-placed-file"


@pytest.mark.fs_e2e
def test_preserve_unknown_files_false_replaces_dest(tmp_path: Path) -> None:
    """When preserve_unknown_files=False, existing non-tracked files in library_root
    should be replaced by hardlinks from the managed folder."""
    managed_root, library_root = make_roots(tmp_path, "preserve_unknown_false")

    managed_folder = managed_root / "Replace Movie (2024)"
    managed_folder.mkdir(parents=True)
    source = managed_folder / "Replace.Movie.2024.1080p.mkv"
    source.write_text("source-video", encoding="utf-8")

    lib_folder = library_root / "Replace Movie (2024)"
    lib_folder.mkdir(parents=True)
    existing = lib_folder / "Replace.Movie.2024.1080p.mkv"
    existing.write_text("old-file-content", encoding="utf-8")

    config = make_radarr_config(
        managed_root=managed_root,
        library_root=library_root,
        projection=RadarrProjectionConfig(preserve_unknown_files=False),
    )

    service = LibrariArrService(config)
    service.radarr = FakeRadarr(movies=[make_movie(1, "Replace Movie", 2024, managed_folder)])

    service.reconcile()

    dest = lib_folder / "Replace.Movie.2024.1080p.mkv"
    assert dest.exists()
    assert dest.samefile(source), "File should be replaced by a hardlink to source"


# ---------------------------------------------------------------------------
# Extras projection (managed_extras_allowlist)
# ---------------------------------------------------------------------------


@pytest.mark.fs_e2e
def test_extras_are_projected_according_to_allowlist(tmp_path: Path) -> None:
    """Extras matching the allowlist should be projected alongside the video file."""
    managed_root, library_root = make_roots(tmp_path, "extras_projection")

    managed_folder = managed_root / "Extras Movie (2024)"
    managed_folder.mkdir(parents=True)
    video = managed_folder / "Extras.Movie.2024.mkv"
    video.write_text("video-content", encoding="utf-8")
    srt = managed_folder / "Extras.Movie.2024.srt"
    srt.write_text("subtitle-content", encoding="utf-8")
    nfo = managed_folder / "movie.nfo"
    nfo.write_text("nfo-content", encoding="utf-8")
    random_file = managed_folder / "random.txt"
    random_file.write_text("should-not-project", encoding="utf-8")

    config = make_radarr_config(managed_root=managed_root, library_root=library_root)

    service = LibrariArrService(config)
    service.radarr = FakeRadarr(movies=[make_movie(1, "Extras Movie", 2024, managed_folder)])

    service.reconcile()

    lib_folder = library_root / "Extras Movie (2024)"
    assert (lib_folder / video.name).exists(), "Video should be projected"
    assert (lib_folder / srt.name).exists(), "SRT subtitle should be projected"
    assert (lib_folder / nfo.name).exists(), "movie.nfo should be projected"
    assert not (lib_folder / random_file.name).exists(), "Non-allowlisted file should NOT project"


@pytest.mark.fs_e2e
def test_custom_extras_allowlist(tmp_path: Path) -> None:
    """A custom managed_extras_allowlist should override the defaults."""
    managed_root, library_root = make_roots(tmp_path, "custom_extras")

    managed_folder = managed_root / "Custom Extras (2024)"
    managed_folder.mkdir(parents=True)
    video = managed_folder / "Custom.Extras.2024.mkv"
    video.write_text("video", encoding="utf-8")
    srt = managed_folder / "Custom.Extras.2024.srt"
    srt.write_text("subtitle", encoding="utf-8")
    custom_ext = managed_folder / "Custom.Extras.2024.ass"
    custom_ext.write_text("ass-subtitle", encoding="utf-8")

    config = make_radarr_config(
        managed_root=managed_root,
        library_root=library_root,
        projection=RadarrProjectionConfig(managed_extras_allowlist=["*.ass"]),
    )

    service = LibrariArrService(config)
    service.radarr = FakeRadarr(movies=[make_movie(1, "Custom Extras", 2024, managed_folder)])

    service.reconcile()

    lib_folder = library_root / "Custom Extras (2024)"
    assert (lib_folder / video.name).exists(), "Video always projected"
    assert (lib_folder / custom_ext.name).exists(), ".ass should be projected per custom list"
    assert not (lib_folder / srt.name).exists(), ".srt NOT projected (not in custom list)"


# ---------------------------------------------------------------------------
# Custom video extensions
# ---------------------------------------------------------------------------


@pytest.mark.fs_e2e
def test_custom_video_extensions(tmp_path: Path) -> None:
    """Custom managed_video_extensions should control which files are treated as videos."""
    managed_root, library_root = make_roots(tmp_path, "custom_video_ext")

    managed_folder = managed_root / "Custom Ext Movie (2024)"
    managed_folder.mkdir(parents=True)
    mkv = managed_folder / "movie.mkv"
    mkv.write_text("mkv-content", encoding="utf-8")
    m2ts = managed_folder / "movie.m2ts"
    m2ts.write_text("m2ts-content", encoding="utf-8")

    config = make_radarr_config(
        managed_root=managed_root,
        library_root=library_root,
        projection=RadarrProjectionConfig(
            managed_video_extensions=[".m2ts"],
            managed_extras_allowlist=[],
        ),
    )

    service = LibrariArrService(config)
    service.radarr = FakeRadarr(movies=[make_movie(1, "Custom Ext Movie", 2024, managed_folder)])

    service.reconcile()

    lib_folder = library_root / "Custom Ext Movie (2024)"
    assert (lib_folder / m2ts.name).exists(), ".m2ts should be projected with custom extension"
    assert not (lib_folder / mkv.name).exists(), ".mkv NOT projected (not in custom list)"


# ---------------------------------------------------------------------------
# exclude_paths
# ---------------------------------------------------------------------------


@pytest.mark.fs_e2e
def test_exclude_paths_skips_discovery(tmp_path: Path) -> None:
    """Folders matching exclude_paths should not be discovered for auto-add."""
    managed_root, library_root = make_roots(tmp_path, "exclude_paths")

    visible = managed_root / "Visible Movie (2024)"
    visible.mkdir(parents=True)
    (visible / "Visible.2024.mkv").write_text("visible", encoding="utf-8")

    excluded = managed_root / "@eaDir" / "Some Movie (2024)"
    excluded.mkdir(parents=True)
    (excluded / "Some.Movie.2024.mkv").write_text("excluded", encoding="utf-8")

    config = make_radarr_config(
        managed_root=managed_root,
        library_root=library_root,
        exclude_paths=["@eaDir/"],
    )

    service = LibrariArrService(config)
    service.radarr = FakeRadarr(movies=[make_movie(1, "Visible Movie", 2024, visible)])

    service.reconcile()

    assert (library_root / "Visible Movie (2024)" / "Visible.2024.mkv").exists()
    assert not (library_root / "Some Movie (2024)").exists()


# ---------------------------------------------------------------------------
# Source file replaced (relink-on-replace)
# ---------------------------------------------------------------------------


@pytest.mark.fs_e2e
def test_relink_on_source_replace(tmp_path: Path) -> None:
    """When the source file is replaced (different inode), the projected hardlink
    should be updated to point to the new source."""
    managed_root, library_root = make_roots(tmp_path, "relink_replace")

    managed_folder = managed_root / "Relink Movie (2024)"
    managed_folder.mkdir(parents=True)
    source = managed_folder / "Relink.Movie.2024.mkv"
    source.write_text("original-content", encoding="utf-8")

    config = make_radarr_config(managed_root=managed_root, library_root=library_root)

    service = LibrariArrService(config)
    service.radarr = FakeRadarr(movies=[make_movie(1, "Relink Movie", 2024, managed_folder)])

    service.reconcile()

    projected = library_root / "Relink Movie (2024)" / source.name
    assert projected.exists()
    assert projected.samefile(source)
    original_inode = source.stat().st_ino

    source.unlink()
    source.write_text("upgraded-content", encoding="utf-8")
    assert source.stat().st_ino != original_inode, "Sanity: new file should have different inode"

    service.reconcile()

    assert projected.exists()
    assert projected.samefile(source), "Projected file should be relinked to new source"
    assert projected.read_text(encoding="utf-8") == "upgraded-content"
