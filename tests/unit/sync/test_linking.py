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


def test_link_manager_uses_folder_name_not_movie_metadata(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    folder = nested_root / "Fixture Legacy (1977)"
    folder.mkdir(parents=True)
    shadow_root.mkdir(parents=True)

    movie = {"title": "Completely Different Title", "year": 1977}
    manager = ShadowLinkManager([nested_root])

    link, _ = manager.ensure_link(folder, shadow_root, existing_links=set(), movie=movie)

    assert link.name == "Fixture Legacy (1977)"
    assert link.is_symlink()


def test_link_manager_does_not_use_movie_metadata_title_for_link_name(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    folder = nested_root / "Face Off Source (1997)"
    folder.mkdir(parents=True)
    shadow_root.mkdir(parents=True)

    # Movie has a slash title - it must NOT be used for naming; folder name is the source of truth.
    movie = {"title": "Face/Off\\Redux", "year": 1997}
    manager = ShadowLinkManager([nested_root])

    link, _ = manager.ensure_link(folder, shadow_root, existing_links=set(), movie=movie)

    assert link.name == "Face Off Source (1997)"
    assert "/" not in link.name
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


def test_link_manager_preserves_existing_local_name_over_metadata_name(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    folder = nested_root / "Benno macht Geschichten (1982) FSK6"
    folder.mkdir(parents=True)
    shadow_root.mkdir(parents=True)

    existing_link = shadow_root / "Benno macht Geschichten (1982)"
    existing_link.symlink_to(folder, target_is_directory=True)

    movie = {"title": "Benno Makes Stories", "year": 1982}
    manager = ShadowLinkManager([nested_root])

    link, created = manager.ensure_link(
        folder,
        shadow_root,
        existing_links={existing_link},
        movie=movie,
    )

    assert created is False
    assert link == existing_link
    assert not (shadow_root / "Benno Makes Stories (1982)").exists()


def test_link_manager_does_not_reuse_stale_wrong_named_link(
    tmp_path: Path,
) -> None:
    """Regression: a stale symlink that points to the right target but has a wrong name
    (e.g. created when an NFO contained a wrong tmdbId that matched a different movie)
    must not be returned as-is.  A new symlink with the correct folder-canonical name
    should be created instead."""
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    folder = nested_root / "EO (2022)"
    folder.mkdir(parents=True)
    shadow_root.mkdir(parents=True)

    # Simulate the stale link created when NFO had the wrong Minions tmdbId.
    stale_link = shadow_root / "Minions - The Rise of Gru (2022)"
    stale_link.symlink_to(folder, target_is_directory=True)

    # NFO has been corrected; movie is now matched to EO.
    movie = {"title": "EO", "year": 2022}
    manager = ShadowLinkManager([nested_root])

    link, created = manager.ensure_link(
        folder,
        shadow_root,
        existing_links={stale_link},
        movie=movie,
    )

    assert link.name == "EO (2022)"
    assert link.is_symlink()
    assert link.resolve(strict=False) == folder
    assert created is True


def test_link_manager_omits_redundant_root_name_in_qualifier(tmp_path: Path) -> None:
    shadow_root = tmp_path / "FSK12"
    root_a = tmp_path / "source" / "FSK12"
    root_b = tmp_path / "archive" / "FSK12"
    shadow_root.mkdir(parents=True)

    folder_a = root_a / "Das Boot" / "Das Boot (1981)"
    folder_b = root_b / "Das Boot" / "Das Boot (1981)"
    folder_a.mkdir(parents=True)
    folder_b.mkdir(parents=True)

    manager = ShadowLinkManager([root_a, root_b])

    link_a, _ = manager.ensure_link(folder_a, shadow_root, existing_links=set(), movie=None)
    link_b, _ = manager.ensure_link(folder_b, shadow_root, existing_links=set(), movie=None)

    assert link_a.name == "Das Boot (1981)"
    assert link_b.name.startswith("Das Boot (1981)--")
    assert "--FSK12-" not in link_b.name
    assert link_b.name.endswith("--Das-Boot")
