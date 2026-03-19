import os
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
    PathsConfig,
    RadarrConfig,
    RootMapping,
    RuntimeConfig,
    SonarrConfig,
)
from librariarr.projection import get_sonarr_webhook_queue
from librariarr.service import LibrariArrService


def _resolve_case_root(case_name: str) -> Path:
    persist_root = Path(os.getenv("LIBRARIARR_E2E_PERSIST_ROOT", "/e2e"))
    case_root = persist_root / case_name
    try:
        case_root.mkdir(parents=True, exist_ok=True)
        return case_root
    except OSError:
        fallback_root = Path("/tmp") / "librariarr-e2e"
        fallback_root.mkdir(parents=True, exist_ok=True)
        fallback_case_root = fallback_root / case_name
        fallback_case_root.mkdir(parents=True, exist_ok=True)
        return fallback_case_root


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


def _seed_series_or_skip(session: requests.Session, base_url: str, managed_root: Path) -> dict:
    managed_root.mkdir(parents=True, exist_ok=True)

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
    managed_root_str = str(managed_root)
    has_managed_root = any(
        str(item.get("path", "")).rstrip("/") == managed_root_str.rstrip("/")
        for item in root_folders
    )
    if not has_managed_root:
        create_root_resp = session.post(
            f"{base_url}/api/v3/rootfolder",
            json={"path": managed_root_str},
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
        "titleSlug": "fixture-series-projection",
        "images": [],
        "tvdbId": 80379,
        "year": 2005,
        "rootFolderPath": managed_root_str,
        "path": f"{managed_root_str}/old-fixture-series-path",
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


def _update_sonarr_series_path(
    session: requests.Session,
    base_url: str,
    *,
    series_id: int,
    new_path: Path,
) -> None:
    get_series_resp = session.get(f"{base_url}/api/v3/series/{series_id}", timeout=20)
    get_series_resp.raise_for_status()
    payload = get_series_resp.json()
    payload["path"] = str(new_path)
    payload["rootFolderPath"] = str(new_path.parent)
    put_resp = session.put(f"{base_url}/api/v3/series/{series_id}", json=payload, timeout=20)
    put_resp.raise_for_status()


def _build_service_config(
    *,
    managed_root: Path,
    library_root: Path,
    sonarr_url: str,
    api_key: str,
    debounce_seconds: int = 1,
) -> AppConfig:
    return AppConfig(
        paths=PathsConfig(
            series_root_mappings=[
                RootMapping(
                    nested_root=str(managed_root),
                    shadow_root=str(library_root),
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
        runtime=RuntimeConfig(
            debounce_seconds=debounce_seconds,
            maintenance_interval_minutes=60,
        ),
    )


@pytest.mark.e2e
def test_sonarr_e2e_projection_projects_series_files() -> None:
    case_root = _resolve_case_root(f"sonarr_projection_{uuid.uuid4().hex[:8]}")
    managed_root = case_root / "series"
    library_root = case_root / "sonarr_library"
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)

    sonarr_url = os.getenv("LIBRARIARR_SONARR_E2E_URL", "http://sonarr-test:8989").rstrip("/")
    api_key = _wait_for_api_key(Path("/sonarr-config/config.xml"))
    session = _wait_for_sonarr(sonarr_url, api_key)

    seeded_series = _seed_series_or_skip(session, sonarr_url, managed_root)
    series_id = int(seeded_series["id"])
    canonical_name = _canonical_name_from_seeded_series(seeded_series)
    managed_series_folder = managed_root / canonical_name
    season_one = managed_series_folder / "Season 01"
    season_one.mkdir(parents=True, exist_ok=True)
    source_file = season_one / "Fixture.Series.S01E01.1080p.x265.mkv"
    source_file.write_text("stub", encoding="utf-8")
    _update_sonarr_series_path(
        session,
        sonarr_url,
        series_id=series_id,
        new_path=managed_series_folder,
    )

    service = LibrariArrService(
        _build_service_config(
            managed_root=managed_root,
            library_root=library_root,
            sonarr_url=sonarr_url,
            api_key=api_key,
        )
    )
    service.reconcile()

    projected_file = library_root / canonical_name / "Season 01" / source_file.name
    assert projected_file.exists()
    assert projected_file.is_file()
    assert projected_file.stat().st_ino == source_file.stat().st_ino


@pytest.mark.e2e
def test_sonarr_e2e_projection_scopes_to_webhook_series_ids() -> None:
    case_root = _resolve_case_root(f"sonarr_projection_scope_{uuid.uuid4().hex[:8]}")
    managed_root = case_root / "series"
    library_root = case_root / "sonarr_library"
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)

    sonarr_url = os.getenv("LIBRARIARR_SONARR_E2E_URL", "http://sonarr-test:8989").rstrip("/")
    api_key = _wait_for_api_key(Path("/sonarr-config/config.xml"))
    session = _wait_for_sonarr(sonarr_url, api_key)

    seeded_series = _seed_series_or_skip(session, sonarr_url, managed_root)
    series_id = int(seeded_series["id"])
    canonical_name = _canonical_name_from_seeded_series(seeded_series)
    managed_series_folder = managed_root / canonical_name
    season_one = managed_series_folder / "Season 01"
    season_one.mkdir(parents=True, exist_ok=True)

    scoped_file = season_one / "Fixture.Series.Scoped.S01E01.1080p.x265.mkv"
    ignored_file = season_one / "Fixture.Series.Ignored.S01E01.1080p.x265.mkv"
    scoped_file.write_text("scope", encoding="utf-8")
    ignored_file.write_text("ignore", encoding="utf-8")

    _update_sonarr_series_path(
        session,
        sonarr_url,
        series_id=series_id,
        new_path=managed_series_folder,
    )

    queue = get_sonarr_webhook_queue()
    queue.consume_series_ids()
    queue.enqueue(
        series_id=series_id,
        event_type="EpisodeFile",
        normalized_path=str(scoped_file),
    )

    service = LibrariArrService(
        _build_service_config(
            managed_root=managed_root,
            library_root=library_root,
            sonarr_url=sonarr_url,
            api_key=api_key,
        )
    )
    service.reconcile()

    projected_folder = library_root / canonical_name / "Season 01"
    assert (projected_folder / scoped_file.name).exists()
    assert (projected_folder / ignored_file.name).exists()


@pytest.mark.e2e
def test_sonarr_e2e_projection_uses_sonarr_title_year_folder_name() -> None:
    case_root = _resolve_case_root(f"sonarr_projection_name_{uuid.uuid4().hex[:8]}")
    managed_root = case_root / "series"
    library_root = case_root / "sonarr_library"
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)

    sonarr_url = os.getenv("LIBRARIARR_SONARR_E2E_URL", "http://sonarr-test:8989").rstrip("/")
    api_key = _wait_for_api_key(Path("/sonarr-config/config.xml"))
    session = _wait_for_sonarr(sonarr_url, api_key)

    seeded_series = _seed_series_or_skip(session, sonarr_url, managed_root)
    series_id = int(seeded_series["id"])
    alias_folder = managed_root / f"Alias-{uuid.uuid4().hex[:6]}"
    season_one = alias_folder / "Season 01"
    season_one.mkdir(parents=True, exist_ok=True)
    source_file = season_one / "Fixture.Series.S01E01.1080p.x265.mkv"
    source_file.write_text("stub", encoding="utf-8")
    _update_sonarr_series_path(
        session,
        sonarr_url,
        series_id=series_id,
        new_path=alias_folder,
    )

    config = _build_service_config(
        managed_root=managed_root,
        library_root=library_root,
        sonarr_url=sonarr_url,
        api_key=api_key,
    )
    config.sonarr.projection.series_folder_name_source = "sonarr"

    service = LibrariArrService(config)
    service.reconcile()

    canonical_name = _canonical_name_from_seeded_series(seeded_series)
    projected_file = library_root / canonical_name / "Season 01" / source_file.name
    assert projected_file.exists()


@pytest.mark.e2e
def test_sonarr_e2e_runtime_projection_reacts_to_managed_file_create() -> None:
    case_root = _resolve_case_root(f"sonarr_projection_runtime_{uuid.uuid4().hex[:8]}")
    managed_root = case_root / "series"
    library_root = case_root / "sonarr_library"
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)

    sonarr_url = os.getenv("LIBRARIARR_SONARR_E2E_URL", "http://sonarr-test:8989").rstrip("/")
    api_key = _wait_for_api_key(Path("/sonarr-config/config.xml"))
    session = _wait_for_sonarr(sonarr_url, api_key)

    seeded_series = _seed_series_or_skip(session, sonarr_url, managed_root)
    series_id = int(seeded_series["id"])
    canonical_name = _canonical_name_from_seeded_series(seeded_series)
    managed_series_folder = managed_root / canonical_name
    season_one = managed_series_folder / "Season 01"
    season_one.mkdir(parents=True, exist_ok=True)
    _update_sonarr_series_path(
        session,
        sonarr_url,
        series_id=series_id,
        new_path=managed_series_folder,
    )

    service = LibrariArrService(
        _build_service_config(
            managed_root=managed_root,
            library_root=library_root,
            sonarr_url=sonarr_url,
            api_key=api_key,
            debounce_seconds=1,
        )
    )
    stop_event = threading.Event()
    runtime_thread = threading.Thread(target=service.run, kwargs={"stop_event": stop_event})
    runtime_thread.start()

    try:
        source_file = season_one / "Fixture.Series.Runtime.S01E01.1080p.x265.mkv"
        source_file.write_text("runtime", encoding="utf-8")

        projected_file = library_root / canonical_name / "Season 01" / source_file.name
        _wait_for_condition(
            lambda: projected_file.exists(),
            error_message="Timed out waiting for runtime-triggered Sonarr projection",
        )
    finally:
        stop_event.set()
        runtime_thread.join(timeout=20)

    assert not runtime_thread.is_alive()
