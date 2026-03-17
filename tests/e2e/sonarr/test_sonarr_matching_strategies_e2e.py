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
    SonarrConfig,
)
from librariarr.service import LibrariArrService
from tests.e2e.sonarr.test_sonarr_e2e import (
    _canonical_name_from_seeded_series,
    _resolve_case_root,
    _seed_series_or_skip,
    _wait_for_api_key,
    _wait_for_sonarr,
)


def _series_path_by_id(session: requests.Session, base_url: str, series_id: int) -> str:
    response = session.get(f"{base_url}/api/v3/series/{series_id}", timeout=20)
    response.raise_for_status()
    return str(response.json().get("path") or "")


@pytest.mark.e2e
def test_sonarr_e2e_reconcile_matches_by_existing_link_name() -> None:
    case_root = _resolve_case_root(f"sonarr_match_existing_link_{uuid.uuid4().hex[:8]}")

    nested_root = case_root / "series"
    shadow_root = case_root / "sonarr_library"
    nested_root.mkdir(parents=True, exist_ok=True)
    shadow_root.mkdir(parents=True, exist_ok=True)

    sonarr_url = os.getenv("LIBRARIARR_SONARR_E2E_URL", "http://sonarr-test:8989").rstrip("/")
    api_key = _wait_for_api_key(Path("/sonarr-config/config.xml"))
    session = _wait_for_sonarr(sonarr_url, api_key)

    seeded_series = _seed_series_or_skip(session, sonarr_url, shadow_root)

    folder_name = f"Alias Series Folder {uuid.uuid4().hex[:6]}"
    series_folder = nested_root / folder_name
    season_one = series_folder / "Season 01"
    season_one.mkdir(parents=True, exist_ok=True)
    (season_one / "Fixture.Series.S01E01.1080p.x265.mkv").write_text("stub", encoding="utf-8")

    # Force match via existing-link strategy: link name matches Sonarr series,
    # while the folder name does not.
    existing_link = shadow_root / _canonical_name_from_seeded_series(seeded_series)
    existing_link.symlink_to(series_folder, target_is_directory=True)

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
            url="http://radarr:7878",
            api_key="test",
            enabled=False,
            sync_enabled=False,
        ),
        sonarr=SonarrConfig(
            enabled=True,
            url=sonarr_url,
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

    series_id = int(seeded_series["id"])
    assert _series_path_by_id(session, sonarr_url, series_id) == str(expected_link)


@pytest.mark.e2e
def test_sonarr_e2e_reconcile_matches_by_fuzzy_fallback() -> None:
    case_root = _resolve_case_root(f"sonarr_match_fuzzy_{uuid.uuid4().hex[:8]}")

    nested_root = case_root / "series"
    shadow_root = case_root / "sonarr_library"
    nested_root.mkdir(parents=True, exist_ok=True)
    shadow_root.mkdir(parents=True, exist_ok=True)

    sonarr_url = os.getenv("LIBRARIARR_SONARR_E2E_URL", "http://sonarr-test:8989").rstrip("/")
    api_key = _wait_for_api_key(Path("/sonarr-config/config.xml"))
    session = _wait_for_sonarr(sonarr_url, api_key)

    seeded_series = _seed_series_or_skip(session, sonarr_url, shadow_root)

    seeded_title = str(seeded_series.get("title") or "Fixture Series").strip() or "Fixture Series"
    seeded_year = int(seeded_series.get("year") or 2005)
    folder_name = f"{seeded_title} Extended ({seeded_year})"

    series_folder = nested_root / folder_name
    season_one = series_folder / "Season 01"
    season_one.mkdir(parents=True, exist_ok=True)
    (season_one / "Fixture.Series.S01E01.1080p.x265.mkv").write_text("stub", encoding="utf-8")

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
            url="http://radarr:7878",
            api_key="test",
            enabled=False,
            sync_enabled=False,
        ),
        sonarr=SonarrConfig(
            enabled=True,
            url=sonarr_url,
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

    series_id = int(seeded_series["id"])
    assert _series_path_by_id(session, sonarr_url, series_id) == str(expected_link)
