import os
import uuid
from pathlib import Path

import pytest

from librariarr.service import LibrariArrService
from tests.e2e.sonarr.test_sonarr_e2e import (
    _build_service_config,
    _canonical_name_from_seeded_series,
    _resolve_case_root,
    _seed_series_or_skip,
    _update_sonarr_series_path,
    _wait_for_api_key,
    _wait_for_sonarr,
)


@pytest.mark.e2e
def test_sonarr_e2e_projection_skips_series_outside_managed_mappings() -> None:
    case_root = _resolve_case_root(f"sonarr_projection_unmapped_{uuid.uuid4().hex[:8]}")
    managed_root = case_root / "series"
    unmapped_root = case_root / "unmapped"
    library_root = case_root / "sonarr_library"
    managed_root.mkdir(parents=True, exist_ok=True)
    unmapped_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)

    sonarr_url = os.getenv("LIBRARIARR_SONARR_E2E_URL", "http://sonarr-test:8989").rstrip("/")
    api_key = _wait_for_api_key(Path("/sonarr-config/config.xml"))
    session = _wait_for_sonarr(sonarr_url, api_key)

    seeded_series = _seed_series_or_skip(session, sonarr_url, managed_root)
    series_id = int(seeded_series["id"])
    canonical_name = _canonical_name_from_seeded_series(seeded_series)

    unmapped_folder = unmapped_root / canonical_name
    season_one = unmapped_folder / "Season 01"
    season_one.mkdir(parents=True, exist_ok=True)
    source_file = season_one / "Fixture.Series.Unmapped.S01E01.1080p.x265.mkv"
    source_file.write_text("unmapped", encoding="utf-8")

    _update_sonarr_series_path(
        session,
        sonarr_url,
        series_id=series_id,
        new_path=unmapped_folder,
    )

    config = _build_service_config(
        managed_root=managed_root,
        library_root=library_root,
        sonarr_url=sonarr_url,
        api_key=api_key,
    )
    service = LibrariArrService(config)
    service.reconcile()

    projected = library_root / canonical_name / "Season 01" / source_file.name
    assert not projected.exists()


@pytest.mark.e2e
def test_sonarr_e2e_projection_respects_extras_allowlist() -> None:
    case_root = _resolve_case_root(f"sonarr_projection_extras_{uuid.uuid4().hex[:8]}")
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

    managed_folder = managed_root / canonical_name
    season_one = managed_folder / "Season 01"
    season_one.mkdir(parents=True, exist_ok=True)
    video_file = season_one / "Fixture.Series.S01E01.1080p.x265.mkv"
    subtitle_file = season_one / "Fixture.Series.S01E01.srt"
    rejected_file = season_one / "notes.txt"
    video_file.write_text("video", encoding="utf-8")
    subtitle_file.write_text("subtitle", encoding="utf-8")
    rejected_file.write_text("note", encoding="utf-8")

    _update_sonarr_series_path(
        session,
        sonarr_url,
        series_id=series_id,
        new_path=managed_folder,
    )

    config = _build_service_config(
        managed_root=managed_root,
        library_root=library_root,
        sonarr_url=sonarr_url,
        api_key=api_key,
    )

    service = LibrariArrService(config)
    service.reconcile()

    projected_root = library_root / canonical_name / "Season 01"
    assert (projected_root / video_file.name).exists()
    assert (projected_root / subtitle_file.name).exists()
    assert not (projected_root / rejected_file.name).exists()
