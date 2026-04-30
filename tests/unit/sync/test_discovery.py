from pathlib import Path

from librariarr.service.reconcile_helpers import discover_unmatched_folders
from librariarr.sync.discovery import (
    collect_current_links,
    discover_movie_folders,
    discover_series_folders,
)


def test_discover_movie_folders_identifies_parent_movie_dir(tmp_path: Path) -> None:
    root = tmp_path / "movies"
    movie_dir = root / "Studio" / "Movie A (2020)"
    nested_extra = movie_dir / "extras"
    movie_dir.mkdir(parents=True)
    nested_extra.mkdir(parents=True)
    (movie_dir / "Movie.A.2020.1080p.mkv").write_text("x", encoding="utf-8")
    (nested_extra / "featurette.mp4").write_text("x", encoding="utf-8")

    found = discover_movie_folders(root, {".mkv", ".mp4"})

    assert movie_dir in found
    assert nested_extra not in found


def test_collect_current_links_maps_target_to_all_links(tmp_path: Path) -> None:
    shadow_a = tmp_path / "radarr_a"
    shadow_b = tmp_path / "radarr_b"
    target = tmp_path / "movies" / "Movie B (2021)"
    shadow_a.mkdir(parents=True)
    shadow_b.mkdir(parents=True)
    target.mkdir(parents=True)

    link_a = shadow_a / "Movie B (2021)"
    link_b = shadow_b / "Movie B (2021)"
    link_a.symlink_to(target, target_is_directory=True)
    link_b.symlink_to(target, target_is_directory=True)
    (shadow_a / "not-a-link").mkdir()

    links = collect_current_links([shadow_a, shadow_b])

    assert target in links
    assert links[target] == {link_a, link_b}


def test_discover_movie_folders_ignores_season_directories(tmp_path: Path) -> None:
    root = tmp_path / "library"
    season_dir = root / "Show A" / "Season 01"
    season_dir.mkdir(parents=True)
    (season_dir / "Show.A.S01E01.1080p.mkv").write_text("x", encoding="utf-8")

    found = discover_movie_folders(root, {".mkv", ".mp4"})

    assert season_dir not in found


def test_discover_series_folders_detects_standard_season_layout(tmp_path: Path) -> None:
    root = tmp_path / "series"
    series_dir = root / "Show A (2020)"
    season_one = series_dir / "Season 01"
    season_one.mkdir(parents=True)
    (season_one / "Show.A.S01E01.1080p.mkv").write_text("x", encoding="utf-8")

    found = discover_series_folders(root, {".mkv", ".mp4"})

    assert series_dir in found
    assert season_one not in found


def test_discover_series_folders_detects_flat_episode_layout(tmp_path: Path) -> None:
    root = tmp_path / "series"
    series_dir = root / "Show B"
    series_dir.mkdir(parents=True)
    (series_dir / "Show.B.S01E01.1080p.mkv").write_text("x", encoding="utf-8")

    found = discover_series_folders(root, {".mkv", ".mp4"})

    assert series_dir in found


def test_discover_movie_folders_honors_exclude_paths(tmp_path: Path) -> None:
    root = tmp_path / "movies"
    valid_dir = root / "FSK12" / "Pierre Richard Collection" / "Der Regenschirmmörder (1980)"
    deleted_dir = (
        root
        / "FSK12"
        / ".deletedByTMM"
        / "Pierre Richard Collection"
        / "[2] Der Regenschirmmörder (1980) FSK12"
    )
    valid_dir.mkdir(parents=True)
    deleted_dir.mkdir(parents=True)
    (valid_dir / "movie.mkv").write_text("x", encoding="utf-8")
    (deleted_dir / "movie.mkv").write_text("x", encoding="utf-8")

    found = discover_movie_folders(root, {".mkv", ".mp4"}, [".deletedByTMM/"])

    assert valid_dir in found
    assert deleted_dir not in found


def test_discover_series_folders_honors_exclude_paths(tmp_path: Path) -> None:
    root = tmp_path / "series"
    valid_series = root / "Show A"
    deleted_series = root / ".deletedByTMM" / "Show B"
    (valid_series / "Season 01").mkdir(parents=True)
    (deleted_series / "Season 01").mkdir(parents=True)
    (valid_series / "Season 01" / "Show.A.S01E01.1080p.mkv").write_text("x", encoding="utf-8")
    (deleted_series / "Season 01" / "Show.B.S01E01.1080p.mkv").write_text("x", encoding="utf-8")

    found = discover_series_folders(root, {".mkv", ".mp4"}, [".deletedByTMM/"])

    assert valid_series in found
    assert deleted_series not in found


def test_discover_series_folders_skips_season_folder_with_flat_episodes(tmp_path: Path) -> None:
    """A folder named like a season (Season 06, Staffel 01, S03) must not be a series root."""
    root = tmp_path / "series"
    series_dir = root / "FSK12" / "Show A (2020)"
    season_en = series_dir / "Season 06"
    season_de = series_dir / "Staffel 01"
    season_en.mkdir(parents=True)
    season_de.mkdir(parents=True)
    (season_en / "Show.A.S06E01.1080p.mkv").write_text("x", encoding="utf-8")
    (season_de / "Show.A.S01E01.1080p.mkv").write_text("x", encoding="utf-8")

    found = discover_series_folders(root, {".mkv", ".mp4"})

    assert series_dir in found
    assert season_en not in found
    assert season_de not in found


def test_discover_series_folders_skips_standalone_season_folder_at_root(tmp_path: Path) -> None:
    """A stray season folder directly under the nested root must not become a series root."""
    root = tmp_path / "series"
    stray_season = root / "Season 06"
    stray_season.mkdir(parents=True)
    (stray_season / "Show.A.S06E01.1080p.mkv").write_text("x", encoding="utf-8")

    found = discover_series_folders(root, {".mkv", ".mp4"})

    assert stray_season not in found


def test_discover_series_folders_works_with_deep_nesting(tmp_path: Path) -> None:
    """Series grouped inside a parent folder (e.g. Star Trek/) are still discovered."""
    root = tmp_path / "series"
    group_dir = root / "FSK12" / "Star Trek"
    series_a = group_dir / "Show A (1987)"
    series_b = group_dir / "Show B (1993)"
    (series_a / "Staffel 01").mkdir(parents=True)
    (series_b / "Season 01").mkdir(parents=True)
    (series_a / "Staffel 01" / "Show.A.S01E01.1080p.mkv").write_text("x", encoding="utf-8")
    (series_b / "Season 01" / "Show.B.S01E01.1080p.mkv").write_text("x", encoding="utf-8")

    found = discover_series_folders(root, {".mkv", ".mp4"})

    assert series_a in found
    assert series_b in found
    assert group_dir not in found


def test_discover_series_folders_skips_season_named_with_nested_seasons(tmp_path: Path) -> None:
    """Even if a season folder itself contains sub-season dirs, it must not be a series root."""
    root = tmp_path / "series"
    series_dir = root / "Show A"
    outer_season = series_dir / "Staffel 01"
    inner_season = outer_season / "Season 01"
    inner_season.mkdir(parents=True)
    (inner_season / "ep.S01E01.mkv").write_text("x", encoding="utf-8")

    found = discover_series_folders(root, {".mkv", ".mp4"})

    assert outer_season not in found
    assert inner_season not in found
    # The series_dir itself is the valid root (it contains season subdirs).
    assert series_dir in found


def test_discover_movie_folders_honors_exclude_paths_case_insensitive(tmp_path: Path) -> None:
    root = tmp_path / "movies"
    valid_dir = root / "FSK12" / "Movie A (2020)"
    deleted_dir = root / "FSK12" / ".DeletedByTMM" / "Movie B (2021)"
    valid_dir.mkdir(parents=True)
    deleted_dir.mkdir(parents=True)
    (valid_dir / "movie.mkv").write_text("x", encoding="utf-8")
    (deleted_dir / "movie.mkv").write_text("x", encoding="utf-8")

    found = discover_movie_folders(root, {".mkv", ".mp4"}, [".deletedbytmm/"])

    assert valid_dir in found
    assert deleted_dir not in found


def test_discover_unmatched_folders_marks_non_canonical_names_unmatched(tmp_path: Path) -> None:
    """Managed folders with non-canonical names (e.g. 'Title (Year) FSK6') should be
    treated as unmatched so auto-add can resolve/store explicit mappings."""
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"

    # Create managed folders with FSK suffixes
    movie_a = managed_root / "A Rainy Day in New York (2019) FSK0"
    movie_b = managed_root / "Barbie (2023) FSK6"
    movie_a.mkdir(parents=True)
    movie_b.mkdir(parents=True)
    (movie_a / "movie.mkv").write_text("x", encoding="utf-8")
    (movie_b / "movie.mkv").write_text("x", encoding="utf-8")

    # existing_paths represents what managed_equivalent_path() returns:
    # canonical names (without FSK suffix) resolved under managed_root.
    # Non-canonical managed folders should still be treated as unmatched so
    # auto-add can resolve them via Radarr API and store movie_id->managed mapping.
    existing_paths = {
        (managed_root / "A Rainy Day in New York (2019)").resolve(strict=False),
        (managed_root / "Barbie (2023)").resolve(strict=False),
    }

    unmatched = discover_unmatched_folders(
        mappings=[(managed_root, library_root)],
        existing_paths=existing_paths,
        affected_paths=None,
        discover_fn=discover_movie_folders,
        video_exts={".mkv"},
        scan_exclude_paths=set(),
    )

    assert movie_a in unmatched
    assert movie_b in unmatched
