"""Sonarr projection fs-e2e tests.

Sonarr-specific scenarios: season-subfolder projection, series extras
at root and season level, and nested_root/shadow_root mapping.
"""

from pathlib import Path

import pytest

from librariarr.service import LibrariArrService

from .conftest import FakeSonarr, make_roots, make_series, make_sonarr_config


@pytest.mark.fs_e2e
def test_sonarr_projects_season_subfolder_structure(tmp_path: Path) -> None:
    """Series with Season subdirectories should produce matching subfolder
    structure in the shadow root with hardlinks for each episode."""
    nested_root, shadow_root = make_roots(tmp_path, "sonarr_season_folders")

    series_dir = nested_root / "Breaking Bad (2008)"
    s01 = series_dir / "Season 01"
    s02 = series_dir / "Season 02"
    s01.mkdir(parents=True)
    s02.mkdir(parents=True)

    ep1 = s01 / "Breaking.Bad.S01E01.1080p.mkv"
    ep2 = s01 / "Breaking.Bad.S01E02.1080p.mkv"
    ep3 = s02 / "Breaking.Bad.S02E01.1080p.mkv"
    ep1.write_text("s01e01", encoding="utf-8")
    ep2.write_text("s01e02", encoding="utf-8")
    ep3.write_text("s02e01", encoding="utf-8")

    config = make_sonarr_config(nested_root=nested_root, shadow_root=shadow_root)

    service = LibrariArrService(config)
    service.sonarr = FakeSonarr(series=[make_series(1, "Breaking Bad", 2008, series_dir)])

    service.reconcile()

    proj_s01e01 = shadow_root / "Breaking Bad (2008)" / "Season 01" / ep1.name
    proj_s01e02 = shadow_root / "Breaking Bad (2008)" / "Season 01" / ep2.name
    proj_s02e01 = shadow_root / "Breaking Bad (2008)" / "Season 02" / ep3.name

    assert proj_s01e01.exists(), "S01E01 should be projected"
    assert proj_s01e02.exists(), "S01E02 should be projected"
    assert proj_s02e01.exists(), "S02E01 should be projected"

    assert proj_s01e01.samefile(ep1), "Projected file should be hardlink to source"
    assert proj_s01e02.samefile(ep2)
    assert proj_s02e01.samefile(ep3)


@pytest.mark.fs_e2e
def test_sonarr_projects_series_extras(tmp_path: Path) -> None:
    """Series extras (tvshow.nfo at root, .srt alongside episodes) should be
    projected according to the default Sonarr extras allowlist."""
    nested_root, shadow_root = make_roots(tmp_path, "sonarr_extras")

    series_dir = nested_root / "The Wire (2002)"
    s01 = series_dir / "Season 01"
    s01.mkdir(parents=True)

    # Root-level extras
    tvshow_nfo = series_dir / "tvshow.nfo"
    tvshow_nfo.write_text("tvshow-nfo", encoding="utf-8")
    poster = series_dir / "poster.jpg"
    poster.write_text("poster-data", encoding="utf-8")

    # Episode + subtitle
    ep = s01 / "The.Wire.S01E01.1080p.mkv"
    ep.write_text("episode", encoding="utf-8")
    srt = s01 / "The.Wire.S01E01.srt"
    srt.write_text("subtitle", encoding="utf-8")

    # Non-allowlisted file
    readme = series_dir / "readme.txt"
    readme.write_text("should not project", encoding="utf-8")

    config = make_sonarr_config(nested_root=nested_root, shadow_root=shadow_root)

    service = LibrariArrService(config)
    service.sonarr = FakeSonarr(series=[make_series(1, "The Wire", 2002, series_dir)])

    service.reconcile()

    shadow_series = shadow_root / "The Wire (2002)"
    assert (shadow_series / "tvshow.nfo").exists(), "tvshow.nfo should be projected"
    assert (shadow_series / "poster.jpg").exists(), "poster.jpg should be projected"
    assert (shadow_series / "Season 01" / ep.name).exists(), "Episode should be projected"
    assert (shadow_series / "Season 01" / srt.name).exists(), "SRT should be projected"
    assert not (shadow_series / "readme.txt").exists(), "Non-allowlisted file should NOT project"


@pytest.mark.fs_e2e
def test_sonarr_flat_series_without_season_folders(tmp_path: Path) -> None:
    """A series with episodes directly in the root (no season subfolders)
    should still project correctly."""
    nested_root, shadow_root = make_roots(tmp_path, "sonarr_flat_series")

    series_dir = nested_root / "Miniseries (2024)"
    series_dir.mkdir(parents=True)

    ep1 = series_dir / "Miniseries.S01E01.mkv"
    ep2 = series_dir / "Miniseries.S01E02.mkv"
    ep1.write_text("ep1", encoding="utf-8")
    ep2.write_text("ep2", encoding="utf-8")

    config = make_sonarr_config(nested_root=nested_root, shadow_root=shadow_root)

    service = LibrariArrService(config)
    service.sonarr = FakeSonarr(series=[make_series(1, "Miniseries", 2024, series_dir)])

    service.reconcile()

    shadow_series = shadow_root / "Miniseries (2024)"
    assert (shadow_series / ep1.name).exists(), "Episode in root should be projected"
    assert (shadow_series / ep2.name).exists()
    assert (shadow_series / ep1.name).samefile(ep1)


@pytest.mark.fs_e2e
def test_sonarr_name_mismatch_projects_canonical(tmp_path: Path) -> None:
    """When the nested folder name differs from Sonarr's canonical title,
    projection should use the canonical name for the shadow folder."""
    nested_root, shadow_root = make_roots(tmp_path, "sonarr_name_mismatch")

    # Actual folder has extra info in the name
    series_dir = nested_root / "Game of Thrones (2011) Complete"
    series_dir.mkdir(parents=True)
    s01 = series_dir / "Season 01"
    s01.mkdir(parents=True)
    ep = s01 / "GoT.S01E01.1080p.mkv"
    ep.write_text("episode", encoding="utf-8")

    config = make_sonarr_config(nested_root=nested_root, shadow_root=shadow_root)

    service = LibrariArrService(config)
    service.sonarr = FakeSonarr(series=[make_series(1, "Game of Thrones", 2011, series_dir)])

    service.reconcile()

    # Should use canonical name
    canonical = shadow_root / "Game of Thrones (2011)" / "Season 01" / ep.name
    assert canonical.exists(), "Projection should use canonical series name"
    assert canonical.samefile(ep)

    # Decorated name should NOT appear in shadow
    decorated = shadow_root / "Game of Thrones (2011) Complete"
    assert not decorated.exists(), "Decorated folder name should not be in shadow root"


@pytest.mark.fs_e2e
def test_sonarr_missing_nested_folder_skips(tmp_path: Path) -> None:
    """When the nested (managed) folder doesn't exist, Sonarr projection should
    skip without errors."""
    nested_root, shadow_root = make_roots(tmp_path, "sonarr_missing_nested")

    ghost_path = nested_root / "Ghost Series (2024)"

    config = make_sonarr_config(nested_root=nested_root, shadow_root=shadow_root)

    service = LibrariArrService(config)
    service.sonarr = FakeSonarr(series=[make_series(1, "Ghost Series", 2024, ghost_path)])

    service.reconcile()

    assert not (shadow_root / "Ghost Series (2024)").exists()
