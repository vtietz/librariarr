from __future__ import annotations

from pathlib import Path

from librariarr.projection.models import ProjectedFileState
from librariarr.projection.provenance import ProjectionStateStore


def _sample_state(*, movie_id: int, source_path: Path, dest_path: Path) -> ProjectedFileState:
    return ProjectedFileState(
        movie_id=movie_id,
        dest_path=str(dest_path),
        source_path=str(source_path),
        kind="video",
        managed=True,
        source_dev=None,
        source_inode=None,
        size=1,
        mtime=1.0,
        file_hash=None,
    )


def test_resolve_movie_ids_by_paths_matches_source_prefix_for_deleted_folder(
    tmp_path: Path,
) -> None:
    store = ProjectionStateStore(tmp_path / "projection.db")

    managed_folder = tmp_path / "managed" / "Family Is Family (2018)"
    source_path = managed_folder / "Family.Is.Family.2018.mkv"
    dest_path = tmp_path / "library" / "Family Is Family (2018)" / "Family.Is.Family.2018.mkv"

    store.upsert_projected_files(
        [_sample_state(movie_id=42, source_path=source_path, dest_path=dest_path)]
    )

    resolved = store.resolve_movie_ids_by_paths({managed_folder})

    assert resolved == {42}


def test_resolve_movie_ids_by_paths_matches_exact_source_file_path(tmp_path: Path) -> None:
    store = ProjectionStateStore(tmp_path / "projection.db")

    source_path = tmp_path / "managed" / "Movie A (2020)" / "Movie.A.2020.mkv"
    dest_path = tmp_path / "library" / "Movie A (2020)" / "Movie.A.2020.mkv"

    store.upsert_projected_files(
        [_sample_state(movie_id=7, source_path=source_path, dest_path=dest_path)]
    )

    resolved = store.resolve_movie_ids_by_paths({source_path})

    assert resolved == {7}


def test_resolve_series_ids_by_paths_matches_source_prefix_for_renamed_folder(
    tmp_path: Path,
) -> None:
    store = ProjectionStateStore(tmp_path / "projection.db")

    source_folder = tmp_path / "series" / "Family Show (2018)"
    source_path = source_folder / "Season 01" / "Family.Show.S01E01.mkv"
    dest_path = tmp_path / "series-shadow" / "Family Show (2018)" / "Season 01" / "E01.mkv"

    store.upsert_projected_files(
        [_sample_state(movie_id=301, source_path=source_path, dest_path=dest_path)]
    )

    resolved = store.resolve_series_ids_by_paths({source_folder})

    assert resolved == {301}


def test_resolve_series_ids_by_paths_matches_exact_source_file_path(tmp_path: Path) -> None:
    store = ProjectionStateStore(tmp_path / "projection.db")

    source_path = tmp_path / "series" / "Show A (2020)" / "Season 01" / "Show.A.S01E01.mkv"
    dest_path = tmp_path / "series-shadow" / "Show A (2020)" / "Season 01" / "E01.mkv"

    store.upsert_projected_files(
        [_sample_state(movie_id=302, source_path=source_path, dest_path=dest_path)]
    )

    resolved = store.resolve_series_ids_by_paths({source_path})

    assert resolved == {302}
