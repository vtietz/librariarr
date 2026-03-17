import os
import uuid
from pathlib import Path

import pytest
import requests

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    PathsConfig,
    RadarrConfig,
    RootMapping,
    RuntimeConfig,
)
from librariarr.service import LibrariArrService
from librariarr.sync.naming import safe_path_component
from tests.e2e.radarr.test_radarr_e2e import (
    _canonical_name_from_seeded_movie,
    _resolve_case_root,
    _seed_movie_or_skip,
    _wait_for_api_key,
    _wait_for_radarr,
)


def _movie_path_by_id(session: requests.Session, base_url: str, movie_id: int) -> str:
    response = session.get(f"{base_url}/api/v3/movie/{movie_id}", timeout=20)
    response.raise_for_status()
    return str(response.json().get("path") or "")


@pytest.mark.e2e
def test_radarr_e2e_reconcile_matches_by_existing_link_name() -> None:
    case_root = _resolve_case_root(f"radarr_match_existing_link_{uuid.uuid4().hex[:8]}")

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
        title="Fixture Existing Link Strategy Movie",
        title_slug="fixture-existing-link-strategy-movie-2014",
        tmdb_id=266856,
        year=2014,
    )

    folder_name = f"Alias Folder {uuid.uuid4().hex[:6]}"
    movie_folder = nested_root / folder_name
    movie_folder.mkdir(parents=True, exist_ok=True)
    (movie_folder / "Fixture.Video.1080p.x265.mkv").write_text("stub", encoding="utf-8")

    # Force match via existing-link strategy: this link name matches the Radarr item,
    # while the folder name does not.
    existing_link = shadow_root / _canonical_name_from_seeded_movie(seeded_movie)
    existing_link.symlink_to(movie_folder, target_is_directory=True)

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
    assert _movie_path_by_id(session, radarr_url, movie_id) == str(expected_link)


@pytest.mark.e2e
def test_radarr_e2e_reconcile_matches_by_fuzzy_fallback() -> None:
    case_root = _resolve_case_root(f"radarr_match_fuzzy_{uuid.uuid4().hex[:8]}")

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
        title="Fixture Fuzzy Match Example Movie",
        title_slug="fixture-fuzzy-match-example-movie-2012",
        tmdb_id=68718,
        year=2012,
    )

    seeded_title = safe_path_component(
        str(seeded_movie.get("title") or "Fixture Fuzzy Match Example")
    )
    seeded_year = int(seeded_movie.get("year") or 2012)
    folder_name = f"{seeded_title} Extended ({seeded_year})"

    movie_folder = nested_root / folder_name
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
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )

    service = LibrariArrService(config)
    service.reconcile()

    expected_link = shadow_root / folder_name
    assert expected_link.is_symlink()

    movie_id = int(seeded_movie["id"])
    assert _movie_path_by_id(session, radarr_url, movie_id) == str(expected_link)


@pytest.mark.e2e
def test_radarr_e2e_strict_policy_blocks_exact_title_year_path_update() -> None:
    case_root = _resolve_case_root(f"radarr_match_policy_strict_{uuid.uuid4().hex[:8]}")

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
        title="Fixture Strict Policy Movie",
        title_slug="fixture-strict-policy-movie-2019",
        tmdb_id=539972,
        year=2019,
    )

    canonical_name = _canonical_name_from_seeded_movie(seeded_movie)
    movie_folder = nested_root / canonical_name
    movie_folder.mkdir(parents=True, exist_ok=True)
    (movie_folder / "Fixture.Video.1080p.x265.mkv").write_text("stub", encoding="utf-8")

    movie_id = int(seeded_movie["id"])
    baseline_path = _movie_path_by_id(session, radarr_url, movie_id)

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
            path_update_match_policy="external_ids_only",
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )

    service = LibrariArrService(config)
    service.reconcile()

    expected_link = shadow_root / canonical_name
    assert expected_link.is_symlink()
    assert _movie_path_by_id(session, radarr_url, movie_id) == baseline_path
