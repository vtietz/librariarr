import os
import shutil
from pathlib import Path

import pytest

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    IngestConfig,
    PathsConfig,
    RadarrConfig,
    RootMapping,
    RuntimeConfig,
)
from librariarr.service import LibrariArrService


def _make_roots(tmp_path: Path, case_name: str) -> tuple[Path, Path]:
    persist_root = os.getenv("LIBRARIARR_E2E_PERSIST_ROOT")
    if not persist_root:
        return tmp_path / "movies", tmp_path / "radarr_library"

    case_root = Path(persist_root) / case_name
    if case_root.exists():
        shutil.rmtree(case_root)
    movies_root = case_root / "movies"
    shadow_root = case_root / "radarr_library"
    movies_root.mkdir(parents=True, exist_ok=True)
    shadow_root.mkdir(parents=True, exist_ok=True)
    return movies_root, shadow_root


def _relativize_links_for_host_view(shadow_root: Path) -> None:
    persist_root = os.getenv("LIBRARIARR_E2E_PERSIST_ROOT")
    if not persist_root:
        return

    for link in shadow_root.iterdir():
        if not link.is_symlink():
            continue
        target = link.resolve(strict=False)
        relative_target = os.path.relpath(str(target), start=str(link.parent))
        link.unlink(missing_ok=True)
        link.symlink_to(relative_target, target_is_directory=True)


@pytest.mark.fs_e2e
def test_e2e_reconcile_creates_expected_symlink_layout(tmp_path: Path) -> None:
    nested_root, shadow_root = _make_roots(tmp_path, "creates_symlink_layout")

    movie_a = nested_root / "age_12" / "Blender" / "Fixture Catalog A (2008)"
    movie_b = nested_root / "age_16" / "OpenFilms" / "Sintel (2010)"
    movie_a.mkdir(parents=True)
    movie_b.mkdir(parents=True)

    # Small stub files are enough to trigger movie discovery.
    (movie_a / "Big.Buck.Bunny.2008.1080p.x265.mkv").write_text("stub", encoding="utf-8")
    (movie_b / "Sintel.2010.2160p.REMUX.mkv").write_text("stub", encoding="utf-8")

    config = AppConfig(
        paths=PathsConfig(
            root_mappings=[
                RootMapping(nested_root=str(nested_root), shadow_root=str(shadow_root)),
            ]
        ),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            sync_enabled=False,
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )

    service = LibrariArrService(config)
    service.reconcile()
    _relativize_links_for_host_view(shadow_root)

    link_a = shadow_root / "Fixture Catalog A (2008)"
    link_b = shadow_root / "Sintel (2010)"

    assert link_a.is_symlink()
    assert link_a.resolve(strict=False) == movie_a
    assert link_b.is_symlink()
    assert link_b.resolve(strict=False) == movie_b


@pytest.mark.fs_e2e
def test_e2e_reconcile_handles_collisions_and_orphans(tmp_path: Path) -> None:
    root_base, shadow_root = _make_roots(tmp_path, "collision_and_orphan_cleanup")
    root_one = root_base / "source_a"
    root_two = root_base / "source_b"

    movie_one = root_one / "age_12" / "Blender" / "Sintel (2010)"
    movie_two = root_two / "age_16" / "OpenFilms" / "Sintel (2010)"
    movie_one.mkdir(parents=True)
    movie_two.mkdir(parents=True)
    (movie_one / "Sintel.2010.1080p.x265.mkv").write_text("stub", encoding="utf-8")
    (movie_two / "Sintel.2010.1080p.x265.mkv").write_text("stub", encoding="utf-8")

    config = AppConfig(
        paths=PathsConfig(
            root_mappings=[
                RootMapping(nested_root=str(root_one), shadow_root=str(shadow_root)),
                RootMapping(nested_root=str(root_two), shadow_root=str(shadow_root)),
            ]
        ),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            sync_enabled=False,
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )

    service = LibrariArrService(config)
    service.reconcile()
    _relativize_links_for_host_view(shadow_root)

    plain_link = shadow_root / "Sintel (2010)"
    qualified_link = shadow_root / "Sintel (2010)--source_b-age_16-OpenFilms"
    assert plain_link.is_symlink()
    assert qualified_link.is_symlink()

    # Remove one source and reconcile to verify orphan cleanup end-to-end.
    for child in movie_two.iterdir():
        child.unlink()
    movie_two.rmdir()

    service.reconcile()
    _relativize_links_for_host_view(shadow_root)

    assert plain_link.is_symlink()
    assert not qualified_link.exists()


@pytest.mark.fs_e2e
def test_e2e_reconcile_respects_root_mappings(tmp_path: Path) -> None:
    root_base, shadow_root = _make_roots(tmp_path, "mapped_roots")
    age12_root = root_base / "age_12"
    age16_root = root_base / "age_16"
    age12_shadow = shadow_root / "age_12"
    age16_shadow = shadow_root / "age_16"

    movie_age12 = age12_root / "Studio" / "Movie A (2020)"
    movie_age16 = age16_root / "Studio" / "Movie B (2021)"
    movie_age12.mkdir(parents=True)
    movie_age16.mkdir(parents=True)
    (movie_age12 / "Movie.A.2020.1080p.x265.mkv").write_text("stub", encoding="utf-8")
    (movie_age16 / "Movie.B.2021.1080p.x265.mkv").write_text("stub", encoding="utf-8")

    config = AppConfig(
        paths=PathsConfig(
            root_mappings=[
                RootMapping(nested_root=str(age12_root), shadow_root=str(age12_shadow)),
                RootMapping(nested_root=str(age16_root), shadow_root=str(age16_shadow)),
            ]
        ),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            sync_enabled=False,
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )

    service = LibrariArrService(config)
    service.reconcile()
    _relativize_links_for_host_view(age12_shadow)
    _relativize_links_for_host_view(age16_shadow)

    assert (age12_shadow / "Movie A (2020)").is_symlink()
    assert not (age16_shadow / "Movie A (2020)").exists()
    assert (age16_shadow / "Movie B (2021)").is_symlink()
    assert not (age12_shadow / "Movie B (2021)").exists()


@pytest.mark.fs_e2e
def test_e2e_ingest_moves_shadow_folder_into_nested_root(tmp_path: Path) -> None:
    root_base, shadow_root = _make_roots(tmp_path, "ingest_moves_shadow_to_nested")
    nested_root = root_base / "age_12"
    mapped_shadow = shadow_root / "age_12"

    imported_dir = mapped_shadow / "Imported Movie (2024)"
    imported_dir.mkdir(parents=True)
    (imported_dir / "Imported.Movie.2024.1080p.mkv").write_text("stub", encoding="utf-8")

    config = AppConfig(
        paths=PathsConfig(
            root_mappings=[
                RootMapping(nested_root=str(nested_root), shadow_root=str(mapped_shadow)),
            ]
        ),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            sync_enabled=False,
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
        ingest=IngestConfig(enabled=True, min_age_seconds=0),
    )

    service = LibrariArrService(config)
    service.reconcile()
    _relativize_links_for_host_view(mapped_shadow)

    destination = nested_root / "Imported Movie (2024)"
    shadow_link = mapped_shadow / "Imported Movie (2024)"
    assert destination.exists()
    assert shadow_link.is_symlink()
    assert shadow_link.resolve(strict=False) == destination


@pytest.mark.fs_e2e
def test_e2e_incremental_reconcile_limits_orphan_cleanup_to_affected_paths(
    tmp_path: Path,
) -> None:
    nested_root, shadow_root = _make_roots(tmp_path, "incremental_affected_paths")

    movie_a = nested_root / "age_12" / "Blender" / "Fixture Catalog A (2008)"
    movie_b = nested_root / "age_16" / "OpenFilms" / "Sintel (2010)"
    movie_a.mkdir(parents=True)
    movie_b.mkdir(parents=True)
    (movie_a / "Big.Buck.Bunny.2008.1080p.x265.mkv").write_text("stub", encoding="utf-8")
    (movie_b / "Sintel.2010.2160p.REMUX.mkv").write_text("stub", encoding="utf-8")

    config = AppConfig(
        paths=PathsConfig(
            root_mappings=[
                RootMapping(nested_root=str(nested_root), shadow_root=str(shadow_root)),
            ]
        ),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            sync_enabled=False,
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )

    service = LibrariArrService(config)
    service.reconcile()
    _relativize_links_for_host_view(shadow_root)

    link_a = shadow_root / "Fixture Catalog A (2008)"
    link_b = shadow_root / "Sintel (2010)"
    assert link_a.is_symlink()
    assert link_b.is_symlink()

    for child in movie_b.iterdir():
        child.unlink()
    movie_b.rmdir()

    changed_path_in_a = movie_a / "notes.txt"
    changed_path_in_a.write_text("changed", encoding="utf-8")
    service.reconcile({changed_path_in_a})
    _relativize_links_for_host_view(shadow_root)

    assert link_a.is_symlink()
    assert link_b.is_symlink()

    service.reconcile()
    _relativize_links_for_host_view(shadow_root)

    assert link_a.is_symlink()
    assert not link_b.exists()
