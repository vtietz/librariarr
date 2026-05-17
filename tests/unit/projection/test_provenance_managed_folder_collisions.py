from __future__ import annotations

from pathlib import Path

from librariarr.projection.provenance import ProjectionStateStore


def test_set_managed_folder_rejects_collision_without_force(tmp_path: Path) -> None:
    store = ProjectionStateStore(tmp_path / "projection-state.sqlite")
    shared_folder = tmp_path / "shared"

    assert store.set_managed_folder(100, shared_folder) is True
    assert store.set_managed_folder(200, shared_folder) is False

    mappings = store.get_managed_folders_by_movie_ids()
    assert mappings[100] == shared_folder
    assert 200 not in mappings


def test_set_managed_folder_force_takeover_reassigns_owner(tmp_path: Path) -> None:
    store = ProjectionStateStore(tmp_path / "projection-state.sqlite")
    shared_folder = tmp_path / "shared"

    assert store.set_managed_folder(100, shared_folder) is True
    assert store.set_managed_folder(200, shared_folder, force_takeover=True) is True

    mappings = store.get_managed_folders_by_movie_ids()
    assert mappings[200] == shared_folder
    assert 100 not in mappings


def test_set_managed_folders_bulk_skips_colliding_folder_assignment(tmp_path: Path) -> None:
    store = ProjectionStateStore(tmp_path / "projection-state.sqlite")
    existing_folder = tmp_path / "folder-a"
    replacement_folder = tmp_path / "folder-b"

    assert store.set_managed_folder(10, existing_folder) is True

    written = store.set_managed_folders_bulk(
        [
            (10, replacement_folder),
            (20, replacement_folder),
        ]
    )

    assert written == 1
    mappings = store.get_managed_folders_by_movie_ids()
    assert mappings[10] == replacement_folder
    assert 20 not in mappings
