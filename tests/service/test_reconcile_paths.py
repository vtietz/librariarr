import shutil
from pathlib import Path

import pytest

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    PathsConfig,
    QualityRule,
    RadarrConfig,
    RadarrMappingConfig,
    RootMapping,
    RuntimeConfig,
)
from librariarr.service import LibrariArrService
from tests.service.helpers import FakeRadarr, make_config

pytestmark = pytest.mark.skip(
    reason="Legacy Radarr link/matching flow removed in projection-only mode"
)


def test_reconcile_uses_qualified_name_on_collision(tmp_path: Path) -> None:
    root_one = tmp_path / "age_12"
    root_two = tmp_path / "age_16"
    shadow_root = tmp_path / "radarr_library"

    movie_one = root_one / "Blender" / "Sintel (2010)"
    movie_two = root_two / "OpenFilms" / "Sintel (2010)"
    movie_one.mkdir(parents=True)
    movie_two.mkdir(parents=True)
    (movie_one / "Sintel.2010.1080p.x265.mkv").write_text("x", encoding="utf-8")
    (movie_two / "Sintel.2010.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = AppConfig(
        paths=PathsConfig(
            root_mappings=[
                RootMapping(nested_root=str(root_one), shadow_root=str(shadow_root)),
                RootMapping(nested_root=str(root_two), shadow_root=str(shadow_root)),
            ]
        ),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            sync_enabled=False,
            mapping=RadarrMappingConfig(
                quality_map=[QualityRule(match=["1080p", "x265"], target_id=7)]
            ),
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )
    service = LibrariArrService(config)

    service.reconcile()

    plain = shadow_root / "Sintel (2010)"
    qualified = shadow_root / "Sintel (2010)--age_16-OpenFilms"

    assert plain.is_symlink()
    assert qualified.is_symlink()


def test_reconcile_deletes_radarr_entry_when_configured(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)
    shadow_root.mkdir(parents=True)

    missing_target = nested_root / "Tears of Steel (2012)"
    orphan = shadow_root / "Tears of Steel (2012)"
    orphan.symlink_to(missing_target, target_is_directory=True)

    config = make_config(
        nested_root,
        shadow_root,
        sync_enabled=True,
        radarr_action_on_missing="delete",
    )
    service = LibrariArrService(config)

    fake = FakeRadarr(
        movies=[
            {
                "id": 77,
                "title": "Tears of Steel",
                "year": 2012,
                "path": "/old/path",
                "movieFile": {"id": 17},
                "monitored": True,
            }
        ]
    )
    service.radarr = fake

    service.reconcile()

    assert not orphan.exists()
    assert fake.deleted == [77]
    assert fake.unmonitored == []
    assert fake.refreshed == []


def test_reconcile_routes_links_to_mapped_shadow_roots(tmp_path: Path) -> None:
    age12_root = tmp_path / "movies" / "age_12"
    age16_root = tmp_path / "movies" / "age_16"
    age12_shadow = tmp_path / "radarr_library" / "age_12"
    age16_shadow = tmp_path / "radarr_library" / "age_16"

    movie_age12 = age12_root / "Studio" / "Movie A (2020)"
    movie_age16 = age16_root / "Studio" / "Movie B (2021)"
    movie_age12.mkdir(parents=True)
    movie_age16.mkdir(parents=True)
    (movie_age12 / "Movie.A.2020.1080p.x265.mkv").write_text("x", encoding="utf-8")
    (movie_age16 / "Movie.B.2021.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = AppConfig(
        paths=PathsConfig(
            root_mappings=[
                RootMapping(nested_root=str(age12_root), shadow_root=str(age12_shadow)),
                RootMapping(nested_root=str(age16_root), shadow_root=str(age16_shadow)),
            ]
        ),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            sync_enabled=False,
            mapping=RadarrMappingConfig(
                quality_map=[QualityRule(match=["1080p", "x265"], target_id=7)]
            ),
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )

    service = LibrariArrService(config)
    service.reconcile()

    assert (age12_shadow / "Movie A (2020)").is_symlink()
    assert not (age16_shadow / "Movie A (2020)").exists()
    assert (age16_shadow / "Movie B (2021)").is_symlink()
    assert not (age12_shadow / "Movie B (2021)").exists()


def test_reconcile_updates_path_when_movie_moves_between_mapped_roots(tmp_path: Path) -> None:
    age12_root = tmp_path / "movies" / "age_12"
    age16_root = tmp_path / "movies" / "age_16"
    age12_shadow = tmp_path / "radarr_library" / "age_12"
    age16_shadow = tmp_path / "radarr_library" / "age_16"

    movie_old = age12_root / "Studio" / "Movie A (2020)"
    movie_old.mkdir(parents=True)
    (movie_old / "Movie.A.2020.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = AppConfig(
        paths=PathsConfig(
            root_mappings=[
                RootMapping(nested_root=str(age12_root), shadow_root=str(age12_shadow)),
                RootMapping(nested_root=str(age16_root), shadow_root=str(age16_shadow)),
            ]
        ),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            sync_enabled=True,
            mapping=RadarrMappingConfig(
                quality_map=[QualityRule(match=["1080p", "x265"], target_id=7)]
            ),
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )

    service = LibrariArrService(config)
    fake = FakeRadarr(
        movies=[
            {
                "id": 1,
                "title": "Movie A",
                "year": 2020,
                "path": "/old/path",
                "movieFile": {"id": 11},
                "monitored": True,
            }
        ]
    )
    service.radarr = fake

    service.reconcile()

    old_link = age12_shadow / "Movie A (2020)"
    assert old_link.is_symlink()
    assert fake.updated_paths[-1] == (1, str(old_link))

    movie_new = age16_root / "Studio" / "Movie A (2020)"
    movie_new.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(movie_old), str(movie_new))

    service.reconcile({movie_old, movie_new})

    new_link = age16_shadow / "Movie A (2020)"
    assert new_link.is_symlink()
    assert not old_link.exists()
    assert fake.updated_paths[-1] == (1, str(new_link))


def test_reconcile_strict_policy_blocks_title_year_path_update(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Fixture Catalog A (2008)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Fixture.Catalog.A.2008.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(
        nested_root,
        shadow_root,
        sync_enabled=True,
        path_update_match_policy="external_ids_only",
    )
    service = LibrariArrService(config)

    fake = FakeRadarr(
        movies=[
            {
                "id": 1,
                "title": "Fixture Catalog A",
                "year": 2008,
                "path": "/old/path",
                "movieFile": {"id": 11},
                "monitored": True,
            }
        ]
    )
    service.radarr = fake

    service.reconcile()

    expected_link = shadow_root / "Fixture Catalog A (2008)"
    assert expected_link.is_symlink()
    assert fake.updated_paths == []
    assert fake.refreshed == []


def test_reconcile_strict_policy_allows_external_id_path_update(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Fixture Catalog A (2008)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Fixture.Catalog.A.2008.1080p.x265.mkv").write_text("x", encoding="utf-8")
    (movie_dir / "movie.nfo").write_text("<movie><tmdbid>9008</tmdbid></movie>", encoding="utf-8")

    config = make_config(
        nested_root,
        shadow_root,
        sync_enabled=True,
        path_update_match_policy="external_ids_only",
    )
    service = LibrariArrService(config)

    fake = FakeRadarr(
        movies=[
            {
                "id": 1,
                "title": "Different Title",
                "year": 2008,
                "tmdbId": 9008,
                "path": "/old/path",
                "movieFile": {"id": 11},
                "monitored": True,
            }
        ]
    )
    service.radarr = fake

    service.reconcile()

    expected_link = shadow_root / "Fixture Catalog A (2008)"
    assert expected_link.is_symlink()
    assert fake.updated_paths[-1] == (1, str(expected_link))
    assert fake.refreshed == [1]


def test_reconcile_uses_folder_name_for_link(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Fixture Legacy"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Star.Wars.1977.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    service = LibrariArrService(config)
    fake = FakeRadarr(
        movies=[
            {
                "id": 1,
                "title": "Fixture Legacy",
                "year": 1977,
                "path": "/old/path",
                "movieFile": {"id": 11},
                "monitored": True,
            }
        ]
    )
    service.radarr = fake

    service.reconcile()

    # Link is named after the folder, not the Radarr-metadata title+year.
    folder_link = shadow_root / "Fixture Legacy"
    assert folder_link.is_symlink()


def test_reconcile_skips_quality_update_when_quality_map_empty(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Fixture Catalog A (2008)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Big.Buck.Bunny.2008.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    config.radarr.mapping.quality_map = []
    service = LibrariArrService(config)

    fake = FakeRadarr(
        movies=[
            {
                "id": 1,
                "title": "Fixture Catalog A",
                "year": 2008,
                "path": "/old/path",
                "movieFile": {"id": 11},
                "monitored": True,
            }
        ]
    )
    service.radarr = fake

    service.reconcile()

    assert fake.updated_paths and fake.updated_paths[0][0] == 1
    assert fake.updated_qualities == []
    assert fake.refreshed == [1]


def test_reconcile_skips_refresh_when_movie_state_unchanged(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Fixture Catalog A (2008)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Big.Buck.Bunny.2008.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    config.radarr.mapping.quality_map = []
    service = LibrariArrService(config)

    link_path = shadow_root / "Fixture Catalog A (2008)"
    fake = FakeRadarr(
        movies=[
            {
                "id": 1,
                "title": "Fixture Catalog A",
                "year": 2008,
                "path": str(link_path),
                "movieFile": {"id": 11},
                "monitored": True,
            }
        ]
    )
    service.radarr = fake

    service.reconcile()

    assert fake.updated_paths == []
    assert fake.updated_qualities == []
    assert fake.refreshed == []


def test_reconcile_auto_add_skips_quality_mapping_without_movie_file(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Fixture Catalog B (2009)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Fixture.Catalog.B.2009.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(
        nested_root,
        shadow_root,
        sync_enabled=True,
        auto_add_unmatched=True,
        auto_add_quality_profile_id=7,
    )
    service = LibrariArrService(config)

    fake = FakeRadarr(
        movies=[],
        lookup_results=[{"title": "Fixture Catalog B", "year": 2009, "tmdbId": 9009}],
        add_movie_result={
            "id": 99,
            "title": "Fixture Catalog B",
            "year": 2009,
            "path": str(shadow_root / "Fixture Catalog B (2009)"),
        },
    )
    service.radarr = fake

    service.reconcile()

    assert fake.added_movies
    assert fake.updated_qualities == []
    assert fake.refreshed == [99]


def test_reconcile_preserves_existing_valid_local_link(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Fixture Legacy"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Star.Wars.1977.1080p.x265.mkv").write_text("x", encoding="utf-8")
    shadow_root.mkdir(parents=True)
    stale_link = shadow_root / "Fixture Legacy"
    stale_link.symlink_to(movie_dir, target_is_directory=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    service = LibrariArrService(config)
    fake = FakeRadarr(
        movies=[
            {
                "id": 1,
                "title": "Fixture Legacy",
                "year": 1977,
                "path": "/old/path",
                "movieFile": {"id": 11},
                "monitored": True,
            }
        ]
    )
    service.radarr = fake

    service.reconcile()

    assert stale_link.is_symlink()
    assert not (shadow_root / "Fixture Legacy (1977)").exists()
    assert fake.updated_paths == [(1, str(stale_link))]


def test_reconcile_removes_duplicate_alternate_title_link(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Benno macht Geschichten (1982) FSK6"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Benno.macht.Geschichten.1982.1080p.x265.mkv").write_text("x", encoding="utf-8")
    shadow_root.mkdir(parents=True)

    local_link = shadow_root / "Benno macht Geschichten (1982)"
    english_link = shadow_root / "Benno Makes Stories (1982)"
    local_link.symlink_to(movie_dir, target_is_directory=True)
    english_link.symlink_to(movie_dir, target_is_directory=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    service = LibrariArrService(config)
    fake = FakeRadarr(
        movies=[
            {
                "id": 1,
                "title": "Benno Makes Stories",
                "year": 1982,
                "path": str(english_link),
                "movieFile": {"id": 11},
                "monitored": True,
            }
        ]
    )
    service.radarr = fake

    service.reconcile()

    assert local_link.is_symlink()
    assert not english_link.exists()
    assert fake.updated_paths == [(1, str(local_link))]
