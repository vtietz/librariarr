from __future__ import annotations

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
    MovieRootMapping,
    PathsConfig,
    RadarrConfig,
    RadarrProjectionConfig,
    RuntimeConfig,
)
from librariarr.sync.naming import safe_path_component


def resolve_case_root(case_name: str) -> Path:
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


def wait_for_api_key(config_xml_path: Path, timeout_seconds: int = 180) -> str:
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
    raise TimeoutError(f"Timed out waiting for Radarr API key in {config_xml_path}")


def wait_for_radarr(base_url: str, api_key: str, timeout_seconds: int = 180) -> requests.Session:
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


def seed_movie_or_skip(
    session: requests.Session,
    base_url: str,
    root_folder: Path,
    *,
    title: str = "Fixture Legacy",
    title_slug: str = "fixture-legacy-1977",
    tmdb_id: int = 11,
    year: int = 1977,
) -> dict:
    root_folder.mkdir(parents=True, exist_ok=True)

    profiles_resp = session.get(f"{base_url}/api/v3/qualityprofile", timeout=20)
    profiles_resp.raise_for_status()
    profiles = profiles_resp.json()
    if not profiles:
        pytest.skip("Radarr has no quality profiles available for seeding")
    profile_id = int(profiles[0]["id"])

    root_folders_resp = session.get(f"{base_url}/api/v3/rootfolder", timeout=20)
    root_folders_resp.raise_for_status()
    root_folders = root_folders_resp.json()
    root_folder_str = str(root_folder)
    has_root = any(
        str(item.get("path", "")).rstrip("/") == root_folder_str.rstrip("/")
        for item in root_folders
    )
    if not has_root:
        create_root_resp = session.post(
            f"{base_url}/api/v3/rootfolder",
            json={"path": root_folder_str},
            timeout=20,
        )
        if create_root_resp.status_code >= 400:
            pytest.skip(
                f"Radarr root folder setup failed ({create_root_resp.status_code}): "
                f"{create_root_resp.text[:200]}"
            )

    payload = {
        "title": title,
        "qualityProfileId": profile_id,
        "titleSlug": title_slug,
        "images": [],
        "tmdbId": tmdb_id,
        "year": year,
        "rootFolderPath": root_folder_str,
        "path": f"{root_folder_str}/old-{title_slug}",
        "monitored": True,
        "minimumAvailability": "released",
        "addOptions": {"searchForMovie": False},
    }

    add_movie_resp = session.post(f"{base_url}/api/v3/movie", json=payload, timeout=30)
    if add_movie_resp.status_code >= 400:
        existing = find_movie_by_tmdb_or_none(session, base_url, payload["tmdbId"])
        if existing is not None:
            return existing
        pytest.skip(
            f"Radarr movie seeding failed ({add_movie_resp.status_code}): "
            f"{add_movie_resp.text[:200]}"
        )

    return add_movie_resp.json()


def find_movie_by_tmdb_or_none(
    session: requests.Session,
    base_url: str,
    tmdb_id: int,
) -> dict | None:
    movies_resp = session.get(f"{base_url}/api/v3/movie", timeout=20)
    movies_resp.raise_for_status()
    for movie in movies_resp.json():
        if int(movie.get("tmdbId") or 0) == tmdb_id:
            return movie
    return None


def canonical_name_from_seeded_movie(movie: dict) -> str:
    title = str(movie.get("title") or "Fixture Seeded Title").strip() or "Fixture Seeded Title"
    title = safe_path_component(title)
    year = movie.get("year")
    if isinstance(year, int):
        return f"{title} ({year})"
    return title


def seed_slash_title_movie_or_skip(
    session: requests.Session,
    base_url: str,
    root_folder: Path,
) -> dict:
    candidates = [
        {
            "title": "Face/Off",
            "title_slug": "face-off-1997",
            "tmdb_id": 754,
            "year": 1997,
        },
        {
            "title": "Fahrenheit 9/11",
            "title_slug": "fahrenheit-9-11-2004",
            "tmdb_id": 177,
            "year": 2004,
        },
    ]

    for candidate in candidates:
        seeded_movie = seed_movie_or_skip(
            session,
            base_url,
            root_folder,
            title=candidate["title"],
            title_slug=candidate["title_slug"],
            tmdb_id=candidate["tmdb_id"],
            year=candidate["year"],
        )
        if "/" in str(seeded_movie.get("title") or ""):
            return seeded_movie

    pytest.skip(
        "Radarr did not provide slash titles for known slash-title TMDB candidates; "
        "cannot validate slash sanitization behavior"
    )


def projection_config(
    *,
    managed_root: Path,
    library_root: Path,
    radarr_url: str,
    api_key: str,
    sync_enabled: bool = False,
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
            sync_enabled=sync_enabled,
            projection=RadarrProjectionConfig(),
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )


def ensure_movie_path_under_managed_root(
    session: requests.Session,
    base_url: str,
    movie: dict,
    managed_root: Path,
    folder_suffix: str,
) -> dict:
    movie_id = int(movie["id"])
    target_path = managed_root / f"{folder_suffix}-{uuid.uuid4().hex[:6]}"

    get_resp = session.get(f"{base_url}/api/v3/movie/{movie_id}", timeout=20)
    get_resp.raise_for_status()
    payload = get_resp.json()
    payload["path"] = str(target_path)

    update_resp = session.put(f"{base_url}/api/v3/movie/{movie_id}", json=payload, timeout=20)
    if update_resp.status_code >= 400:
        pytest.skip(
            f"Unable to set movie path under managed root ({update_resp.status_code}): "
            f"{update_resp.text[:200]}"
        )

    refreshed_resp = session.get(f"{base_url}/api/v3/movie/{movie_id}", timeout=20)
    refreshed_resp.raise_for_status()
    return refreshed_resp.json()
