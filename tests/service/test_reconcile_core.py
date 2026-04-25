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


def test_reconcile_auto_adds_unmatched_movie_folder_when_enabled(tmp_path: Path) -> None:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"
    movie_dir = managed_root / "Fixture Auto Add (2017)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Fixture.Auto.Add.2017.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(
        managed_root,
        library_root,
        sync_enabled=True,
        auto_add_unmatched=True,
    )
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        movies=[],
        quality_profiles=[{"id": 7, "name": "1080p"}],
        lookup_results=[{"title": "Fixture Auto Add", "year": 2017, "tmdbId": 1001}],
        add_movie_result={
            "id": 42,
            "title": "Fixture Auto Add",
            "year": 2017,
            "path": str(library_root / "Fixture Auto Add (2017)"),
            "movieFile": {"id": 420},
            "monitored": True,
        },
    )

    service.reconcile()

    assert service.radarr.added_movies
    assert service.radarr.added_movies[0]["quality_profile_id"] == 7


def test_reconcile_ingests_movie_from_library_root_before_projection(tmp_path: Path) -> None:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"
    incoming = library_root / "Fixture Ingest (2024)"
    incoming.mkdir(parents=True)
    incoming_file = incoming / "Fixture.Ingest.2024.1080p.x265.mkv"
    incoming_file.write_text("x", encoding="utf-8")

    config = make_config(managed_root, library_root, sync_enabled=True)
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        movies=[
            _movie(
                77,
                "Fixture Ingest",
                2024,
                incoming,
            )
        ]
    )

    service.reconcile()

    moved_folder = managed_root / "Fixture Ingest (2024)"
    moved_file = moved_folder / "Fixture.Ingest.2024.1080p.x265.mkv"
    projected_file = _projected_file(
        library_root,
        "Fixture Ingest (2024)",
        "Fixture.Ingest.2024.1080p.x265.mkv",
    )

    assert moved_folder.exists()
    assert moved_file.exists()
    assert projected_file.exists()
    assert projected_file.samefile(moved_file)
    assert service.radarr.updated_paths == [(77, str(moved_folder))]


def test_reconcile_ingest_skips_when_destination_exists_and_strategy_skip(tmp_path: Path) -> None:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"

    existing_managed = managed_root / "Fixture Ingest (2024)"
    existing_managed.mkdir(parents=True)
    (existing_managed / "existing.mkv").write_text("old", encoding="utf-8")

    incoming = library_root / "Fixture Ingest (2024)"
    incoming.mkdir(parents=True)
    incoming_file = incoming / "incoming.mkv"
    incoming_file.write_text("new", encoding="utf-8")

    config = make_config(managed_root, library_root, sync_enabled=True)
    config.ingest.collision_strategy = "skip"
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        movies=[_movie(77, "Fixture Ingest", 2024, incoming)],
    )

    service.reconcile()

    assert incoming.exists()
    assert incoming_file.exists()
    assert existing_managed.exists()
    assert service.radarr.updated_paths == []
