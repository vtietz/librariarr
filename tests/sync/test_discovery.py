from pathlib import Path

from librariarr.sync.discovery import collect_current_links, discover_movie_folders


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
