from pathlib import Path

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


def test_discover_movie_folders_ignores_common_non_movie_folder_names(tmp_path: Path) -> None:
    root = tmp_path / "movies"
    movie_dir = root / "Movie A (2020)"
    specials_dir = root / "Specials"
    extras_dir = root / "EXTRAS"
    movie_dir.mkdir(parents=True)
    specials_dir.mkdir(parents=True)
    extras_dir.mkdir(parents=True)
    (movie_dir / "Movie.A.2020.1080p.mkv").write_text("x", encoding="utf-8")
    (specials_dir / "Show.S00E01.1080p.mkv").write_text("x", encoding="utf-8")
    (extras_dir / "Featurette.mp4").write_text("x", encoding="utf-8")

    found = discover_movie_folders(root, {".mkv", ".mp4"})

    assert movie_dir in found
    assert specials_dir not in found
    assert extras_dir not in found
