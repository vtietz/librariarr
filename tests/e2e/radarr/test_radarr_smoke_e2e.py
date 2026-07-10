"""Live Radarr smoke tests against a real Radarr instance.

Covers the first-contact (adopt) flow, projection, idempotency, and prune —
the paths that need a real Arr API to be meaningful. Full scenario coverage
lives in tests/e2e/filesystem (fake Arr, real filesystem).
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from librariarr.core.engine import SCOPE_FULL, ReconcileEngine
from librariarr.core.index import AdvisoryCache

from .radarr_e2e_helpers import (
    projection_config,
    resolve_case_root,
    seed_movie_or_skip,
    wait_for_api_key,
    wait_for_radarr,
)

pytestmark = pytest.mark.e2e

RADARR_URL = os.getenv("LIBRARIARR_RADARR_E2E_URL", "").rstrip("/")
RADARR_CONFIG_XML = Path(os.getenv("LIBRARIARR_RADARR_CONFIG_XML", "/radarr-config/config.xml"))


@pytest.fixture(scope="module")
def radarr_session():
    if not RADARR_URL:
        pytest.skip("LIBRARIARR_RADARR_E2E_URL is not set")
    api_key = wait_for_api_key(RADARR_CONFIG_XML)
    session = wait_for_radarr(RADARR_URL, api_key)
    return session, api_key


@pytest.fixture
def case(radarr_session, tmp_path):
    session, api_key = radarr_session
    case_root = resolve_case_root(f"smoke-{uuid.uuid4().hex[:8]}")
    managed_root = case_root / "movies"
    library_root = case_root / "radarr_library"
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)
    config = projection_config(
        managed_root=managed_root,
        library_root=library_root,
        radarr_url=RADARR_URL,
        api_key=api_key,
        sync_enabled=True,
    )
    engine = ReconcileEngine(config, cache=AdvisoryCache(tmp_path / "idcache.json"))
    return session, config, engine, managed_root, library_root


def _delete_movie(session, movie_id: int) -> None:
    session.delete(
        f"{RADARR_URL}/api/v3/movie/{movie_id}",
        params={"deleteFiles": "false", "addImportExclusion": "false"},
        timeout=20,
    )


def test_adopt_projection_idempotency_and_prune(case):
    session, config, engine, managed_root, library_root = case
    seeded = seed_movie_or_skip(session, RADARR_URL, library_root)
    movie_id = int(seeded["id"])
    try:
        # Point the movie at a canonical folder under the library root (fileless).
        canonical = library_root / f"{seeded['title']} ({seeded['year']})"
        payload = session.get(f"{RADARR_URL}/api/v3/movie/{movie_id}", timeout=20).json()
        payload["path"] = str(canonical)
        session.put(f"{RADARR_URL}/api/v3/movie/{movie_id}", json=payload, timeout=20)

        # First contact: a matching managed folder exists -> adopt + project.
        managed_folder = managed_root / f"{seeded['title']} ({seeded['year']})"
        managed_file = managed_folder / "feature.mkv"
        managed_folder.mkdir(parents=True)
        managed_file.write_text("fixture-video-content", encoding="utf-8")

        report = engine.run(scope=SCOPE_FULL)
        assert not report.errors, report.errors
        projected = canonical / "feature.mkv"
        assert projected.exists(), "managed file must be projected into the library folder"
        assert projected.stat().st_ino == managed_file.stat().st_ino

        # Idempotency: a second run must not produce filesystem actions.
        second = engine.run(scope=SCOPE_FULL)
        fs_actions = [a for a in second.actions if a.kind in {"link", "ingest_link", "trash"}]
        assert fs_actions == [], fs_actions

        # Prune: removing the movie from Radarr clears the projection, never the managed file.
        _delete_movie(session, movie_id)
        movie_id = 0
        engine.run(scope=SCOPE_FULL)
        assert managed_file.exists(), "managed data must survive Arr-side deletion"
        assert not projected.exists()
    finally:
        if movie_id:
            _delete_movie(session, movie_id)


def test_auto_add_unmatched_folder_and_projection(case):
    session, _, engine, managed_root, library_root = case

    profiles_resp = session.get(f"{RADARR_URL}/api/v3/qualityprofile", timeout=20)
    profiles_resp.raise_for_status()
    profiles = profiles_resp.json()
    if not profiles:
        pytest.skip("Radarr has no quality profiles available for auto-add")

    root_folders_resp = session.get(f"{RADARR_URL}/api/v3/rootfolder", timeout=20)
    root_folders_resp.raise_for_status()
    root_folders = root_folders_resp.json()
    library_root_str = str(library_root)
    has_library_root = any(
        str(item.get("path", "")).rstrip("/") == library_root_str.rstrip("/")
        for item in root_folders
    )
    if not has_library_root:
        create_root_resp = session.post(
            f"{RADARR_URL}/api/v3/rootfolder",
            json={"path": library_root_str},
            timeout=20,
        )
        if create_root_resp.status_code >= 400:
            pytest.skip(
                f"Radarr root folder setup failed ({create_root_resp.status_code}): "
                f"{create_root_resp.text[:200]}"
            )

    engine.config.radarr.auto_add_unmatched = True
    engine.config.radarr.auto_add_quality_profile_id = int(profiles[0]["id"])
    engine.config.radarr.auto_add_search_on_add = False
    engine.config.radarr.auto_add_monitored = False

    existing_movies_resp = session.get(f"{RADARR_URL}/api/v3/movie", timeout=20)
    existing_movies_resp.raise_for_status()
    existing_movies = existing_movies_resp.json()
    existing_tmdb_ids = {
        int(row.get("tmdbId") or 0)
        for row in existing_movies
        if isinstance(row, dict) and (row.get("tmdbId") is not None)
    }
    existing_ids = {
        int(row.get("id") or 0)
        for row in existing_movies
        if isinstance(row, dict) and (row.get("id") is not None)
    }

    chosen: dict | None = None
    for title, year in [
        ("Coherence", 2013),
        ("Primer", 2004),
        ("Gattaca", 1997),
        ("Moon", 2009),
    ]:
        lookup_resp = session.get(
            f"{RADARR_URL}/api/v3/movie/lookup",
            params={"term": f"{title} ({year})"},
            timeout=20,
        )
        if lookup_resp.status_code >= 400:
            continue
        rows = lookup_resp.json() if isinstance(lookup_resp.json(), list) else []
        exact = [
            row
            for row in rows
            if (row.get("title") or "").lower() == title.lower()
            and int(row.get("year") or 0) == year
            and int(row.get("tmdbId") or 0) not in existing_tmdb_ids
        ]
        if len(exact) == 1:
            chosen = exact[0]
            break

    if chosen is None:
        pytest.skip("No unique lookup candidate available for Radarr auto-add smoke test")

    target_folder = managed_root / f"{chosen['title']} ({chosen['year']})"
    managed_file = target_folder / "auto-add.mkv"
    managed_file.parent.mkdir(parents=True, exist_ok=True)
    managed_file.write_text("fixture-video-content", encoding="utf-8")

    added_id = 0
    try:
        report = engine.run(scope=SCOPE_FULL)
        assert not report.errors, report.errors

        refreshed_movies_resp = session.get(f"{RADARR_URL}/api/v3/movie", timeout=20)
        refreshed_movies_resp.raise_for_status()
        refreshed_movies = refreshed_movies_resp.json()
        added = [
            row
            for row in refreshed_movies
            if int(row.get("tmdbId") or 0) == int(chosen.get("tmdbId") or 0)
            and int(row.get("id") or 0) not in existing_ids
        ]
        assert added, "auto-add did not create a new Radarr movie entry"

        added_movie = added[0]
        added_id = int(added_movie["id"])
        projected = Path(added_movie["path"]) / "auto-add.mkv"
        assert projected.exists(), "managed file must be projected into the Radarr folder"
        assert projected.stat().st_ino == managed_file.stat().st_ino
    finally:
        if added_id:
            _delete_movie(session, added_id)
