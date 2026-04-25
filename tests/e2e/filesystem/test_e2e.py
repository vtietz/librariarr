import os
import shutil
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


class _FakeRadarr:
    def __init__(self, movies: list[dict]) -> None:
        self.movies = movies

    def get_movies(self) -> list[dict]:
        return self.movies


def _movie(movie_id: int, title: str, year: int, path: Path) -> dict:
    return {
        "id": movie_id,
        "title": title,
        "year": year,
        "path": str(path),
        "movieFile": {"id": movie_id * 10},
        "monitored": True,
    }


def _make_roots(tmp_path: Path, case_name: str) -> tuple[Path, Path]:
    persist_root = os.getenv("LIBRARIARR_E2E_PERSIST_ROOT")
    if not persist_root:
        return tmp_path / "managed", tmp_path / "library"

    case_root = Path(persist_root) / case_name
    try:
        if case_root.exists():
            shutil.rmtree(case_root)
        managed_root = case_root / "managed"
        library_root = case_root / "library"
        managed_root.mkdir(parents=True, exist_ok=True)
        library_root.mkdir(parents=True, exist_ok=True)
        return managed_root, library_root
    except OSError:
        fallback_root = tmp_path / case_name
        if fallback_root.exists():
            shutil.rmtree(fallback_root)
        managed_root = fallback_root / "managed"
        library_root = fallback_root / "library"
        managed_root.mkdir(parents=True, exist_ok=True)
        library_root.mkdir(parents=True, exist_ok=True)
        return managed_root, library_root


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
def test_e2e_projection_creates_expected_hardlink_layout(tmp_path: Path) -> None:
    managed_root, library_root = _make_roots(tmp_path, "projection_hardlink_layout")

    movie_a = managed_root / "age_12" / "Blender" / "Fixture Catalog A (2008)"
    movie_b = managed_root / "age_16" / "OpenFilms" / "Sintel (2010)"
    movie_a.mkdir(parents=True)
    movie_b.mkdir(parents=True)

    source_a = movie_a / "Big.Buck.Bunny.2008.1080p.x265.mkv"
    source_b = movie_b / "Sintel.2010.2160p.REMUX.mkv"
    source_a.write_text("stub", encoding="utf-8")
    source_b.write_text("stub", encoding="utf-8")

    config = AppConfig(
        paths=PathsConfig(
            series_root_mappings=[],
            movie_root_mappings=[
                MovieRootMapping(managed_root=str(managed_root), library_root=str(library_root))
            ],
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
    service.radarr = _FakeRadarr(
        movies=[
            _movie(1, "Fixture Catalog A", 2008, movie_a),
            _movie(2, "Sintel", 2010, movie_b),
        ]
    )

    service.reconcile()

    projected_a = library_root / "age_12" / "Blender" / "Fixture Catalog A (2008)" / source_a.name
    projected_b = library_root / "age_16" / "OpenFilms" / "Sintel (2010)" / source_b.name

    assert projected_a.exists()
    assert projected_b.exists()
    assert projected_a.samefile(source_a)
    assert projected_b.samefile(source_b)


@pytest.mark.fs_e2e
def test_e2e_projection_respects_movie_root_mappings(tmp_path: Path) -> None:
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
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            sync_enabled=False,
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )

    service = LibrariArrService(config)
    service.radarr = _FakeRadarr(
        movies=[
            _movie(1, "Movie A", 2020, movie_a),
            _movie(2, "Movie B", 2021, movie_b),
        ]
    )

    service.reconcile()

    projected_a = library_a / "Movie A (2020)" / source_a.name
    projected_b = library_b / "Movie B (2021)" / source_b.name

    assert projected_a.exists()
    assert projected_b.exists()
    assert not (library_b / "Movie A (2020)").exists()
    assert not (library_a / "Movie B (2021)").exists()


@pytest.mark.fs_e2e
def test_e2e_projection_scopes_to_webhook_movie_ids(tmp_path: Path) -> None:
    managed_root, library_root = _make_roots(tmp_path, "projection_scoped_webhook")

    movie_a = managed_root / "Fixture Catalog A (2008)"
    movie_b = managed_root / "Fixture Catalog B (2009)"
    movie_a.mkdir(parents=True)
    movie_b.mkdir(parents=True)

    source_a = movie_a / "a.mkv"
    source_b = movie_b / "b.mkv"
    source_a.write_text("a", encoding="utf-8")
    source_b.write_text("b", encoding="utf-8")

    config = AppConfig(
        paths=PathsConfig(
            series_root_mappings=[],
            movie_root_mappings=[
                MovieRootMapping(managed_root=str(managed_root), library_root=str(library_root))
            ],
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
    service.radarr = _FakeRadarr(
        movies=[
            _movie(1, "Fixture Catalog A", 2008, movie_a),
            _movie(2, "Fixture Catalog B", 2009, movie_b),
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
def test_e2e_projection_does_not_ingest_shadow_folder(tmp_path: Path) -> None:
    managed_root, shadow_root = _make_roots(tmp_path, "ingest_moves_shadow_to_nested")
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
            enabled=False,
            url="http://radarr:7878",
            api_key="test",
            sync_enabled=False,
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
