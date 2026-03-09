from pathlib import Path

from librariarr.sync.linking import ShadowLinkManager


def test_link_manager_creates_canonical_link_without_movie(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    folder = nested_root / "Sing (2016) FSK0"
    folder.mkdir(parents=True)
    shadow_root.mkdir(parents=True)

    manager = ShadowLinkManager([nested_root])

    link, created = manager.ensure_link(folder, shadow_root, existing_links=set(), movie=None)

    assert created is True
    assert link.name == "Sing (2016)"
    assert link.is_symlink()
    assert link.resolve(strict=False) == folder


def test_link_manager_uses_movie_metadata_name(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    folder = nested_root / "Star Wars"
    folder.mkdir(parents=True)
    shadow_root.mkdir(parents=True)

    movie = {"title": "Star Wars", "year": 1977}
    manager = ShadowLinkManager([nested_root])

    link, _ = manager.ensure_link(folder, shadow_root, existing_links=set(), movie=movie)

    assert link.name == "Star Wars (1977)"
    assert link.is_symlink()


def test_link_manager_qualifies_colliding_names(tmp_path: Path) -> None:
    shadow_root = tmp_path / "radarr_library"
    root_a = tmp_path / "age_12"
    root_b = tmp_path / "age_16"
    shadow_root.mkdir(parents=True)

    folder_a = root_a / "Blender" / "Sintel (2010)"
    folder_b = root_b / "OpenFilms" / "Sintel (2010)"
    folder_a.mkdir(parents=True)
    folder_b.mkdir(parents=True)

    manager = ShadowLinkManager([root_a, root_b])

    link_a, _ = manager.ensure_link(folder_a, shadow_root, existing_links=set(), movie=None)
    link_b, _ = manager.ensure_link(folder_b, shadow_root, existing_links=set(), movie=None)

    assert link_a.name == "Sintel (2010)"
    assert link_b.name.startswith("Sintel (2010)--")
    assert link_b.is_symlink()
    assert link_b.resolve(strict=False) == folder_b
