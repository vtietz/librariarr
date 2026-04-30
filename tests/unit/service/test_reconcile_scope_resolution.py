from pathlib import Path

from librariarr.projection import get_radarr_webhook_queue, get_sonarr_webhook_queue
from librariarr.service import LibrariArrService
from tests.service.helpers import make_config


def _service(tmp_path: Path) -> LibrariArrService:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"
    managed_root.mkdir()
    library_root.mkdir()
    return LibrariArrService(make_config(managed_root, library_root, sync_enabled=True))


def test_scope_resolution_full_mode_does_not_seed_from_ingest_only(tmp_path: Path) -> None:
    service = _service(tmp_path)

    scope = service._resolve_projection_scope(
        force_full_scope=False,
        incremental_mode=False,
        affected_paths=None,
        ingested_movie_ids={101},
        auto_added_movie_ids=set(),
        auto_added_series_ids=set(),
    )

    assert scope["scoped_movie_ids"] is None
    assert scope["movie_scope_kind"] == "full"


def test_scope_resolution_incremental_mode_seeds_from_ingest(tmp_path: Path) -> None:
    service = _service(tmp_path)

    scope = service._resolve_projection_scope(
        force_full_scope=False,
        incremental_mode=True,
        affected_paths=None,
        ingested_movie_ids={101},
        auto_added_movie_ids={202},
        auto_added_series_ids={303},
    )

    assert scope["scoped_movie_ids"] == {101, 202}
    assert scope["scoped_series_ids"] == {303}
    assert scope["movie_scope_kind"] == "scoped"
    assert scope["series_scope_kind"] == "scoped"


def test_scope_resolution_force_full_drains_queue_without_scoping(tmp_path: Path) -> None:
    service = _service(tmp_path)
    radarr_queue = get_radarr_webhook_queue()
    sonarr_queue = get_sonarr_webhook_queue()

    radarr_queue.consume_movie_ids()
    sonarr_queue.consume_series_ids()
    radarr_queue.enqueue(movie_id=11, event_type="UnitTest", normalized_path="/tmp/a")
    sonarr_queue.enqueue(series_id=22, event_type="UnitTest", normalized_path="/tmp/b")

    scope = service._resolve_projection_scope(
        force_full_scope=True,
        incremental_mode=True,
        affected_paths=None,
        ingested_movie_ids={101},
        auto_added_movie_ids={202},
        auto_added_series_ids={303},
    )

    assert scope["scoped_movie_ids"] is None
    assert scope["scoped_series_ids"] is None
    assert scope["queued_movie_ids"] == {11}
    assert scope["queued_series_ids"] == set()
