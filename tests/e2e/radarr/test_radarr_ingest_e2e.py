import os
import uuid
from pathlib import Path

import pytest

from librariarr.service import LibrariArrService
from librariarr.sync.naming import safe_path_component
from tests.e2e.radarr.radarr_e2e_helpers import (
    projection_config,
    resolve_case_root,
    seed_movie_or_skip,
    wait_for_api_key,
    wait_for_radarr,
)


def _expected_flat_folder(movie: dict) -> str:
    """Derive the flat ``Title (Year)`` folder name the planner would produce."""
    title = str(movie.get("title") or "").strip()
    year = movie.get("year")
    if title and isinstance(year, int):
        return safe_path_component(f"{title} ({year})")
    if title:
        return safe_path_component(title)
    return safe_path_component(f"movie-{movie.get('id')}")


@pytest.mark.e2e
def test_radarr_e2e_ingest_folder_level_new_movie() -> None:
    """Folder-level ingest: movie only in library root, no managed folder yet."""
    case_root = resolve_case_root(f"radarr_ingest_folder_{uuid.uuid4().hex[:8]}")

    managed_root = case_root / "managed_movies"
    library_root = case_root / "library_movies"
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)

    radarr_url = os.getenv("LIBRARIARR_RADARR_E2E_URL", "http://radarr-test:7878").rstrip("/")
    api_key = wait_for_api_key(Path("/radarr-config/config.xml"))
    session = wait_for_radarr(radarr_url, api_key)

    seeded = seed_movie_or_skip(
        session,
        radarr_url,
        library_root,
        title="Fixture Ingest Folder",
        title_slug="fixture-ingest-folder-2015",
        tmdb_id=286217,
        year=2015,
    )

    # Point Radarr movie directly at a library root subfolder
    movie_id = int(seeded["id"])
    lib_folder_name = f"ingest-folder-{uuid.uuid4().hex[:6]}"
    lib_folder = library_root / lib_folder_name
    lib_folder.mkdir(parents=True, exist_ok=True)
    video_file = lib_folder / "Fixture.Ingest.Folder.2015.1080p.mkv"
    video_file.write_text("new-movie", encoding="utf-8")

    get_resp = session.get(f"{radarr_url}/api/v3/movie/{movie_id}", timeout=20)
    get_resp.raise_for_status()
    payload = get_resp.json()
    expected_flat = _expected_flat_folder(payload)
    payload["path"] = str(lib_folder)
    update_resp = session.put(f"{radarr_url}/api/v3/movie/{movie_id}", json=payload, timeout=20)
    update_resp.raise_for_status()

    config = projection_config(
        managed_root=managed_root,
        library_root=library_root,
        radarr_url=radarr_url,
        api_key=api_key,
        sync_enabled=True,
    )
    config.ingest.enabled = True
    service = LibrariArrService(config)
    service.reconcile()

    managed_folder = managed_root / lib_folder_name
    managed_video = managed_folder / video_file.name
    projected_video = library_root / expected_flat / video_file.name

    assert managed_video.exists(), "Video should be moved to managed root"
    assert projected_video.exists(), "Projection should hardlink it back"
    assert projected_video.samefile(managed_video), "Projected file should be a hardlink"


@pytest.mark.e2e
def test_radarr_e2e_ingest_file_level_upgrade() -> None:
    """File-level ingest: managed folder exists, library root has a new file (upgrade)."""
    case_root = resolve_case_root(f"radarr_ingest_upgrade_{uuid.uuid4().hex[:8]}")

    managed_root = case_root / "managed_movies"
    library_root = case_root / "library_movies"
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)

    radarr_url = os.getenv("LIBRARIARR_RADARR_E2E_URL", "http://radarr-test:7878").rstrip("/")
    api_key = wait_for_api_key(Path("/radarr-config/config.xml"))
    session = wait_for_radarr(radarr_url, api_key)

    seeded = seed_movie_or_skip(
        session,
        radarr_url,
        library_root,
        title="Fixture Ingest Upgrade",
        title_slug="fixture-ingest-upgrade-2018",
        tmdb_id=347201,
        year=2018,
    )

    movie_id = int(seeded["id"])
    folder_name = f"ingest-upgrade-{uuid.uuid4().hex[:6]}"

    # Create managed folder with OLD file
    managed_folder = managed_root / folder_name
    managed_folder.mkdir(parents=True, exist_ok=True)
    old_video = managed_folder / "Fixture.Ingest.720p.mkv"
    old_video.write_text("old-quality-720p", encoding="utf-8")

    # Create library folder with NEW file (simulating Radarr upgrade)
    lib_folder = library_root / folder_name
    lib_folder.mkdir(parents=True, exist_ok=True)
    new_video = lib_folder / "Fixture.Ingest.1080p.mkv"
    new_video.write_text("new-quality-1080p", encoding="utf-8")

    # Point Radarr at the library root path
    get_resp = session.get(f"{radarr_url}/api/v3/movie/{movie_id}", timeout=20)
    get_resp.raise_for_status()
    payload = get_resp.json()
    expected_flat = _expected_flat_folder(payload)
    payload["path"] = str(lib_folder)
    update_resp = session.put(f"{radarr_url}/api/v3/movie/{movie_id}", json=payload, timeout=20)
    update_resp.raise_for_status()

    config = projection_config(
        managed_root=managed_root,
        library_root=library_root,
        radarr_url=radarr_url,
        api_key=api_key,
        sync_enabled=True,
    )
    config.ingest.enabled = True
    service = LibrariArrService(config)
    service.reconcile()

    managed_new = managed_folder / new_video.name
    projected_new = library_root / expected_flat / new_video.name

    assert managed_new.exists(), "New file should be ingested into managed root"
    assert managed_new.read_text(encoding="utf-8") == "new-quality-1080p"
    assert projected_new.exists(), "Projection should hardlink new file back"
    assert projected_new.samefile(managed_new), "Projected file should be hardlink to managed"


@pytest.mark.e2e
def test_radarr_e2e_ingest_noop_when_hardlinks_match() -> None:
    """No ingest action when library root files are hardlinks to managed root."""
    case_root = resolve_case_root(f"radarr_ingest_noop_{uuid.uuid4().hex[:8]}")

    managed_root = case_root / "managed_movies"
    library_root = case_root / "library_movies"
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)

    radarr_url = os.getenv("LIBRARIARR_RADARR_E2E_URL", "http://radarr-test:7878").rstrip("/")
    api_key = wait_for_api_key(Path("/radarr-config/config.xml"))
    session = wait_for_radarr(radarr_url, api_key)

    seeded = seed_movie_or_skip(
        session,
        radarr_url,
        managed_root,
        title="Fixture Ingest Noop",
        title_slug="fixture-ingest-noop-2020",
        tmdb_id=539681,
        year=2020,
    )

    movie_id = int(seeded["id"])
    folder_name = f"ingest-noop-{uuid.uuid4().hex[:6]}"

    # Create managed folder with video
    managed_folder = managed_root / folder_name
    managed_folder.mkdir(parents=True, exist_ok=True)
    managed_video = managed_folder / "Fixture.Ingest.Noop.2020.mkv"
    managed_video.write_text("same-content", encoding="utf-8")
    managed_inode = managed_video.stat().st_ino

    # Create hardlink in library root (simulates normal projection state)
    lib_folder = library_root / folder_name
    lib_folder.mkdir(parents=True, exist_ok=True)
    lib_video = lib_folder / managed_video.name
    os.link(str(managed_video), str(lib_video))

    # Point Radarr at library root path
    get_resp = session.get(f"{radarr_url}/api/v3/movie/{movie_id}", timeout=20)
    get_resp.raise_for_status()
    payload = get_resp.json()
    expected_flat = _expected_flat_folder(payload)
    payload["path"] = str(lib_folder)
    update_resp = session.put(f"{radarr_url}/api/v3/movie/{movie_id}", json=payload, timeout=20)
    update_resp.raise_for_status()

    config = projection_config(
        managed_root=managed_root,
        library_root=library_root,
        radarr_url=radarr_url,
        api_key=api_key,
        sync_enabled=True,
    )
    config.ingest.enabled = True
    service = LibrariArrService(config)
    service.reconcile()

    # Managed file should be untouched (same inode)
    assert managed_video.exists()
    assert managed_video.stat().st_ino == managed_inode
    # Projection should be at flat Title (Year) path
    flat_lib_video = library_root / expected_flat / managed_video.name
    assert flat_lib_video.exists()
    assert flat_lib_video.samefile(managed_video)
