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
from librariarr.projection import get_radarr_webhook_queue
from librariarr.service import LibrariArrService
from librariarr.sync.naming import safe_path_component


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


def _seed_movie_or_skip(
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
        existing = _find_movie_by_tmdb_or_none(session, base_url, payload["tmdbId"])
        if existing is not None:
            return existing
        pytest.skip(
            f"Radarr movie seeding failed ({add_movie_resp.status_code}): "
            f"{add_movie_resp.text[:200]}"
        )

    return add_movie_resp.json()


def _find_movie_by_tmdb_or_none(
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


def _canonical_name_from_seeded_movie(movie: dict) -> str:
    title = str(movie.get("title") or "Fixture Seeded Title").strip() or "Fixture Seeded Title"
    title = safe_path_component(title)
    year = movie.get("year")
    if isinstance(year, int):
        return f"{title} ({year})"
    return title


def _seed_slash_title_movie_or_skip(
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
        seeded_movie = _seed_movie_or_skip(
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


def _projection_config(
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


def _ensure_movie_path_under_managed_root(
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


@pytest.mark.e2e
def test_radarr_e2e_reconcile_sanitizes_slash_title_paths() -> None:
    case_root = _resolve_case_root(f"radarr_projection_slash_title_{uuid.uuid4().hex[:8]}")

    managed_root = case_root / "managed_movies"
    library_root = case_root / "library_movies"
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)

    radarr_url = os.getenv("LIBRARIARR_RADARR_E2E_URL", "http://radarr-test:7878").rstrip("/")
    api_key = _wait_for_api_key(Path("/radarr-config/config.xml"))
    session = _wait_for_radarr(radarr_url, api_key)

    seeded_movie = _seed_slash_title_movie_or_skip(session, radarr_url, managed_root)
    seeded_movie = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        seeded_movie,
        managed_root,
        "slash-title",
    )

    managed_folder = Path(str(seeded_movie["path"]))
    managed_folder.mkdir(parents=True, exist_ok=True)
    source_file = managed_folder / "Slash.Title.Projection.1080p.x265.mkv"
    source_file.write_text("stub", encoding="utf-8")

    service = LibrariArrService(
        _projection_config(
            managed_root=managed_root,
            library_root=library_root,
            radarr_url=radarr_url,
            api_key=api_key,
        )
    )
    service.reconcile()

    title = str(seeded_movie.get("title") or "")
    year = seeded_movie.get("year")
    expected_folder_name = (
        safe_path_component(f"{title} ({year})")
        if isinstance(year, int)
        else safe_path_component(title)
    )
    projected_file = library_root / expected_folder_name / source_file.name

    assert projected_file.exists()
    assert projected_file.samefile(source_file)
    assert "/" not in expected_folder_name


@pytest.mark.e2e
def test_radarr_e2e_reconcile_corrects_path_after_nfo_fix() -> None:
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
        title="Fixture Projection Relink",
        title_slug="fixture-projection-relink-2014",
        tmdb_id=266856,
        year=2014,
    )
    seeded_movie = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        seeded_movie,
        managed_root,
        "relink",
    )

    managed_folder = Path(str(seeded_movie["path"]))
    managed_folder.mkdir(parents=True, exist_ok=True)
    source_file = managed_folder / "Fixture.Projection.Relink.2014.1080p.x265.mkv"
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

    old_inode = projected_file.stat().st_ino
    source_file.unlink()
    source_file.write_text("v2", encoding="utf-8")

    service.reconcile()

    assert projected_file.exists()
    assert projected_file.samefile(source_file)
    assert projected_file.read_text(encoding="utf-8") == "v2"
    assert projected_file.stat().st_ino != old_inode


@pytest.mark.e2e
def test_radarr_e2e_reconcile_updates_existing_movie_path() -> None:
    case_root = _resolve_case_root(f"radarr_projection_no_path_mutation_{uuid.uuid4().hex[:8]}")

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
        title="Fixture Projection No Path Mutation",
        title_slug="fixture-projection-no-path-mutation-2018",
        tmdb_id=338970,
        year=2018,
    )
    seeded_movie = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        seeded_movie,
        managed_root,
        "no-path-mutation",
    )

    managed_folder = Path(str(seeded_movie["path"]))
    baseline_path = str(seeded_movie.get("path") or "")
    managed_folder.mkdir(parents=True, exist_ok=True)
    source_file = managed_folder / "Fixture.Projection.No.Path.Mutation.2018.1080p.x265.mkv"
    source_file.write_text("stub", encoding="utf-8")

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

    movie_id = int(seeded_movie["id"])
    movie_resp = session.get(f"{radarr_url}/api/v3/movie/{movie_id}", timeout=20)
    movie_resp.raise_for_status()
    assert str(movie_resp.json().get("path") or "") == baseline_path


@pytest.mark.e2e
def test_radarr_e2e_projection_allowlisted_extras() -> None:
    case_root = _resolve_case_root(f"radarr_projection_allowlisted_extras_{uuid.uuid4().hex[:8]}")

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
        title="Fixture Projection Allowlisted Extras",
        title_slug="fixture-projection-allowlisted-extras-2022",
        tmdb_id=634649,
        year=2022,
    )
    seeded_movie = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        seeded_movie,
        managed_root,
        "allowlisted-extras",
    )

    managed_folder = Path(str(seeded_movie["path"]))
    managed_folder.mkdir(parents=True, exist_ok=True)
    video_file = managed_folder / "Fixture.Projection.Allowlisted.Extras.2022.1080p.x265.mkv"
    nfo_file = managed_folder / "movie.nfo"
    poster_file = managed_folder / "poster.jpg"
    ignored_file = managed_folder / "notes.txt"
    video_file.write_text("video", encoding="utf-8")
    nfo_file.write_text("<movie></movie>", encoding="utf-8")
    poster_file.write_text("poster", encoding="utf-8")
    ignored_file.write_text("ignore", encoding="utf-8")

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
    projected_video = projected_folder / video_file.name
    projected_nfo = projected_folder / nfo_file.name
    projected_poster = projected_folder / poster_file.name
    projected_ignored = projected_folder / ignored_file.name

    assert projected_video.exists()
    assert projected_video.samefile(video_file)
    assert projected_nfo.exists()
    assert projected_nfo.samefile(nfo_file)
    assert projected_poster.exists()
    assert projected_poster.samefile(poster_file)
    assert not projected_ignored.exists()


@pytest.mark.e2e
def test_radarr_e2e_projection_scoped_webhook_reconcile() -> None:
    case_root = _resolve_case_root(f"radarr_projection_scoped_webhook_{uuid.uuid4().hex[:8]}")

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
        title="Fixture Projection Scoped Queue A",
        title_slug="fixture-projection-scoped-queue-a-2011",
        tmdb_id=11778,
        year=2011,
    )
    movie_b = _seed_movie_or_skip(
        session,
        radarr_url,
        managed_root,
        title="Fixture Projection Scoped Queue B",
        title_slug="fixture-projection-scoped-queue-b-2012",
        tmdb_id=82702,
        year=2012,
    )

    movie_a = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        movie_a,
        managed_root,
        "queue-a",
    )
    movie_b = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        movie_b,
        managed_root,
        "queue-b",
    )

    folder_a = Path(str(movie_a["path"]))
    folder_b = Path(str(movie_b["path"]))
    folder_a.mkdir(parents=True, exist_ok=True)
    folder_b.mkdir(parents=True, exist_ok=True)
    source_a = folder_a / "Fixture.Projection.Scoped.Queue.A.2011.1080p.x265.mkv"
    source_b = folder_b / "Fixture.Projection.Scoped.Queue.B.2012.1080p.x265.mkv"
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

    queue = get_radarr_webhook_queue()
    queue.consume_movie_ids()
    try:
        queue.enqueue(
            movie_id=int(movie_b["id"]),
            event_type="MovieFileDelete",
            normalized_path=str(folder_b),
        )
        service.reconcile()
    finally:
        queue.consume_movie_ids()

    projected_a = library_root / folder_a.relative_to(managed_root) / source_a.name
    projected_b = library_root / folder_b.relative_to(managed_root) / source_b.name

    assert not projected_a.exists()
    assert projected_b.exists()
    assert projected_b.samefile(source_b)


@pytest.mark.e2e
def test_radarr_e2e_projection_multi_mapping() -> None:
    case_root = _resolve_case_root(f"radarr_projection_multi_mapping_{uuid.uuid4().hex[:8]}")

    managed_a = case_root / "managed_a"
    managed_b = case_root / "managed_b"
    library_a = case_root / "library_a"
    library_b = case_root / "library_b"
    managed_a.mkdir(parents=True, exist_ok=True)
    managed_b.mkdir(parents=True, exist_ok=True)
    library_a.mkdir(parents=True, exist_ok=True)
    library_b.mkdir(parents=True, exist_ok=True)

    radarr_url = os.getenv("LIBRARIARR_RADARR_E2E_URL", "http://radarr-test:7878").rstrip("/")
    api_key = _wait_for_api_key(Path("/radarr-config/config.xml"))
    session = _wait_for_radarr(radarr_url, api_key)

    movie_a = _seed_movie_or_skip(
        session,
        radarr_url,
        managed_a,
        title="Fixture Projection Mapping A",
        title_slug="fixture-projection-mapping-a-2023",
        tmdb_id=635302,
        year=2023,
    )
    movie_b = _seed_movie_or_skip(
        session,
        radarr_url,
        managed_b,
        title="Fixture Projection Mapping B",
        title_slug="fixture-projection-mapping-b-2024",
        tmdb_id=616036,
        year=2024,
    )

    movie_a = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        movie_a,
        managed_a,
        "mapping-a",
    )
    movie_b = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        movie_b,
        managed_b,
        "mapping-b",
    )

    folder_a = Path(str(movie_a["path"]))
    folder_b = Path(str(movie_b["path"]))
    folder_a.mkdir(parents=True, exist_ok=True)
    folder_b.mkdir(parents=True, exist_ok=True)
    source_a = folder_a / "Fixture.Projection.Mapping.A.2023.1080p.x265.mkv"
    source_b = folder_b / "Fixture.Projection.Mapping.B.2024.1080p.x265.mkv"
    source_a.write_text("a", encoding="utf-8")
    source_b.write_text("b", encoding="utf-8")

    config = AppConfig(
        paths=PathsConfig(
            series_root_mappings=[],
            movie_root_mappings=[
                MovieRootMapping(managed_root=str(managed_a), library_root=str(library_a)),
                MovieRootMapping(managed_root=str(managed_b), library_root=str(library_b)),
            ],
        ),
        radarr=RadarrConfig(
            url=radarr_url,
            api_key=api_key,
            sync_enabled=True,
            projection=RadarrProjectionConfig(),
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )

    service = LibrariArrService(config)
    service.reconcile()

    folder_name_a = safe_path_component("Fixture Projection Mapping A (2023)")
    folder_name_b = safe_path_component("Fixture Projection Mapping B (2024)")
    projected_a = library_a / folder_name_a / source_a.name
    projected_b = library_b / folder_name_b / source_b.name

    assert projected_a.exists()
    assert projected_a.samefile(source_a)
    assert projected_b.exists()
    assert projected_b.samefile(source_b)
    assert not (library_b / folder_a.name / source_a.name).exists()
    assert not (library_a / folder_b.name / source_b.name).exists()


@pytest.mark.e2e
def test_radarr_e2e_ingest_folder_level_new_movie() -> None:
    """Folder-level ingest: movie only in library root, no managed folder yet."""
    case_root = _resolve_case_root(f"radarr_ingest_folder_{uuid.uuid4().hex[:8]}")

    managed_root = case_root / "managed_movies"
    library_root = case_root / "library_movies"
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)

    radarr_url = os.getenv("LIBRARIARR_RADARR_E2E_URL", "http://radarr-test:7878").rstrip("/")
    api_key = _wait_for_api_key(Path("/radarr-config/config.xml"))
    session = _wait_for_radarr(radarr_url, api_key)

    seeded = _seed_movie_or_skip(
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
    payload["path"] = str(lib_folder)
    update_resp = session.put(f"{radarr_url}/api/v3/movie/{movie_id}", json=payload, timeout=20)
    update_resp.raise_for_status()

    config = _projection_config(
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
    projected_video = library_root / lib_folder_name / video_file.name

    assert managed_video.exists(), "Video should be moved to managed root"
    assert projected_video.exists(), "Projection should hardlink it back"
    assert projected_video.samefile(managed_video), "Projected file should be a hardlink"


@pytest.mark.e2e
def test_radarr_e2e_ingest_file_level_upgrade() -> None:
    """File-level ingest: managed folder exists, library root has a new file (upgrade)."""
    case_root = _resolve_case_root(f"radarr_ingest_upgrade_{uuid.uuid4().hex[:8]}")

    managed_root = case_root / "managed_movies"
    library_root = case_root / "library_movies"
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)

    radarr_url = os.getenv("LIBRARIARR_RADARR_E2E_URL", "http://radarr-test:7878").rstrip("/")
    api_key = _wait_for_api_key(Path("/radarr-config/config.xml"))
    session = _wait_for_radarr(radarr_url, api_key)

    seeded = _seed_movie_or_skip(
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
    payload["path"] = str(lib_folder)
    update_resp = session.put(f"{radarr_url}/api/v3/movie/{movie_id}", json=payload, timeout=20)
    update_resp.raise_for_status()

    config = _projection_config(
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
    projected_new = lib_folder / new_video.name

    assert managed_new.exists(), "New file should be ingested into managed root"
    assert managed_new.read_text(encoding="utf-8") == "new-quality-1080p"
    assert projected_new.exists(), "Projection should hardlink new file back"
    assert projected_new.samefile(managed_new), "Projected file should be hardlink to managed"


@pytest.mark.e2e
def test_radarr_e2e_ingest_noop_when_hardlinks_match() -> None:
    """No ingest action when library root files are hardlinks to managed root."""
    case_root = _resolve_case_root(f"radarr_ingest_noop_{uuid.uuid4().hex[:8]}")

    managed_root = case_root / "managed_movies"
    library_root = case_root / "library_movies"
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)

    radarr_url = os.getenv("LIBRARIARR_RADARR_E2E_URL", "http://radarr-test:7878").rstrip("/")
    api_key = _wait_for_api_key(Path("/radarr-config/config.xml"))
    session = _wait_for_radarr(radarr_url, api_key)

    seeded = _seed_movie_or_skip(
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
    payload["path"] = str(lib_folder)
    update_resp = session.put(f"{radarr_url}/api/v3/movie/{movie_id}", json=payload, timeout=20)
    update_resp.raise_for_status()

    config = _projection_config(
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
    assert lib_video.exists()
    assert lib_video.samefile(managed_video)
