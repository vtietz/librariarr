import os
import shutil
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import requests

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    IngestConfig,
    PathsConfig,
    RadarrConfig,
    RootMapping,
    RuntimeConfig,
    SonarrConfig,
)
from librariarr.service import LibrariArrService


def _wait_for_api_key(config_xml_path: Path, timeout_seconds: int = 180) -> str:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if config_xml_path.exists():
            try:
                root = ET.fromstring(config_xml_path.read_text(encoding="utf-8"))
                key = root.findtext("ApiKey", default="").strip()
                if key:
                    return key
            except ET.ParseError:
                pass
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for Sonarr API key in {config_xml_path}")


def _wait_for_sonarr(base_url: str, api_key: str, timeout_seconds: int = 180) -> requests.Session:
    session = requests.Session()
    session.headers.update({"X-Api-Key": api_key, "Content-Type": "application/json"})

    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        try:
            response = session.get(f"{base_url}/api/v3/series", timeout=10)
            if response.status_code == 200:
                return session
            last_error = f"status={response.status_code} body={response.text[:200]}"
        except requests.RequestException as exc:
            last_error = str(exc)
        time.sleep(2)

    raise TimeoutError(f"Timed out waiting for Sonarr API readiness: {last_error}")


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


def _find_series_by_tvdb_or_none(
    session: requests.Session,
    base_url: str,
    tvdb_id: int,
) -> dict | None:
    series_resp = session.get(f"{base_url}/api/v3/series", timeout=20)
    series_resp.raise_for_status()
    for series in series_resp.json():
        if int(series.get("tvdbId") or 0) == tvdb_id:
            return series
    return None


def _seed_series_or_skip(session: requests.Session, base_url: str, shadow_root: Path) -> dict:
    shadow_root.mkdir(parents=True, exist_ok=True)

    profiles_resp = session.get(f"{base_url}/api/v3/qualityprofile", timeout=20)
    profiles_resp.raise_for_status()
    profiles = profiles_resp.json()
    if not profiles:
        pytest.skip("Sonarr has no quality profiles available for seeding")
    profile_id = int(profiles[0]["id"])

    language_profile_id: int | None = None
    try:
        language_profiles_resp = session.get(f"{base_url}/api/v3/languageprofile", timeout=20)
        if language_profiles_resp.status_code == 200:
            language_profiles = language_profiles_resp.json()
            if language_profiles:
                language_profile_id = int(language_profiles[0]["id"])
    except requests.RequestException:
        language_profile_id = None

    root_folders_resp = session.get(f"{base_url}/api/v3/rootfolder", timeout=20)
    root_folders_resp.raise_for_status()
    root_folders = root_folders_resp.json()
    shadow_root_str = str(shadow_root)
    has_shadow_root = any(
        str(item.get("path", "")).rstrip("/") == shadow_root_str.rstrip("/")
        for item in root_folders
    )
    if not has_shadow_root:
        create_root_resp = session.post(
            f"{base_url}/api/v3/rootfolder",
            json={"path": shadow_root_str},
            timeout=20,
        )
        if create_root_resp.status_code >= 400:
            pytest.skip(
                f"Sonarr root folder setup failed ({create_root_resp.status_code}): "
                f"{create_root_resp.text[:200]}"
            )

    payload: dict[str, object] = {
        "title": "Fixture Series",
        "qualityProfileId": profile_id,
        "titleSlug": "fixture-series-legacy",
        "images": [],
        "tvdbId": 80379,
        "year": 2005,
        "rootFolderPath": shadow_root_str,
        "path": f"{shadow_root_str}/old-fixture-series-path",
        "monitored": True,
        "seasonFolder": True,
        "addOptions": {
            "searchForMissingEpisodes": False,
            "searchForCutoffUnmetEpisodes": False,
        },
    }
    if language_profile_id is not None:
        payload["languageProfileId"] = language_profile_id

    add_series_resp = session.post(f"{base_url}/api/v3/series", json=payload, timeout=30)
    if add_series_resp.status_code >= 400:
        existing = _find_series_by_tvdb_or_none(session, base_url, int(payload["tvdbId"]))
        if existing is not None:
            return existing
        pytest.skip(
            f"Sonarr series seeding failed ({add_series_resp.status_code}): "
            f"{add_series_resp.text[:200]}"
        )

    return add_series_resp.json()


def _canonical_name_from_seeded_series(series: dict) -> str:
    title = str(series.get("title") or "Fixture Series").strip() or "Fixture Series"
    year = series.get("year")
    if isinstance(year, int):
        return f"{title} ({year})"
    return title


@pytest.mark.e2e
def test_sonarr_e2e_reconcile_updates_existing_series_path() -> None:
    persist_root = Path(os.getenv("LIBRARIARR_E2E_PERSIST_ROOT", "/e2e"))
    case_root = persist_root / f"sonarr_sync_{uuid.uuid4().hex[:8]}"

    nested_root = case_root / "series"
    shadow_root = case_root / "sonarr_library"
    nested_root.mkdir(parents=True, exist_ok=True)
    shadow_root.mkdir(parents=True, exist_ok=True)

    sonarr_url = os.getenv("LIBRARIARR_SONARR_E2E_URL", "http://sonarr-test:8989").rstrip("/")
    api_key = _wait_for_api_key(Path("/sonarr-config/config.xml"))
    session = _wait_for_sonarr(sonarr_url, api_key)

    seeded_series = _seed_series_or_skip(session, sonarr_url, shadow_root)
    canonical_name = _canonical_name_from_seeded_series(seeded_series)
    series_folder = nested_root / canonical_name
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

    expected_link = shadow_root / canonical_name
    assert expected_link.is_symlink()

    series_id = int(seeded_series["id"])
    get_series_resp = session.get(f"{sonarr_url}/api/v3/series/{series_id}", timeout=20)
    get_series_resp.raise_for_status()
    refreshed_series = get_series_resp.json()

    assert refreshed_series["path"] == str(expected_link)


@pytest.mark.e2e
def test_sonarr_e2e_reconcile_uses_root_level_nfo_tvdbid_with_nested_noise() -> None:
    persist_root = Path(os.getenv("LIBRARIARR_E2E_PERSIST_ROOT", "/e2e"))
    case_root = persist_root / f"sonarr_nfo_noise_{uuid.uuid4().hex[:8]}"

    nested_root = case_root / "series"
    shadow_root = case_root / "sonarr_library"
    nested_root.mkdir(parents=True, exist_ok=True)
    shadow_root.mkdir(parents=True, exist_ok=True)

    sonarr_url = os.getenv("LIBRARIARR_SONARR_E2E_URL", "http://sonarr-test:8989").rstrip("/")
    api_key = _wait_for_api_key(Path("/sonarr-config/config.xml"))
    session = _wait_for_sonarr(sonarr_url, api_key)

    seeded_series = _seed_series_or_skip(session, sonarr_url, shadow_root)
    tvdb_id = int(seeded_series["tvdbId"])

    folder_name = "Custom Series Folder"
    series_folder = nested_root / folder_name
    season_one = series_folder / "Season 01"
    season_one.mkdir(parents=True, exist_ok=True)
    (season_one / "Fixture.Series.S01E01.1080p.x265.mkv").write_text("stub", encoding="utf-8")
    (series_folder / "series.nfo").write_text(
        (
            "<tvshow>"
            "<actors><actor><tvdbid>9999999</tvdbid></actor></actors>"
            f"<tvdbid>{tvdb_id}</tvdbid>"
            "</tvshow>"
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
    get_series_resp = session.get(f"{sonarr_url}/api/v3/series/{series_id}", timeout=20)
    get_series_resp.raise_for_status()
    refreshed_series = get_series_resp.json()
    assert refreshed_series["path"] == str(expected_link)


@pytest.mark.e2e
def test_sonarr_e2e_incremental_cleanup_unmonitors_missing_series() -> None:
    persist_root = Path(os.getenv("LIBRARIARR_E2E_PERSIST_ROOT", "/e2e"))
    case_root = persist_root / f"sonarr_missing_action_{uuid.uuid4().hex[:8]}"

    nested_root = case_root / "series"
    shadow_root = case_root / "sonarr_library"
    nested_root.mkdir(parents=True, exist_ok=True)
    shadow_root.mkdir(parents=True, exist_ok=True)

    sonarr_url = os.getenv("LIBRARIARR_SONARR_E2E_URL", "http://sonarr-test:8989").rstrip("/")
    api_key = _wait_for_api_key(Path("/sonarr-config/config.xml"))
    session = _wait_for_sonarr(sonarr_url, api_key)

    seeded_series = _seed_series_or_skip(session, sonarr_url, shadow_root)
    canonical_name = _canonical_name_from_seeded_series(seeded_series)

    series_folder = nested_root / canonical_name
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
        cleanup=CleanupConfig(
            remove_orphaned_links=True,
            sonarr_action_on_missing="unmonitor",
            missing_grace_seconds=0,
        ),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )

    service = LibrariArrService(config)
    service.reconcile()

    expected_link = shadow_root / canonical_name
    assert expected_link.is_symlink()

    shutil.rmtree(series_folder)
    service.reconcile(affected_paths={series_folder})

    assert not expected_link.exists()
    series_id = int(seeded_series["id"])
    get_series_resp = session.get(f"{sonarr_url}/api/v3/series/{series_id}", timeout=20)
    get_series_resp.raise_for_status()
    refreshed_series = get_series_resp.json()
    assert refreshed_series["monitored"] is False


@pytest.mark.e2e
def test_sonarr_e2e_runtime_reconcile_handles_nested_shadow_file_create() -> None:
    persist_root = Path(os.getenv("LIBRARIARR_E2E_PERSIST_ROOT", "/e2e"))
    case_root = persist_root / f"sonarr_runtime_shadow_nested_{uuid.uuid4().hex[:8]}"

    nested_root = case_root / "series"
    shadow_root = case_root / "sonarr_library"
    nested_root.mkdir(parents=True, exist_ok=True)
    shadow_root.mkdir(parents=True, exist_ok=True)

    sonarr_url = os.getenv("LIBRARIARR_SONARR_E2E_URL", "http://sonarr-test:8989").rstrip("/")
    api_key = _wait_for_api_key(Path("/sonarr-config/config.xml"))
    session = _wait_for_sonarr(sonarr_url, api_key)

    seeded_series = _seed_series_or_skip(session, sonarr_url, shadow_root)
    canonical_name = _canonical_name_from_seeded_series(seeded_series)

    incoming_series_folder = shadow_root / canonical_name
    (incoming_series_folder / "Season 01").mkdir(parents=True, exist_ok=True)

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
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=0),
        ingest=IngestConfig(enabled=True, min_age_seconds=0),
    )

    service = LibrariArrService(config)
    stop_event = threading.Event()
    runtime_thread = threading.Thread(target=service.run, kwargs={"stop_event": stop_event})
    runtime_thread.start()

    try:
        (
            incoming_series_folder
            / "Season 01"
            / "Fixture.Series.Runtime.Nested.Event.S01E01.1080p.x265.mkv"
        ).write_text("stub", encoding="utf-8")

        destination = nested_root / canonical_name
        expected_link = shadow_root / canonical_name
        _wait_for_condition(
            lambda: expected_link.is_symlink() and destination.exists(),
            error_message="Timed out waiting for runtime-triggered Sonarr ingest/symlink update",
        )

        series_id = int(seeded_series["id"])

        def _sonarr_path_matches_expected() -> bool:
            response = session.get(f"{sonarr_url}/api/v3/series/{series_id}", timeout=20)
            response.raise_for_status()
            return response.json().get("path") == str(expected_link)

        _wait_for_condition(
            _sonarr_path_matches_expected,
            error_message="Timed out waiting for runtime-triggered Sonarr path update",
        )
    finally:
        stop_event.set()
        runtime_thread.join(timeout=20)

    assert not runtime_thread.is_alive()


@pytest.mark.e2e
def test_sonarr_e2e_ingest_moves_series_folder_and_updates_series_path() -> None:
    persist_root = Path(os.getenv("LIBRARIARR_E2E_PERSIST_ROOT", "/e2e"))
    case_root = persist_root / f"sonarr_ingest_{uuid.uuid4().hex[:8]}"

    nested_root = case_root / "series" / "age_12"
    shadow_root = case_root / "sonarr_library"
    mapped_shadow_root = shadow_root / "age_12"
    mapped_shadow_root.mkdir(parents=True, exist_ok=True)

    sonarr_url = os.getenv("LIBRARIARR_SONARR_E2E_URL", "http://sonarr-test:8989").rstrip("/")
    api_key = _wait_for_api_key(Path("/sonarr-config/config.xml"))
    session = _wait_for_sonarr(sonarr_url, api_key)

    seeded_series = _seed_series_or_skip(session, sonarr_url, mapped_shadow_root)
    canonical_name = _canonical_name_from_seeded_series(seeded_series)

    imported_series_folder = mapped_shadow_root / canonical_name
    season_one = imported_series_folder / "Season 01"
    season_one.mkdir(parents=True, exist_ok=True)
    (season_one / "Fixture.Series.S01E01.1080p.x265.mkv").write_text("stub", encoding="utf-8")

    config = AppConfig(
        paths=PathsConfig(
            root_mappings=[
                RootMapping(
                    nested_root=str(nested_root),
                    shadow_root=str(mapped_shadow_root),
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
        ingest=IngestConfig(enabled=True, min_age_seconds=0),
    )

    service = LibrariArrService(config)
    service.reconcile()

    expected_destination = nested_root / canonical_name
    expected_link = mapped_shadow_root / canonical_name
    assert expected_destination.exists()
    assert expected_link.is_symlink()
    assert expected_link.resolve(strict=False) == expected_destination

    series_id = int(seeded_series["id"])
    get_series_resp = session.get(f"{sonarr_url}/api/v3/series/{series_id}", timeout=20)
    get_series_resp.raise_for_status()
    refreshed_series = get_series_resp.json()

    assert refreshed_series["path"] == str(expected_link)


@pytest.mark.e2e
def test_sonarr_e2e_ingest_collision_skip_keeps_source_and_path() -> None:
    persist_root = Path(os.getenv("LIBRARIARR_E2E_PERSIST_ROOT", "/e2e"))
    case_root = persist_root / f"sonarr_ingest_skip_{uuid.uuid4().hex[:8]}"

    nested_root = case_root / "series" / "age_12"
    shadow_root = case_root / "sonarr_library"
    mapped_shadow_root = shadow_root / "age_12"

    sonarr_url = os.getenv("LIBRARIARR_SONARR_E2E_URL", "http://sonarr-test:8989").rstrip("/")
    api_key = _wait_for_api_key(Path("/sonarr-config/config.xml"))
    session = _wait_for_sonarr(sonarr_url, api_key)

    seeded_series = _seed_series_or_skip(session, sonarr_url, mapped_shadow_root)
    canonical_name = _canonical_name_from_seeded_series(seeded_series)
    series_id = int(seeded_series["id"])
    baseline_path = str(seeded_series.get("path") or "")

    existing_destination = nested_root / canonical_name
    existing_destination.mkdir(parents=True, exist_ok=True)
    (existing_destination / "README.txt").write_text("placeholder", encoding="utf-8")

    incoming_series_folder = mapped_shadow_root / canonical_name
    season_one = incoming_series_folder / "Season 01"
    season_one.mkdir(parents=True, exist_ok=True)
    (season_one / "Fixture.Series.S01E01.1080p.x265.mkv").write_text("stub", encoding="utf-8")

    config = AppConfig(
        paths=PathsConfig(
            root_mappings=[
                RootMapping(
                    nested_root=str(nested_root),
                    shadow_root=str(mapped_shadow_root),
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
        ingest=IngestConfig(enabled=True, min_age_seconds=0, collision_policy="skip"),
    )

    service = LibrariArrService(config)
    service.reconcile()

    assert incoming_series_folder.exists()
    assert incoming_series_folder.is_dir()
    assert not incoming_series_folder.is_symlink()

    get_series_resp = session.get(f"{sonarr_url}/api/v3/series/{series_id}", timeout=20)
    get_series_resp.raise_for_status()
    refreshed_series = get_series_resp.json()
    assert refreshed_series["path"] == baseline_path


@pytest.mark.e2e
def test_sonarr_e2e_ingest_collision_qualify_moves_with_suffix_and_updates_path() -> None:
    persist_root = Path(os.getenv("LIBRARIARR_E2E_PERSIST_ROOT", "/e2e"))
    case_root = persist_root / f"sonarr_ingest_qualify_{uuid.uuid4().hex[:8]}"

    nested_root = case_root / "series" / "age_12"
    shadow_root = case_root / "sonarr_library"
    mapped_shadow_root = shadow_root / "age_12"

    sonarr_url = os.getenv("LIBRARIARR_SONARR_E2E_URL", "http://sonarr-test:8989").rstrip("/")
    api_key = _wait_for_api_key(Path("/sonarr-config/config.xml"))
    session = _wait_for_sonarr(sonarr_url, api_key)

    seeded_series = _seed_series_or_skip(session, sonarr_url, mapped_shadow_root)
    canonical_name = _canonical_name_from_seeded_series(seeded_series)
    series_id = int(seeded_series["id"])

    existing_destination = nested_root / canonical_name
    existing_destination.mkdir(parents=True, exist_ok=True)
    (existing_destination / "README.txt").write_text("placeholder", encoding="utf-8")

    incoming_series_folder = mapped_shadow_root / canonical_name
    season_one = incoming_series_folder / "Season 01"
    season_one.mkdir(parents=True, exist_ok=True)
    (season_one / "Fixture.Series.S01E01.1080p.x265.mkv").write_text("stub", encoding="utf-8")

    config = AppConfig(
        paths=PathsConfig(
            root_mappings=[
                RootMapping(
                    nested_root=str(nested_root),
                    shadow_root=str(mapped_shadow_root),
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
        ingest=IngestConfig(enabled=True, min_age_seconds=0, collision_policy="qualify"),
    )

    service = LibrariArrService(config)
    service.reconcile()

    qualified_destination = nested_root / f"{canonical_name} [ingest-2]"
    expected_link = mapped_shadow_root / canonical_name
    assert qualified_destination.exists()
    assert expected_link.is_symlink()
    assert expected_link.resolve(strict=False) == qualified_destination

    get_series_resp = session.get(f"{sonarr_url}/api/v3/series/{series_id}", timeout=20)
    get_series_resp.raise_for_status()
    refreshed_series = get_series_resp.json()
    assert refreshed_series["path"] == str(expected_link)
