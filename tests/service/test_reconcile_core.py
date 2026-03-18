from pathlib import Path

from librariarr.projection import get_radarr_webhook_queue
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


def test_reconcile_projects_movie_files_into_library_root(tmp_path: Path) -> None:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"
    movie_dir = managed_root / "Fixture Catalog A (2008)"
    movie_dir.mkdir(parents=True)

    movie_file = movie_dir / "Big.Buck.Bunny.2008.1080p.x265.mkv"
    subtitle_file = movie_dir / "Big.Buck.Bunny.2008.srt"
    movie_file.write_text("x", encoding="utf-8")
    subtitle_file.write_text("sub", encoding="utf-8")

    config = make_config(managed_root, library_root, sync_enabled=False)
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        movies=[_movie(1, "Fixture Catalog A", 2008, movie_dir)],
    )

    service.reconcile()

    projected_movie = _projected_file(
        library_root,
        "Fixture Catalog A (2008)",
        "Big.Buck.Bunny.2008.1080p.x265.mkv",
    )
    projected_subtitle = _projected_file(
        library_root,
        "Fixture Catalog A (2008)",
        "Big.Buck.Bunny.2008.srt",
    )

    assert projected_movie.exists()
    assert projected_subtitle.exists()
    assert projected_movie.samefile(movie_file)
    assert projected_subtitle.samefile(subtitle_file)


def test_reconcile_uses_current_radarr_client_for_projection(tmp_path: Path) -> None:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"
    movie_dir = managed_root / "Fixture Catalog A (2008)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "movie.mkv").write_text("x", encoding="utf-8")

    config = make_config(managed_root, library_root, sync_enabled=False)
    service = LibrariArrService(config)

    fake = FakeRadarr(movies=[_movie(1, "Fixture Catalog A", 2008, movie_dir)])
    service.radarr = fake

    service.reconcile()

    assert fake.get_movies_calls == 1


def test_reconcile_scopes_projection_to_webhook_movie_ids(tmp_path: Path) -> None:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"

    movie_a_dir = managed_root / "Fixture Catalog A (2008)"
    movie_b_dir = managed_root / "Fixture Catalog B (2009)"
    movie_a_dir.mkdir(parents=True)
    movie_b_dir.mkdir(parents=True)
    (movie_a_dir / "a.mkv").write_text("a", encoding="utf-8")
    (movie_b_dir / "b.mkv").write_text("b", encoding="utf-8")

    config = make_config(managed_root, library_root, sync_enabled=False)
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        movies=[
            _movie(1, "Fixture Catalog A", 2008, movie_a_dir),
            _movie(2, "Fixture Catalog B", 2009, movie_b_dir),
        ]
    )

    queue = get_radarr_webhook_queue()
    queue.consume_movie_ids()
    queue.enqueue(
        movie_id=2,
        event_type="Test",
        normalized_path=str(movie_b_dir),
    )

    service.reconcile()

    projected_a = _projected_file(library_root, "Fixture Catalog A (2008)", "a.mkv")
    projected_b = _projected_file(library_root, "Fixture Catalog B (2009)", "b.mkv")

    assert not projected_a.exists()
    assert projected_b.exists()

    queue.consume_movie_ids()


def test_reconcile_skips_movie_projection_when_radarr_disabled(tmp_path: Path) -> None:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"
    movie_dir = managed_root / "Fixture Catalog A (2008)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "movie.mkv").write_text("x", encoding="utf-8")

    config = make_config(
        managed_root,
        library_root,
        sync_enabled=False,
        radarr_enabled=False,
    )
    service = LibrariArrService(config)

    service.reconcile()

    assert not _projected_file(library_root, "Fixture Catalog A (2008)", "movie.mkv").exists()
