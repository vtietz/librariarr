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
