import os
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
    QualityRule,
    RadarrConfig,
    RuntimeConfig,
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
                # Radarr may still be writing the file.
                pass
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for Radarr API key in {config_xml_path}")


def _wait_for_radarr(base_url: str, api_key: str, timeout_seconds: int = 180) -> requests.Session:
    session = requests.Session()
    session.headers.update({"X-Api-Key": api_key, "Content-Type": "application/json"})

    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        try:
            response = session.get(f"{base_url}/api/v3/movie", timeout=10)
            if response.status_code == 200:
                return session
            last_error = f"status={response.status_code} body={response.text[:200]}"
        except requests.RequestException as exc:
            last_error = str(exc)
        time.sleep(2)

    raise TimeoutError(f"Timed out waiting for Radarr API readiness: {last_error}")


def _seed_movie_or_skip(session: requests.Session, base_url: str, shadow_root: Path) -> dict:
    profiles_resp = session.get(f"{base_url}/api/v3/qualityprofile", timeout=20)
    profiles_resp.raise_for_status()
    profiles = profiles_resp.json()
    if not profiles:
        pytest.skip("Radarr has no quality profiles available for seeding")
    profile_id = int(profiles[0]["id"])

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
                f"Radarr root folder setup failed ({create_root_resp.status_code}): "
                f"{create_root_resp.text[:200]}"
            )

    payload = {
        "title": "Star Wars",
        "qualityProfileId": profile_id,
        "titleSlug": "star-wars-1977",
        "images": [],
        "tmdbId": 11,
        "year": 1977,
        "rootFolderPath": shadow_root_str,
        "path": f"{shadow_root_str}/old-star-wars-path",
        "monitored": True,
        "minimumAvailability": "released",
        "addOptions": {"searchForMovie": False},
    }

    add_movie_resp = session.post(f"{base_url}/api/v3/movie", json=payload, timeout=30)
    if add_movie_resp.status_code >= 400:
        pytest.skip(
            f"Radarr movie seeding failed ({add_movie_resp.status_code}): "
            f"{add_movie_resp.text[:200]}"
        )

    return add_movie_resp.json()


@pytest.mark.e2e
def test_radarr_e2e_reconcile_updates_existing_movie_path() -> None:
    persist_root = Path(os.getenv("LIBRARIARR_E2E_PERSIST_ROOT", "/e2e"))
    case_root = persist_root / f"radarr_sync_{uuid.uuid4().hex[:8]}"

    nested_root = case_root / "movies"
    shadow_root = case_root / "radarr_library"
    movie_folder = nested_root / "Star Wars (1977)"
    movie_folder.mkdir(parents=True, exist_ok=True)
    shadow_root.mkdir(parents=True, exist_ok=True)
    (movie_folder / "Star.Wars.1977.1080p.x265.mkv").write_text("stub", encoding="utf-8")

    radarr_url = os.getenv("LIBRARIARR_RADARR_E2E_URL", "http://radarr-test:7878").rstrip("/")
    api_key = _wait_for_api_key(Path("/radarr-config/config.xml"))
    session = _wait_for_radarr(radarr_url, api_key)

    seeded_movie = _seed_movie_or_skip(session, radarr_url, shadow_root)

    config = AppConfig(
        paths=PathsConfig(nested_roots=[str(nested_root)]),
        radarr=RadarrConfig(
            url=radarr_url,
            api_key=api_key,
            shadow_root=str(shadow_root),
            sync_enabled=True,
        ),
        quality_map=[QualityRule(match=["1080p", "x265"], target_id=7, name="Bluray-1080p")],
        cleanup=CleanupConfig(remove_orphaned_links=True, unmonitor_on_delete=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )

    service = LibrariArrService(config)
    service.reconcile()

    expected_link = shadow_root / "Star Wars (1977)"
    assert expected_link.is_symlink()

    movie_id = int(seeded_movie["id"])
    get_movie_resp = session.get(f"{radarr_url}/api/v3/movie/{movie_id}", timeout=20)
    get_movie_resp.raise_for_status()
    refreshed_movie = get_movie_resp.json()

    assert refreshed_movie["path"] == str(expected_link)
