"""Live Sonarr smoke test: auto-add + projection + prune.

Depends on Sonarr's metadata lookup (SkyHook); skips when lookup is
unavailable. Full scenario coverage lives in tests/e2e/filesystem.
"""

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
    PathsConfig,
    RootMapping,
    RuntimeConfig,
    SonarrConfig,
    SonarrProjectionConfig,
)
from librariarr.config.models import RadarrConfig
from librariarr.core.engine import SCOPE_FULL, ReconcileEngine
from librariarr.core.index import AdvisoryCache

pytestmark = pytest.mark.e2e

SONARR_URL = os.getenv("LIBRARIARR_SONARR_E2E_URL", "").rstrip("/")
SONARR_CONFIG_XML = Path(os.getenv("LIBRARIARR_SONARR_CONFIG_XML", "/sonarr-config/config.xml"))


def _wait_for_api_key(config_xml: Path, timeout_seconds: int = 180) -> str:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if config_xml.exists():
            try:
                key = (
                    ET.fromstring(config_xml.read_text(encoding="utf-8"))
                    .findtext("ApiKey", default="")
                    .strip()
                )
                if key:
                    return key
            except ET.ParseError:
                pass
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for Sonarr API key in {config_xml}")


@pytest.fixture(scope="module")
def sonarr_session():
    if not SONARR_URL:
        pytest.skip("LIBRARIARR_SONARR_E2E_URL is not set")
    api_key = _wait_for_api_key(SONARR_CONFIG_XML)
    session = requests.Session()
    session.headers.update({"X-Api-Key": api_key, "Content-Type": "application/json"})
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            if session.get(f"{SONARR_URL}/api/v3/series", timeout=10).status_code == 200:
                return session, api_key
        except requests.RequestException:
            pass
        time.sleep(2)
    pytest.skip("Sonarr API did not become ready")


def _case_root() -> Path:
    persist = Path(os.getenv("LIBRARIARR_E2E_PERSIST_ROOT", "/e2e"))
    case = persist / f"smoke-sonarr-{uuid.uuid4().hex[:8]}"
    try:
        case.mkdir(parents=True, exist_ok=True)
    except OSError:
        case = Path("/tmp/librariarr-e2e") / case.name
        case.mkdir(parents=True, exist_ok=True)
    return case


def test_series_auto_add_projection_and_prune(sonarr_session, tmp_path):
    session, api_key = sonarr_session
    case_root = _case_root()
    managed_root = case_root / "series"
    library_root = case_root / "sonarr_library"
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)

    profiles = session.get(f"{SONARR_URL}/api/v3/qualityprofile", timeout=20).json()
    if not profiles:
        pytest.skip("Sonarr has no quality profiles")
    session.post(f"{SONARR_URL}/api/v3/rootfolder", json={"path": str(library_root)}, timeout=20)

    config = AppConfig(
        paths=PathsConfig(
            series_root_mappings=[
                RootMapping(managed_root=str(managed_root), library_root=str(library_root))
            ],
        ),
        radarr=RadarrConfig(url="", api_key="", enabled=False),
        sonarr=SonarrConfig(
            enabled=True,
            url=SONARR_URL,
            api_key=api_key,
            auto_add_unmatched=True,
            auto_add_quality_profile_id=int(profiles[0]["id"]),
            projection=SonarrProjectionConfig(),
        ),
        runtime=RuntimeConfig(debounce_seconds=1),
    )
    engine = ReconcileEngine(config, cache=AdvisoryCache(tmp_path / "idcache.json"))

    if engine.sonarr is None:
        pytest.skip("Sonarr client not constructed")
    try:
        lookup = engine.sonarr.lookup_series("Breaking Bad")
    except Exception as exc:  # noqa: BLE001 - metadata service may be unavailable
        pytest.skip(f"Sonarr lookup unavailable: {exc}")
    if not any((r.get("title") or "").lower() == "breaking bad" for r in lookup):
        pytest.skip("Sonarr lookup did not return the fixture series")

    managed_folder = managed_root / "Breaking Bad (2008)"
    managed_ep = managed_folder / "Season 01" / "Breaking.Bad.S01E01.mkv"
    managed_ep.parent.mkdir(parents=True)
    managed_ep.write_text("fixture-episode", encoding="utf-8")

    series_id = 0
    try:
        report = engine.run(scope=SCOPE_FULL)
        assert not report.errors, report.errors
        added = [s for s in engine.sonarr.get_series() if "breaking bad" in s["title"].lower()]
        assert added, f"series was not auto-added; unmatched={report.to_dict()['unmatched']}"
        series_id = int(added[0]["id"])
        projected = Path(added[0]["path"]) / "Season 01" / "Breaking.Bad.S01E01.mkv"
        assert projected.exists()
        assert projected.stat().st_ino == managed_ep.stat().st_ino

        # Disable auto-add for the prune phase: with it on, discovery would
        # (by design) re-add the series from the still-present managed folder.
        config.sonarr.auto_add_unmatched = False
        delete_resp = session.delete(
            f"{SONARR_URL}/api/v3/series/{series_id}",
            params={"deleteFiles": "false"},
            timeout=20,
        )
        delete_resp.raise_for_status()
        deadline = time.time() + 30
        while time.time() < deadline:
            remaining = {int(s["id"]) for s in engine.sonarr.get_series()}
            if series_id not in remaining:
                break
            time.sleep(1)
        else:
            pytest.fail("Sonarr did not remove the series within 30s")
        series_id = 0

        second = engine.run(scope=SCOPE_FULL)
        assert not second.errors, second.errors
        assert managed_ep.exists(), "managed data must survive Arr-side deletion"
        assert not projected.exists(), second.to_dict()
    finally:
        leftovers = [
            int(s["id"])
            for s in session.get(f"{SONARR_URL}/api/v3/series", timeout=20).json()
            if "breaking bad" in (s.get("title") or "").lower()
        ]
        for leftover_id in leftovers:
            session.delete(
                f"{SONARR_URL}/api/v3/series/{leftover_id}",
                params={"deleteFiles": "false"},
                timeout=20,
            )
