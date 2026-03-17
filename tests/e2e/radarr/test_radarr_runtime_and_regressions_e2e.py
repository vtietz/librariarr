import os
import shutil
import threading
import time
import uuid
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
from tests.e2e.radarr.test_radarr_e2e import (
    _canonical_name_from_seeded_movie,
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


@pytest.mark.e2e
def test_radarr_e2e_reconcile_uses_root_level_nfo_tmdbid_with_nested_noise() -> None:
    case_root = _resolve_case_root(f"radarr_nfo_noise_{uuid.uuid4().hex[:8]}")

    nested_root = case_root / "movies"
    shadow_root = case_root / "radarr_library"
    nested_root.mkdir(parents=True, exist_ok=True)
    shadow_root.mkdir(parents=True, exist_ok=True)

    radarr_url = os.getenv("LIBRARIARR_RADARR_E2E_URL", "http://radarr-test:7878").rstrip("/")
    api_key = _wait_for_api_key(Path("/radarr-config/config.xml"))
    session = _wait_for_radarr(radarr_url, api_key)

    seeded_movie = _seed_movie_or_skip(
        session,
        radarr_url,
        shadow_root,
        title="Fixture NFO Noise Movie",
        title_slug="fixture-nfo-noise-movie-2014",
        tmdb_id=266856,
        year=2014,
    )

    folder_name = "Completely Custom Folder"
    movie_folder = nested_root / folder_name
    movie_folder.mkdir(parents=True, exist_ok=True)
    (movie_folder / "Fixture.Video.mkv").write_text("stub", encoding="utf-8")
    (movie_folder / "movie.nfo").write_text(
        (
            "<movie>"
            "<credits><person><tmdbid>99999999</tmdbid></person></credits>"
            f"<tmdbid>{int(seeded_movie['tmdbId'])}</tmdbid>"
            "</movie>"
        ),
        encoding="utf-8",
    )

    config = AppConfig(
        paths=PathsConfig(
            root_mappings=[
                RootMapping(
                    nested_root=str(nested_root),
                    shadow_root=str(shadow_root),
                )
            ]
        ),
        radarr=RadarrConfig(
            url=radarr_url,
            api_key=api_key,
            sync_enabled=True,
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )

    service = LibrariArrService(config)
    service.reconcile()

    expected_link = shadow_root / folder_name
    assert expected_link.is_symlink()

    movie_id = int(seeded_movie["id"])
    get_movie_resp = session.get(f"{radarr_url}/api/v3/movie/{movie_id}", timeout=20)
    get_movie_resp.raise_for_status()
    refreshed_movie = get_movie_resp.json()
    assert refreshed_movie["path"] == str(expected_link)


@pytest.mark.e2e
def test_radarr_e2e_incremental_cleanup_unmonitors_missing_movie() -> None:
    case_root = _resolve_case_root(f"radarr_missing_action_{uuid.uuid4().hex[:8]}")

    nested_root = case_root / "movies"
    shadow_root = case_root / "radarr_library"
    nested_root.mkdir(parents=True, exist_ok=True)
    shadow_root.mkdir(parents=True, exist_ok=True)

    radarr_url = os.getenv("LIBRARIARR_RADARR_E2E_URL", "http://radarr-test:7878").rstrip("/")
    api_key = _wait_for_api_key(Path("/radarr-config/config.xml"))
    session = _wait_for_radarr(radarr_url, api_key)

    seeded_movie = _seed_movie_or_skip(
        session,
        radarr_url,
        shadow_root,
        title="Fixture Missing Action Movie",
        title_slug="fixture-missing-action-movie-2012",
        tmdb_id=68718,
        year=2012,
    )
    canonical_name = _canonical_name_from_seeded_movie(seeded_movie)
    movie_folder = nested_root / canonical_name
    movie_folder.mkdir(parents=True, exist_ok=True)
    (movie_folder / "Fixture.Video.1080p.x265.mkv").write_text("stub", encoding="utf-8")

    config = AppConfig(
        paths=PathsConfig(
            root_mappings=[
                RootMapping(
                    nested_root=str(nested_root),
                    shadow_root=str(shadow_root),
                )
            ]
        ),
        radarr=RadarrConfig(
            url=radarr_url,
            api_key=api_key,
            sync_enabled=True,
        ),
        cleanup=CleanupConfig(
            remove_orphaned_links=True,
            radarr_action_on_missing="unmonitor",
            missing_grace_seconds=0,
        ),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )

    service = LibrariArrService(config)
    service.reconcile()

    expected_link = shadow_root / canonical_name
    assert expected_link.is_symlink()

    shutil.rmtree(movie_folder)
    service.reconcile(affected_paths={movie_folder})

    assert not expected_link.exists()
    movie_id = int(seeded_movie["id"])
    get_movie_resp = session.get(f"{radarr_url}/api/v3/movie/{movie_id}", timeout=20)
    get_movie_resp.raise_for_status()
    refreshed_movie = get_movie_resp.json()
    assert refreshed_movie["monitored"] is False


@pytest.mark.e2e
def test_radarr_e2e_runtime_reconcile_handles_nested_shadow_file_create() -> None:
    case_root = _resolve_case_root(f"radarr_runtime_shadow_nested_{uuid.uuid4().hex[:8]}")

    nested_root = case_root / "movies"
    shadow_root = case_root / "radarr_library"
    nested_root.mkdir(parents=True, exist_ok=True)
    shadow_root.mkdir(parents=True, exist_ok=True)

    radarr_url = os.getenv("LIBRARIARR_RADARR_E2E_URL", "http://radarr-test:7878").rstrip("/")
    api_key = _wait_for_api_key(Path("/radarr-config/config.xml"))
    session = _wait_for_radarr(radarr_url, api_key)

    seeded_movie = _seed_movie_or_skip(
        session,
        radarr_url,
        shadow_root,
        title="Fixture Runtime Nested Event Movie",
        title_slug="fixture-runtime-nested-event-movie-2019",
        tmdb_id=539972,
        year=2019,
    )
    canonical_name = _canonical_name_from_seeded_movie(seeded_movie)

    incoming_folder = shadow_root / canonical_name
    incoming_folder.mkdir(parents=True, exist_ok=True)

    config = AppConfig(
        paths=PathsConfig(
            root_mappings=[
                RootMapping(
                    nested_root=str(nested_root),
                    shadow_root=str(shadow_root),
                )
            ]
        ),
        radarr=RadarrConfig(
            url=radarr_url,
            api_key=api_key,
            sync_enabled=True,
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=0),
        ingest=IngestConfig(enabled=True, min_age_seconds=0),
    )

    service = LibrariArrService(config)
    stop_event = threading.Event()
    runtime_thread = threading.Thread(target=service.run, kwargs={"stop_event": stop_event})
    runtime_thread.start()

    try:
        (incoming_folder / "Fixture.Runtime.Nested.Event.2019.1080p.x265.mkv").write_text(
            "stub",
            encoding="utf-8",
        )

        destination = nested_root / canonical_name
        expected_link = shadow_root / canonical_name
        _wait_for_condition(
            lambda: expected_link.is_symlink() and destination.exists(),
            error_message="Timed out waiting for runtime-triggered ingest/symlink update",
        )

        movie_id = int(seeded_movie["id"])

        def _radarr_path_matches_expected() -> bool:
            response = session.get(f"{radarr_url}/api/v3/movie/{movie_id}", timeout=20)
            response.raise_for_status()
            return response.json().get("path") == str(expected_link)

        _wait_for_condition(
            _radarr_path_matches_expected,
            error_message="Timed out waiting for runtime-triggered Radarr path update",
        )
    finally:
        stop_event.set()
        runtime_thread.join(timeout=20)

    assert not runtime_thread.is_alive()
