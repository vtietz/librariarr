import os
from pathlib import Path

import requests

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


def test_reconcile_logs_scope_resolution_for_webhook_movie_scope(tmp_path: Path, caplog) -> None:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"

    movie_dir = managed_root / "Fixture Catalog A (2008)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "a.mkv").write_text("a", encoding="utf-8")

    config = make_config(managed_root, library_root, sync_enabled=False)
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        movies=[_movie(2, "Fixture Catalog A", 2008, movie_dir)],
    )

    queue = get_radarr_webhook_queue()
    queue.consume_movie_ids()
    queue.enqueue(movie_id=2, event_type="Test", normalized_path=str(movie_dir))

    caplog.set_level("INFO", logger="librariarr.service")
    service.reconcile()

    assert "Reconcile scope resolved:" in caplog.text
    assert "movie_scope=scoped" in caplog.text
    assert "movie_count=1" in caplog.text
    assert "Projection dispatch: arr=radarr" in caplog.text

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


def test_reconcile_projects_auto_added_movies_immediately_in_incremental_mode(
    tmp_path: Path,
) -> None:
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
            "path": str(movie_dir),
            "movieFile": {"id": 420},
            "monitored": True,
        },
    )

    projection_calls: list[set[int] | None] = []

    def _capture_projection(scoped_movie_ids: set[int] | None, **kwargs) -> dict[str, int]:
        projection_calls.append(None if scoped_movie_ids is None else set(scoped_movie_ids))
        return {
            "scoped_movie_count": len(scoped_movie_ids or set()),
            "planned_movies": 0,
            "skipped_movies": 0,
            "projected_files": 0,
            "unchanged_files": 0,
            "skipped_files": 0,
        }

    service.movie_projection.reconcile = _capture_projection

    service.reconcile(affected_paths={movie_dir})

    assert projection_calls[0] == {42}
    assert None not in projection_calls


def test_reconcile_ingests_movie_from_library_root_before_projection(tmp_path: Path) -> None:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"
    incoming = library_root / "Fixture Ingest (2024)"
    incoming.mkdir(parents=True)
    incoming_file = incoming / "Fixture.Ingest.2024.1080p.x265.mkv"
    incoming_file.write_text("x", encoding="utf-8")

    config = make_config(managed_root, library_root, sync_enabled=True)
    config.ingest.enabled = True
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
    assert service.radarr.updated_paths == []


def test_reconcile_ingest_moves_new_file_when_managed_exists(tmp_path: Path) -> None:
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
    config.ingest.enabled = True
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        movies=[_movie(77, "Fixture Ingest", 2024, incoming)],
    )

    service.reconcile()

    assert (existing_managed / "incoming.mkv").exists()
    assert (existing_managed / "incoming.mkv").read_text(encoding="utf-8") == "new"
    assert service.radarr.updated_paths == []


def test_full_reconcile_projects_all_movies_even_with_ingest_ids(tmp_path: Path) -> None:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"

    movie_a_dir = managed_root / "Fixture Catalog A (2008)"
    movie_b_dir = managed_root / "Fixture Catalog B (2009)"
    movie_a_dir.mkdir(parents=True)
    movie_b_dir.mkdir(parents=True)
    (movie_a_dir / "a.mkv").write_text("a", encoding="utf-8")
    (movie_b_dir / "b.mkv").write_text("b", encoding="utf-8")

    config = make_config(managed_root, library_root, sync_enabled=True)
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        movies=[
            _movie(1, "Fixture Catalog A", 2008, movie_a_dir),
            _movie(2, "Fixture Catalog B", 2009, movie_b_dir),
        ]
    )

    service._ingest_movies_from_library_roots = lambda _affected_paths, **kw: {1}

    service.reconcile(affected_paths=None)

    projected_a = _projected_file(library_root, "Fixture Catalog A (2008)", "a.mkv")
    projected_b = _projected_file(library_root, "Fixture Catalog B (2009)", "b.mkv")

    assert projected_a.exists()
    assert projected_b.exists()


def test_reconcile_file_ingest_replaces_upgraded_movie(tmp_path: Path) -> None:
    """Radarr upgrade: new file in library root replaces old in managed root."""
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"

    managed_movie = managed_root / "Fixture Upgrade (2024)"
    managed_movie.mkdir(parents=True)
    (managed_movie / "old.720p.mkv").write_text("old-quality", encoding="utf-8")

    library_movie = library_root / "Fixture Upgrade (2024)"
    library_movie.mkdir(parents=True)
    (library_movie / "new.1080p.mkv").write_text("new-quality", encoding="utf-8")

    config = make_config(managed_root, library_root, sync_enabled=True)
    config.ingest.enabled = True
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        movies=[_movie(99, "Fixture Upgrade", 2024, library_movie)],
    )

    service.reconcile()

    assert (managed_movie / "new.1080p.mkv").exists()
    assert (managed_movie / "new.1080p.mkv").read_text(encoding="utf-8") == "new-quality"

    projected = _projected_file(library_root, "Fixture Upgrade (2024)", "new.1080p.mkv")
    assert projected.exists()
    assert projected.samefile(managed_movie / "new.1080p.mkv")


def test_reconcile_file_ingest_noop_when_inodes_match(tmp_path: Path) -> None:
    """No ingest when library root file is a hardlink to managed root file."""
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"

    managed_movie = managed_root / "Fixture Match (2020)"
    managed_movie.mkdir(parents=True)
    managed_file = managed_movie / "movie.mkv"
    managed_file.write_text("content", encoding="utf-8")

    library_movie = library_root / "Fixture Match (2020)"
    library_movie.mkdir(parents=True)
    os.link(str(managed_file), str(library_movie / "movie.mkv"))

    config = make_config(managed_root, library_root, sync_enabled=True)
    config.ingest.enabled = True
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        movies=[_movie(50, "Fixture Match", 2020, library_movie)],
    )

    service.reconcile()

    assert managed_file.exists()
    assert managed_file.read_text(encoding="utf-8") == "content"


def test_duplicate_movie_in_two_subfolders_only_radarr_path_projected(tmp_path: Path) -> None:
    """When the same movie exists in two nested subfolders, only the folder
    that Radarr's path points to is projected. The other folder is ignored."""
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"

    # Same movie in two different subfolders
    folder_a = managed_root / "Studio_A" / "Duplicate Movie (2023)"
    folder_b = managed_root / "Studio_B" / "Duplicate Movie (2023)"
    folder_a.mkdir(parents=True)
    folder_b.mkdir(parents=True)

    file_a = folder_a / "Duplicate.Movie.2023.1080p.mkv"
    file_b = folder_b / "Duplicate.Movie.2023.720p.mkv"
    file_a.write_text("version-a", encoding="utf-8")
    file_b.write_text("version-b", encoding="utf-8")

    # Radarr knows about this movie once, pointing to folder_a
    config = make_config(managed_root, library_root, sync_enabled=False)
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        movies=[_movie(99, "Duplicate Movie", 2023, folder_a)],
    )

    service.reconcile()

    # folder_a's file is projected (flattened to Title (Year)/)
    projected_a = _projected_file(
        library_root, "Duplicate Movie (2023)", "Duplicate.Movie.2023.1080p.mkv"
    )
    assert projected_a.exists()
    assert projected_a.samefile(file_a)

    # folder_b's file is NOT projected — Radarr doesn't know about it
    projected_b = _projected_file(
        library_root, "Duplicate Movie (2023)", "Duplicate.Movie.2023.720p.mkv"
    )
    assert not projected_b.exists()


def test_reconcile_normalizes_nested_radarr_path_via_temporary_hop(tmp_path: Path) -> None:
    managed_root = tmp_path / "managed" / "FSK06 Erwachsene"
    library_root = tmp_path / "library" / "FSK06 Erwachsene"

    managed_movie = managed_root / "Willi wird das Kind schon schaukeln (1972)"
    managed_movie.mkdir(parents=True)
    (managed_movie / "movie.mkv").write_text("x", encoding="utf-8")

    nested_library = (
        library_root
        / "Willi wird das Kind schon schaukeln (1972)"
        / "Willi wird das Kind schon schaukeln (1972)"
    )

    class AncestorConflictFakeRadarr(FakeRadarr):
        def update_movie_path(self, movie: dict, new_path: str) -> bool:
            expected = str(library_root / "Willi wird das Kind schon schaukeln (1972)")
            if movie.get("path") == str(nested_library) and new_path == expected:
                response = requests.Response()
                response.status_code = 400
                response._content = (
                    b'[{"errorCode":"MovieAncestorValidator",'
                    b'"errorMessage":"Path is an ancestor of an existing movie"}]'
                )
                raise requests.HTTPError(response=response)
            return super().update_movie_path(movie, new_path)

    config = make_config(managed_root, library_root, sync_enabled=False)
    service = LibrariArrService(config)
    service.radarr = AncestorConflictFakeRadarr(
        movies=[
            _movie(
                2087,
                "Willi wird das Kind schon schaukeln",
                1972,
                nested_library,
            )
        ]
    )

    service.reconcile()

    updated_paths = [path for movie_id, path in service.radarr.updated_paths if movie_id == 2087]
    assert len(updated_paths) >= 2
    assert updated_paths[-1] == str(library_root / "Willi wird das Kind schon schaukeln (1972)")
