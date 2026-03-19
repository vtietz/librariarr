import os
import threading
import time
import uuid
from pathlib import Path

import pytest

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    MovieRootMapping,
    PathsConfig,
    RadarrConfig,
    RuntimeConfig,
)
from librariarr.projection import get_radarr_webhook_queue
from librariarr.service import LibrariArrService
from tests.e2e.radarr.test_radarr_e2e import (
    _ensure_movie_path_under_managed_root,
    _resolve_case_root,
    _seed_movie_or_skip,
    _wait_for_api_key,
    _wait_for_radarr,
)


def _wait_for_condition(
    predicate,
    *,
    timeout_seconds: int = 20,
    step_seconds: float = 0.2,
    error_message: str,
) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(step_seconds)
    raise TimeoutError(error_message)


def _projection_config(
    *,
    managed_root: Path,
    library_root: Path,
    radarr_url: str,
    api_key: str,
) -> AppConfig:
    return AppConfig(
        paths=PathsConfig(
            series_root_mappings=[],
            movie_root_mappings=[
                MovieRootMapping(
                    managed_root=str(managed_root),
                    library_root=str(library_root),
                )
            ],
        ),
        radarr=RadarrConfig(
            url=radarr_url,
            api_key=api_key,
            sync_enabled=True,
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=0),
    )


@pytest.mark.e2e
def test_radarr_e2e_projection_relinks_when_managed_file_is_replaced() -> None:
    case_root = _resolve_case_root(f"radarr_projection_relink_replace_{uuid.uuid4().hex[:8]}")

    managed_root = case_root / "managed_movies"
    library_root = case_root / "library_movies"
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)

    radarr_url = os.getenv("LIBRARIARR_RADARR_E2E_URL", "http://radarr-test:7878").rstrip("/")
    api_key = _wait_for_api_key(Path("/radarr-config/config.xml"))
    session = _wait_for_radarr(radarr_url, api_key)

    seeded_movie = _seed_movie_or_skip(
        session,
        radarr_url,
        managed_root,
        title="Fixture Projection Replace Source",
        title_slug="fixture-projection-replace-source-2016",
        tmdb_id=293660,
        year=2016,
    )
    seeded_movie = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        seeded_movie,
        managed_root,
        "replace-source",
    )

    managed_folder = Path(str(seeded_movie["path"]))
    managed_folder.mkdir(parents=True, exist_ok=True)
    source_file = managed_folder / "Fixture.Projection.Replace.Source.2016.1080p.x265.mkv"
    source_file.write_text("v1", encoding="utf-8")

    service = LibrariArrService(
        _projection_config(
            managed_root=managed_root,
            library_root=library_root,
            radarr_url=radarr_url,
            api_key=api_key,
        )
    )
    service.reconcile()

    projected_file = library_root / managed_folder.relative_to(managed_root) / source_file.name
    assert projected_file.exists()
    assert projected_file.samefile(source_file)

    initial_inode = projected_file.stat().st_ino
    source_file.unlink()
    source_file.write_text("v2", encoding="utf-8")

    service.reconcile()

    assert projected_file.exists()
    assert projected_file.samefile(source_file)
    assert projected_file.read_text(encoding="utf-8") == "v2"
    assert projected_file.stat().st_ino != initial_inode


@pytest.mark.e2e
def test_radarr_e2e_projection_preserves_unknown_library_files() -> None:
    case_root = _resolve_case_root(f"radarr_projection_preserve_unknown_{uuid.uuid4().hex[:8]}")

    managed_root = case_root / "managed_movies"
    library_root = case_root / "library_movies"
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)

    radarr_url = os.getenv("LIBRARIARR_RADARR_E2E_URL", "http://radarr-test:7878").rstrip("/")
    api_key = _wait_for_api_key(Path("/radarr-config/config.xml"))
    session = _wait_for_radarr(radarr_url, api_key)

    seeded_movie = _seed_movie_or_skip(
        session,
        radarr_url,
        managed_root,
        title="Fixture Projection Preserve Unknown",
        title_slug="fixture-projection-preserve-unknown-2021",
        tmdb_id=634649,
        year=2021,
    )
    seeded_movie = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        seeded_movie,
        managed_root,
        "preserve-unknown",
    )

    managed_folder = Path(str(seeded_movie["path"]))
    managed_folder.mkdir(parents=True, exist_ok=True)
    source_file = managed_folder / "Fixture.Projection.Preserve.Unknown.2021.1080p.x265.mkv"
    source_file.write_text("managed", encoding="utf-8")

    service = LibrariArrService(
        _projection_config(
            managed_root=managed_root,
            library_root=library_root,
            radarr_url=radarr_url,
            api_key=api_key,
        )
    )
    service.reconcile()

    projected_folder = library_root / managed_folder.relative_to(managed_root)
    projected_file = projected_folder / source_file.name
    unknown_file = projected_folder / "notes.txt"
    unknown_file.write_text("keep me", encoding="utf-8")

    projected_file.unlink()
    service.reconcile()

    assert projected_file.exists()
    assert projected_file.samefile(source_file)
    assert unknown_file.exists()
    assert unknown_file.read_text(encoding="utf-8") == "keep me"


@pytest.mark.e2e
def test_radarr_e2e_runtime_reconcile_processes_webhook_scoped_projection() -> None:
    case_root = _resolve_case_root(f"radarr_projection_runtime_scoped_{uuid.uuid4().hex[:8]}")

    managed_root = case_root / "managed_movies"
    library_root = case_root / "library_movies"
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)

    radarr_url = os.getenv("LIBRARIARR_RADARR_E2E_URL", "http://radarr-test:7878").rstrip("/")
    api_key = _wait_for_api_key(Path("/radarr-config/config.xml"))
    session = _wait_for_radarr(radarr_url, api_key)

    movie_a = _seed_movie_or_skip(
        session,
        radarr_url,
        managed_root,
        title="Fixture Projection Runtime A",
        title_slug="fixture-projection-runtime-a-2011",
        tmdb_id=11778,
        year=2011,
    )
    movie_b = _seed_movie_or_skip(
        session,
        radarr_url,
        managed_root,
        title="Fixture Projection Runtime B",
        title_slug="fixture-projection-runtime-b-2012",
        tmdb_id=82702,
        year=2012,
    )
    movie_a = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        movie_a,
        managed_root,
        "runtime-a",
    )
    movie_b = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        movie_b,
        managed_root,
        "runtime-b",
    )

    folder_a = Path(str(movie_a["path"]))
    folder_b = Path(str(movie_b["path"]))
    folder_a.mkdir(parents=True, exist_ok=True)
    folder_b.mkdir(parents=True, exist_ok=True)
    source_a = folder_a / "Fixture.Projection.Runtime.A.2011.1080p.x265.mkv"
    source_b = folder_b / "Fixture.Projection.Runtime.B.2012.1080p.x265.mkv"
    source_a.write_text("a", encoding="utf-8")
    source_b.write_text("b", encoding="utf-8")

    service = LibrariArrService(
        _projection_config(
            managed_root=managed_root,
            library_root=library_root,
            radarr_url=radarr_url,
            api_key=api_key,
        )
    )

    projected_a = library_root / folder_a.relative_to(managed_root) / source_a.name
    projected_b = library_root / folder_b.relative_to(managed_root) / source_b.name

    queue = get_radarr_webhook_queue()
    queue.consume_movie_ids()
    queue.enqueue(
        movie_id=int(movie_b["id"]),
        event_type="Download",
        normalized_path=str(folder_b),
    )

    stop_event = threading.Event()
    runtime_thread = threading.Thread(target=service.run, kwargs={"stop_event": stop_event})
    runtime_thread.start()

    try:
        _wait_for_condition(
            lambda: projected_b.exists(),
            timeout_seconds=30,
            error_message="Timed out waiting for runtime-scoped projection for movie B",
        )
    finally:
        stop_event.set()
        runtime_thread.join(timeout=20)
        queue.consume_movie_ids()

    assert not runtime_thread.is_alive()
    assert not projected_a.exists()
    assert projected_b.exists()
    assert projected_b.samefile(source_b)
