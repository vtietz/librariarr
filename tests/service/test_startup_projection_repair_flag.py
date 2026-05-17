from __future__ import annotations

from pathlib import Path

from librariarr.projection.webhook_queue import get_radarr_webhook_queue
from librariarr.service import LibrariArrService
from librariarr.service import reconcile_lifecycle as reconcile_lifecycle_module

from .helpers import FakeRadarr
from .test_reconcile_core import _movie, make_config


def _base_projection_result() -> dict[str, object]:
    return {
        "scoped_movie_count": 1,
        "planned_movies": 0,
        "skipped_movies": 0,
        "projected_files": 0,
        "unchanged_files": 0,
        "skipped_files": 0,
        "matched_movie_ids": set(),
        "per_root": [],
    }


def test_startup_scoped_projection_enables_managed_folder_repair(
    tmp_path: Path,
    monkeypatch,
) -> None:
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

    captured_repair_flags: list[bool] = []

    def _capture_projection(scoped_movie_ids: set[int] | None, **kwargs) -> dict[str, object]:
        assert scoped_movie_ids == {2}
        captured_repair_flags.append(bool(kwargs.get("repair_managed_folders")))
        return _base_projection_result()

    service.movie_projection.reconcile = _capture_projection

    queue = get_radarr_webhook_queue()
    queue.consume_movie_ids()
    queue.enqueue(movie_id=2, event_type="Test", normalized_path=str(movie_b_dir))
    monkeypatch.setattr(
        reconcile_lifecycle_module,
        "current_reconcile_source",
        lambda _tracker: "startup",
    )

    service.reconcile(affected_paths={movie_b_dir})

    assert captured_repair_flags == [True]
    queue.consume_movie_ids()


def test_non_startup_scoped_projection_disables_managed_folder_repair(
    tmp_path: Path,
    monkeypatch,
) -> None:
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

    captured_repair_flags: list[bool] = []

    def _capture_projection(scoped_movie_ids: set[int] | None, **kwargs) -> dict[str, object]:
        assert scoped_movie_ids == {2}
        captured_repair_flags.append(bool(kwargs.get("repair_managed_folders")))
        return _base_projection_result()

    service.movie_projection.reconcile = _capture_projection

    queue = get_radarr_webhook_queue()
    queue.consume_movie_ids()
    queue.enqueue(movie_id=2, event_type="Test", normalized_path=str(movie_b_dir))
    monkeypatch.setattr(
        reconcile_lifecycle_module,
        "current_reconcile_source",
        lambda _tracker: "filesystem",
    )

    service.reconcile(affected_paths={movie_b_dir})

    assert captured_repair_flags == [False]
    queue.consume_movie_ids()
