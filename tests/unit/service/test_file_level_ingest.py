import os
from pathlib import Path

from librariarr.service.reconcile_helpers import (
    FileIngestResult,
    ingest_files_from_library_folder,
)

VIDEO_EXTS = {".mkv", ".mp4", ".avi"}
EXTRAS = ["*.srt", "*.nfo", "poster.jpg", "fanart.jpg"]


def _write(path: Path, content: str = "data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_ingest_files_moves_new_file_to_managed(tmp_path: Path) -> None:
    lib = tmp_path / "library" / "Movie (2024)"
    managed = tmp_path / "managed" / "Movie (2024)"
    managed.mkdir(parents=True)

    _write(lib / "Movie.2024.1080p.mkv", "new-content")

    result = ingest_files_from_library_folder(
        library_folder=lib,
        managed_folder=managed,
        managed_video_extensions=VIDEO_EXTS,
        extras_allowlist=EXTRAS,
    )

    assert result.ingested_count == 1
    assert result.failed_count == 0
    assert (managed / "Movie.2024.1080p.mkv").exists()
    assert not (lib / "Movie.2024.1080p.mkv").exists()


def test_ingest_files_replaces_different_inode(tmp_path: Path) -> None:
    lib = tmp_path / "library" / "Movie (2024)"
    managed = tmp_path / "managed" / "Movie (2024)"

    _write(managed / "Movie.mkv", "old-quality")
    _write(lib / "Movie.mkv", "new-quality")

    old_inode = (managed / "Movie.mkv").stat().st_ino
    result = ingest_files_from_library_folder(
        library_folder=lib,
        managed_folder=managed,
        managed_video_extensions=VIDEO_EXTS,
        extras_allowlist=EXTRAS,
    )

    assert result.ingested_count == 1
    assert result.failed_count == 0
    assert (managed / "Movie.mkv").read_text(encoding="utf-8") == "new-quality"
    assert (managed / "Movie.mkv").stat().st_ino != old_inode
    assert not (lib / "Movie.mkv").exists()


def test_ingest_files_skips_same_inode(tmp_path: Path) -> None:
    lib = tmp_path / "library" / "Movie (2024)"
    managed = tmp_path / "managed" / "Movie (2024)"

    src = _write(managed / "Movie.mkv", "content")
    lib.mkdir(parents=True)
    os.link(str(src), str(lib / "Movie.mkv"))

    result = ingest_files_from_library_folder(
        library_folder=lib,
        managed_folder=managed,
        managed_video_extensions=VIDEO_EXTS,
        extras_allowlist=EXTRAS,
    )

    assert result == FileIngestResult(ingested_count=0, failed_count=0)


def test_ingest_files_skips_non_allowlisted_files(tmp_path: Path) -> None:
    lib = tmp_path / "library" / "Movie (2024)"
    managed = tmp_path / "managed" / "Movie (2024)"
    managed.mkdir(parents=True)

    _write(lib / "readme.txt", "ignore-me")

    result = ingest_files_from_library_folder(
        library_folder=lib,
        managed_folder=managed,
        managed_video_extensions=VIDEO_EXTS,
        extras_allowlist=EXTRAS,
    )

    assert result == FileIngestResult(ingested_count=0, failed_count=0)
    assert (lib / "readme.txt").exists()


def test_ingest_files_handles_extras(tmp_path: Path) -> None:
    lib = tmp_path / "library" / "Movie (2024)"
    managed = tmp_path / "managed" / "Movie (2024)"
    managed.mkdir(parents=True)

    _write(lib / "movie.nfo", "nfo-content")
    _write(lib / "poster.jpg", "jpg-content")

    result = ingest_files_from_library_folder(
        library_folder=lib,
        managed_folder=managed,
        managed_video_extensions=VIDEO_EXTS,
        extras_allowlist=EXTRAS,
    )

    assert result.ingested_count == 2
    assert (managed / "movie.nfo").exists()
    assert (managed / "poster.jpg").exists()


def test_ingest_files_creates_subdirectories(tmp_path: Path) -> None:
    lib = tmp_path / "library" / "Movie (2024)"
    managed = tmp_path / "managed" / "Movie (2024)"
    managed.mkdir(parents=True)

    _write(lib / "Subs" / "english.srt", "subtitle")

    result = ingest_files_from_library_folder(
        library_folder=lib,
        managed_folder=managed,
        managed_video_extensions=VIDEO_EXTS,
        extras_allowlist=EXTRAS,
    )

    assert result.ingested_count == 1
    assert (managed / "Subs" / "english.srt").exists()


def test_ingest_files_returns_zero_for_empty_folder(tmp_path: Path) -> None:
    lib = tmp_path / "library" / "Movie (2024)"
    managed = tmp_path / "managed" / "Movie (2024)"
    lib.mkdir(parents=True)
    managed.mkdir(parents=True)

    result = ingest_files_from_library_folder(
        library_folder=lib,
        managed_folder=managed,
        managed_video_extensions=VIDEO_EXTS,
        extras_allowlist=EXTRAS,
    )

    assert result == FileIngestResult(ingested_count=0, failed_count=0)


def test_ingest_files_mixed_upgrade_and_skip(tmp_path: Path) -> None:
    """Upgrade one video file while leaving an unchanged hardlink alone."""
    lib = tmp_path / "library" / "Movie (2024)"
    managed = tmp_path / "managed" / "Movie (2024)"

    old_video = _write(managed / "Movie.mkv", "old")
    lib.mkdir(parents=True)
    os.link(str(managed / "Movie.mkv"), str(lib / "Movie.mkv"))
    _write(lib / "poster.jpg", "new-poster")
    _write(managed / "poster.jpg", "old-poster")

    result = ingest_files_from_library_folder(
        library_folder=lib,
        managed_folder=managed,
        managed_video_extensions=VIDEO_EXTS,
        extras_allowlist=EXTRAS,
    )

    assert result.ingested_count == 1
    assert result.failed_count == 0
    assert (managed / "Movie.mkv").stat().st_ino == old_video.stat().st_ino
    assert (managed / "poster.jpg").read_text(encoding="utf-8") == "new-poster"
