"""Unit test: whole-folder ingest is skipped when a movie already has projections."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from librariarr.service import LibrariArrService
from tests.e2e.filesystem.conftest import make_movie, make_radarr_config


def _build_service(tmp_path: Path) -> tuple[LibrariArrService, Path, Path]:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"
    managed_root.mkdir()
    library_root.mkdir()
    config = make_radarr_config(
        managed_root=managed_root, library_root=library_root, sync_enabled=True
    )
    service = LibrariArrService(config)
    return service, managed_root, library_root


def test_ingest_skips_whole_folder_when_projections_exist(tmp_path: Path) -> None:
    """_ingest_movie_if_needed must NOT call _resolve_ingest_target when the
    movie already has tracked projections whose dest paths are under the source folder."""
    service, managed_root, library_root = _build_service(tmp_path)

    source = library_root / "Movie (2024)"
    source.mkdir(parents=True)
    (source / "Movie.2024.1080p.mkv").write_text("stub", encoding="utf-8")

    movie = make_movie(1, "Movie", 2024, source)

    # Simulate projection provenance: dest paths under the source (library) folder
    mock_state_store = MagicMock()
    projected_dest = str(source / "Movie.2024.1080p.mkv")
    mock_state_store.get_managed_paths_for_movie.return_value = {projected_dest}
    service.movie_projection = MagicMock()
    service.movie_projection.state_store = mock_state_store

    with patch.object(service, "_resolve_ingest_target") as mock_resolve:
        service._ingest_movie_if_needed(movie, affected_paths=None)

    mock_resolve.assert_not_called()
    mock_state_store.get_managed_paths_for_movie.assert_called_once_with(1)


def test_ingest_proceeds_with_whole_folder_when_no_projections(tmp_path: Path) -> None:
    """_ingest_movie_if_needed must call _resolve_ingest_target when the
    movie has NO tracked projections."""
    service, managed_root, library_root = _build_service(tmp_path)

    source = library_root / "Movie (2024)"
    source.mkdir(parents=True)
    (source / "Movie.2024.1080p.mkv").write_text("stub", encoding="utf-8")

    movie = make_movie(1, "Movie", 2024, source)

    # Simulate no projections
    mock_state_store = MagicMock()
    mock_state_store.get_managed_paths_for_movie.return_value = set()
    service.movie_projection = MagicMock()
    service.movie_projection.state_store = mock_state_store

    with patch.object(service, "_resolve_ingest_target", return_value=None) as mock_resolve:
        service._ingest_movie_if_needed(movie, affected_paths=None)

    mock_resolve.assert_called_once()


def test_ingest_proceeds_when_movie_projection_is_none(tmp_path: Path) -> None:
    """When movie_projection is None (Radarr disabled), whole-folder ingest proceeds."""
    service, managed_root, library_root = _build_service(tmp_path)

    source = library_root / "Movie (2024)"
    source.mkdir(parents=True)
    (source / "Movie.2024.1080p.mkv").write_text("stub", encoding="utf-8")

    movie = make_movie(1, "Movie", 2024, source)

    service.movie_projection = None

    with patch.object(service, "_resolve_ingest_target", return_value=None) as mock_resolve:
        service._ingest_movie_if_needed(movie, affected_paths=None)

    mock_resolve.assert_called_once()


def test_ingest_proceeds_when_projections_in_different_folder(tmp_path: Path) -> None:
    """Whole-folder ingest proceeds when projections exist but under a different
    library folder (different mapping)."""
    service, managed_root, library_root = _build_service(tmp_path)

    source = library_root / "Movie (2024)"
    source.mkdir(parents=True)
    (source / "Movie.2024.1080p.mkv").write_text("stub", encoding="utf-8")

    movie = make_movie(1, "Movie", 2024, source)

    # Projections exist but in a completely different folder
    mock_state_store = MagicMock()
    mock_state_store.get_managed_paths_for_movie.return_value = {
        "/other/library/Movie (2024)/Movie.2024.1080p.mkv"
    }
    service.movie_projection = MagicMock()
    service.movie_projection.state_store = mock_state_store

    with patch.object(service, "_resolve_ingest_target", return_value=None) as mock_resolve:
        service._ingest_movie_if_needed(movie, affected_paths=None)

    mock_resolve.assert_called_once()


def test_ingest_ignores_stale_projection_entries(tmp_path: Path) -> None:
    service, managed_root, library_root = _build_service(tmp_path)

    source = library_root / "Movie (2024)"
    source.mkdir(parents=True)
    (source / "Movie.2024.1080p.mkv").write_text("stub", encoding="utf-8")

    movie = make_movie(1, "Movie", 2024, source)

    stale_source = tmp_path / "stale" / "managed" / "Movie.2024.1080p.mkv"
    mock_state_store = MagicMock()
    mock_state_store.get_managed_entries_for_movie.return_value = [
        (str(source / "Movie.2024.1080p.mkv"), str(stale_source))
    ]
    service.movie_projection = MagicMock()
    service.movie_projection.state_store = mock_state_store

    with patch.object(service, "_resolve_ingest_target", return_value=None) as mock_resolve:
        service._ingest_movie_if_needed(movie, affected_paths=None)

    mock_resolve.assert_called_once()
