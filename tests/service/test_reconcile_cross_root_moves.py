from pathlib import Path

from librariarr.config import MovieRootMapping
from librariarr.service import LibrariArrService
from tests.service.helpers import FakeRadarr, make_config


def _movie(movie_id: int, title: str, year: int, path: Path) -> dict:
    return {
        "id": movie_id,
        "title": title,
        "year": year,
        "path": str(path),
        "movieFile": {"id": movie_id * 10},
        "monitored": True,
    }


def _projected_file(library_root: Path, folder_name: str, filename: str) -> Path:
    return library_root / folder_name / filename


def test_incremental_reconcile_removes_stale_shadow_when_movie_moves_between_roots(
    tmp_path: Path,
) -> None:
    managed_fsk16 = tmp_path / "managed" / "FSK16"
    managed_fsk12 = tmp_path / "managed" / "FSK12"
    shadow_fsk16 = tmp_path / "shadow" / "FSK16"
    shadow_fsk12 = tmp_path / "shadow" / "FSK12"

    original_managed_folder = managed_fsk16 / "Fixture Move (2024)"
    original_managed_folder.mkdir(parents=True)
    original_file = original_managed_folder / "Fixture.Move.2024.1080p.mkv"
    original_file.write_text("x", encoding="utf-8")

    config = make_config(managed_fsk16, shadow_fsk16, sync_enabled=False)
    config.paths.movie_root_mappings.append(
        MovieRootMapping(managed_root=str(managed_fsk12), library_root=str(shadow_fsk12))
    )

    service = LibrariArrService(config)
    movie = _movie(55, "Fixture Move", 2024, original_managed_folder)
    service.radarr = FakeRadarr(movies=[movie])

    service.reconcile()

    old_projected = _projected_file(
        shadow_fsk16,
        "Fixture Move (2024)",
        "Fixture.Move.2024.1080p.mkv",
    )
    assert old_projected.exists()
    assert old_projected.samefile(original_file)

    moved_managed_folder = managed_fsk12 / "Fixture Move (2024)"
    moved_managed_folder.mkdir(parents=True)
    moved_file = moved_managed_folder / "Fixture.Move.2024.1080p.mkv"
    original_file.rename(moved_file)
    movie["path"] = str(moved_managed_folder)

    service.reconcile(affected_paths={shadow_fsk12 / "Fixture Move (2024)"})

    new_projected = _projected_file(
        shadow_fsk12,
        "Fixture Move (2024)",
        "Fixture.Move.2024.1080p.mkv",
    )
    assert new_projected.exists()
    assert new_projected.samefile(moved_file)
    assert not old_projected.exists()


def test_incremental_reconcile_prunes_old_shadow_when_movie_repointed_between_roots(
    tmp_path: Path,
) -> None:
    managed_fsk16 = tmp_path / "managed" / "FSK16"
    managed_fsk12 = tmp_path / "managed" / "FSK12"
    shadow_fsk16 = tmp_path / "shadow" / "FSK16"
    shadow_fsk12 = tmp_path / "shadow" / "FSK12"

    original_managed_folder = managed_fsk16 / "Fixture Repoint (2024)"
    original_managed_folder.mkdir(parents=True)
    original_file = original_managed_folder / "Fixture.Repoint.2024.1080p.mkv"
    original_file.write_text("old", encoding="utf-8")

    config = make_config(managed_fsk16, shadow_fsk16, sync_enabled=False)
    config.paths.movie_root_mappings.append(
        MovieRootMapping(managed_root=str(managed_fsk12), library_root=str(shadow_fsk12))
    )

    service = LibrariArrService(config)
    movie = _movie(56, "Fixture Repoint", 2024, original_managed_folder)
    service.radarr = FakeRadarr(movies=[movie])

    service.reconcile()

    old_projected = _projected_file(
        shadow_fsk16,
        "Fixture Repoint (2024)",
        "Fixture.Repoint.2024.1080p.mkv",
    )
    assert old_projected.exists()
    assert old_projected.samefile(original_file)

    new_managed_folder = managed_fsk12 / "Fixture Repoint (2024)"
    new_managed_folder.mkdir(parents=True)
    new_file = new_managed_folder / "Fixture.Repoint.2024.1080p.mkv"
    new_file.write_text("new", encoding="utf-8")
    movie["path"] = str(new_managed_folder)

    service.reconcile(affected_paths={new_managed_folder})

    new_projected = _projected_file(
        shadow_fsk12,
        "Fixture Repoint (2024)",
        "Fixture.Repoint.2024.1080p.mkv",
    )
    assert new_projected.exists()
    assert new_projected.samefile(new_file)
    assert not old_projected.exists()
