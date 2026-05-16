from __future__ import annotations

import logging
import os
from pathlib import Path

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    MovieRootMapping,
    PathsConfig,
    RadarrConfig,
    RuntimeConfig,
)
from librariarr.projection.models import ProjectedFileState
from librariarr.projection.orchestrator import MovieProjectionOrchestrator


class FakeRadarr:
    def __init__(self) -> None:
        self.update_calls: list[tuple[int, str]] = []

    def update_movie_path(self, movie: dict, new_path: str) -> bool:
        self.update_calls.append((int(movie.get("id") or 0), new_path))
        if str(movie.get("path") or "") == new_path:
            return False
        movie["path"] = new_path
        return True


def _make_config(tmp_path: Path) -> AppConfig:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)

    return AppConfig(
        paths=PathsConfig(
            movie_root_mappings=[
                MovieRootMapping(
                    managed_root=str(managed_root),
                    library_root=str(library_root),
                )
            ]
        ),
        radarr=RadarrConfig(url="http://radarr:7878", api_key="test-key"),
        cleanup=CleanupConfig(),
        runtime=RuntimeConfig(),
    )


def _make_orchestrator(
    tmp_path: Path,
) -> tuple[MovieProjectionOrchestrator, FakeRadarr, AppConfig]:
    state_db = tmp_path / "state.db"
    config = _make_config(tmp_path)
    radarr = FakeRadarr()

    # Keep projection state local to the test temp directory.
    previous = os.getenv("LIBRARIARR_PROJECTION_STATE_PATH")
    os.environ["LIBRARIARR_PROJECTION_STATE_PATH"] = str(state_db)
    try:
        orchestrator = MovieProjectionOrchestrator(
            config=config,
            radarr=radarr,  # type: ignore[arg-type]
            logger=logging.getLogger(__name__),
        )
    finally:
        if previous is None:
            os.environ.pop("LIBRARIARR_PROJECTION_STATE_PATH", None)
        else:
            os.environ["LIBRARIARR_PROJECTION_STATE_PATH"] = previous

    return orchestrator, radarr, config


def test_backfill_recovers_unique_managed_folder_from_provenance(tmp_path: Path) -> None:
    orchestrator, radarr, config = _make_orchestrator(tmp_path)
    managed_folder = (
        Path(config.paths.movie_root_mappings[0].managed_root) / "The Cabin in the Woods (2012)"
    )
    managed_folder.mkdir(parents=True)
    (managed_folder / "movie.mkv").write_text("x")

    movie = {
        "id": 3730,
        "title": "The Cabin in the Woods",
        "year": 2012,
        "path": str(
            Path(config.paths.movie_root_mappings[0].library_root)
            / "The Cabin in the Woods (2012) FSK16"
        ),
    }

    orchestrator.state_store.upsert_projected_files(
        [
            ProjectedFileState(
                movie_id=3730,
                dest_path=str(
                    Path(config.paths.movie_root_mappings[0].library_root)
                    / "The Cabin in the Woods (2012)"
                    / "movie.mkv"
                ),
                source_path=str(managed_folder / "movie.mkv"),
                kind="video",
                managed=True,
                source_dev=None,
                source_inode=None,
                size=1,
                mtime=1.0,
                file_hash=None,
            )
        ]
    )

    repaired = orchestrator._backfill_managed_folder_mappings_from_provenance([movie])
    managed_map = orchestrator.state_store.get_managed_folders_by_movie_ids()

    assert repaired == 1
    assert managed_map[3730] == managed_folder
    assert radarr.update_calls == []


def test_backfill_skips_ambiguous_managed_folders(tmp_path: Path) -> None:
    orchestrator, _radarr, config = _make_orchestrator(tmp_path)
    managed_root = Path(config.paths.movie_root_mappings[0].managed_root)
    library_root = Path(config.paths.movie_root_mappings[0].library_root)

    folder_a = managed_root / "Rango (2011) FSK6"
    folder_b = managed_root / "Rango (2011) Director Cut"
    folder_a.mkdir(parents=True)
    folder_b.mkdir(parents=True)
    (folder_a / "a.mkv").write_text("x")
    (folder_b / "b.mkv").write_text("x")

    orchestrator.state_store.upsert_projected_files(
        [
            ProjectedFileState(
                movie_id=99,
                dest_path=str(library_root / "Rango (2011)" / "a.mkv"),
                source_path=str(folder_a / "a.mkv"),
                kind="video",
                managed=True,
                source_dev=None,
                source_inode=None,
                size=1,
                mtime=1.0,
                file_hash=None,
            ),
            ProjectedFileState(
                movie_id=99,
                dest_path=str(library_root / "Rango (2011)" / "b.mkv"),
                source_path=str(folder_b / "b.mkv"),
                kind="video",
                managed=True,
                source_dev=None,
                source_inode=None,
                size=1,
                mtime=1.0,
                file_hash=None,
            ),
        ]
    )

    repaired = orchestrator._backfill_managed_folder_mappings_from_provenance(
        [{"id": 99, "title": "Rango", "year": 2011, "path": str(library_root / "Rango (2011)")}]
    )
    managed_map = orchestrator.state_store.get_managed_folders_by_movie_ids()

    assert repaired == 0
    assert 99 not in managed_map


def test_backfill_skips_conflicting_managed_folder_title(tmp_path: Path) -> None:
    orchestrator, _radarr, config = _make_orchestrator(tmp_path)
    managed_root = Path(config.paths.movie_root_mappings[0].managed_root)
    library_root = Path(config.paths.movie_root_mappings[0].library_root)

    wrong_folder = managed_root / "Zwei Banditen (1969) FSK16"
    wrong_folder.mkdir(parents=True)
    (wrong_folder / "movie.mkv").write_text("x")

    orchestrator.state_store.upsert_projected_files(
        [
            ProjectedFileState(
                movie_id=3775,
                dest_path=str(library_root / "Z (1969)" / "movie.mkv"),
                source_path=str(wrong_folder / "movie.mkv"),
                kind="video",
                managed=True,
                source_dev=None,
                source_inode=None,
                size=1,
                mtime=1.0,
                file_hash=None,
            )
        ]
    )

    repaired = orchestrator._backfill_managed_folder_mappings_from_provenance(
        [{"id": 3775, "title": "Z", "year": 1969, "path": str(library_root / "Z (1969)")}]
    )

    managed_map = orchestrator.state_store.get_managed_folders_by_movie_ids()
    assert repaired == 0
    assert 3775 not in managed_map


def test_backfill_skips_folder_already_mapped_to_other_movie(tmp_path: Path) -> None:
    orchestrator, _radarr, config = _make_orchestrator(tmp_path)
    managed_root = Path(config.paths.movie_root_mappings[0].managed_root)
    library_root = Path(config.paths.movie_root_mappings[0].library_root)

    shared_folder = managed_root / "Shared Folder (2001)"
    shared_folder.mkdir(parents=True)
    (shared_folder / "movie.mkv").write_text("x")
    orchestrator.state_store.set_managed_folders_bulk([(1001, shared_folder)])

    orchestrator.state_store.upsert_projected_files(
        [
            ProjectedFileState(
                movie_id=1002,
                dest_path=str(library_root / "Shared Folder (2001)" / "movie.mkv"),
                source_path=str(shared_folder / "movie.mkv"),
                kind="video",
                managed=True,
                source_dev=None,
                source_inode=None,
                size=1,
                mtime=1.0,
                file_hash=None,
            )
        ]
    )

    repaired = orchestrator._backfill_managed_folder_mappings_from_provenance(
        [
            {
                "id": 1002,
                "title": "Shared Folder",
                "year": 2001,
                "path": str(library_root / "Shared Folder (2001)"),
            }
        ]
    )

    managed_map = orchestrator.state_store.get_managed_folders_by_movie_ids()
    assert repaired == 0
    assert managed_map[1001] == shared_folder
    assert 1002 not in managed_map
