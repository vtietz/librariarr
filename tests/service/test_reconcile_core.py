from pathlib import Path
from unittest.mock import patch

import requests

from librariarr.service import LibrariArrService
from librariarr.sync.discovery import discover_movie_folders as discover_movie_folders_impl
from tests.service.helpers import FakeRadarr, make_config


def test_reconcile_creates_symlink_for_movie_folder(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie = nested_root / "Fixture Catalog A (2008)"
    movie.mkdir(parents=True)
    (movie / "Big.Buck.Bunny.2008.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=False)
    service = LibrariArrService(config)

    service.reconcile()

    link = shadow_root / "Fixture Catalog A (2008)"
    assert link.is_symlink()
    assert link.resolve(strict=False) == movie


def test_reconcile_skips_movie_folders_when_radarr_disabled(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie = nested_root / "Fixture Catalog A (2008)"
    movie.mkdir(parents=True)
    (movie / "Big.Buck.Bunny.2008.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=False, radarr_enabled=False)
    service = LibrariArrService(config)

    service.reconcile()

    link = shadow_root / "Fixture Catalog A (2008)"
    assert not link.exists()


def test_reconcile_incremental_scans_only_affected_folder(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_a = nested_root / "Fixture Catalog A (2008)"
    movie_b = nested_root / "Fixture Catalog B (2009)"
    movie_a.mkdir(parents=True)
    movie_b.mkdir(parents=True)
    (movie_a / "Fixture.Catalog.A.2008.1080p.x265.mkv").write_text("x", encoding="utf-8")
    (movie_b / "Fixture.Catalog.B.2009.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=False)
    service = LibrariArrService(config)

    service.reconcile()

    changed_file = movie_a / "notes.txt"
    changed_file.write_text("update", encoding="utf-8")
    scanned_roots: list[Path] = []

    with patch("librariarr.service.reconcile.discover_movie_folders") as mocked_discovery:
        mocked_discovery.side_effect = lambda root, video_exts, exclude_paths=None: (
            scanned_roots.append(root)
            or discover_movie_folders_impl(root, video_exts, exclude_paths)
        )
        service.reconcile({changed_file})

    assert scanned_roots == [movie_a]
    assert (shadow_root / "Fixture Catalog A (2008)").is_symlink()
    assert (shadow_root / "Fixture Catalog B (2009)").is_symlink()


def test_reconcile_shadow_only_event_skips_movie_rescan_when_ingest_enabled(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_a = nested_root / "Fixture Catalog A (2008)"
    movie_b = nested_root / "Fixture Catalog B (2009)"
    movie_a.mkdir(parents=True)
    movie_b.mkdir(parents=True)
    (movie_a / "Fixture.Catalog.A.2008.1080p.x265.mkv").write_text("x", encoding="utf-8")
    (movie_b / "Fixture.Catalog.B.2009.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=False)
    config.ingest.enabled = True
    service = LibrariArrService(config)

    service.reconcile()

    shadow_event_path = shadow_root / "incoming"
    scanned_roots: list[Path] = []

    with patch("librariarr.service.reconcile.discover_movie_folders") as mocked_discovery:
        mocked_discovery.side_effect = lambda root, video_exts, exclude_paths=None: (
            scanned_roots.append(root)
            or discover_movie_folders_impl(root, video_exts, exclude_paths)
        )
        service.reconcile({shadow_event_path})

    assert scanned_roots == []


def test_reconcile_removes_orphaned_symlink(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)
    shadow_root.mkdir(parents=True)

    missing_target = nested_root / "Tears of Steel (2012)"
    orphan = shadow_root / "Tears of Steel (2012)"
    orphan.symlink_to(missing_target, target_is_directory=True)

    config = make_config(nested_root, shadow_root, sync_enabled=False)
    service = LibrariArrService(config)

    service.reconcile()

    assert not orphan.exists()


def test_reconcile_syncs_radarr_when_enabled(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Fixture Catalog A (2008)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Big.Buck.Bunny.2008.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=True)
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

    assert fake.get_movies_calls == 1
    assert fake.updated_paths and fake.updated_paths[0][0] == 1
    assert fake.updated_qualities == []
    assert fake.refreshed == [1]


def test_reconcile_continues_when_radarr_update_returns_404(tmp_path: Path, caplog) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Fixture Catalog A (2008)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Big.Buck.Bunny.2008.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    service = LibrariArrService(config)

    fake = FakeRadarr(
        movies=[
            {
                "id": 120,
                "title": "Fixture Catalog A",
                "year": 2008,
                "path": "/old/path",
                "movieFile": {"id": 11},
                "monitored": True,
            }
        ]
    )

    def _raise_not_found(movie: dict, new_path: str) -> bool:
        del movie
        del new_path
        response = requests.Response()
        response.status_code = 404
        response.url = "http://radarr:7878/api/v3/movie/120"
        raise requests.HTTPError("404 Client Error: Not Found", response=response)

    fake.update_movie_path = _raise_not_found  # type: ignore[method-assign]
    service.radarr = fake
    caplog.set_level("WARNING", logger="librariarr.service")

    service.reconcile()

    link = shadow_root / "Fixture Catalog A (2008)"
    assert link.is_symlink()
    assert fake.refreshed == []
    assert "Skipping Radarr sync for missing movie" in caplog.text


def test_reconcile_skips_radarr_when_sync_disabled(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Fixture Catalog A (2008)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Big.Buck.Bunny.2008.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=False)
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

    assert fake.get_movies_calls == 0
    assert fake.updated_paths == []
    assert fake.updated_qualities == []
    assert fake.refreshed == []


def test_reconcile_canonicalizes_suffix_folder_name_without_sync(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Sing (2016) FSK0"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Sing.2016.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=False)
    service = LibrariArrService(config)

    service.reconcile()

    canonical_link = shadow_root / "Sing (2016)"
    assert canonical_link.is_symlink()
    assert canonical_link.resolve(strict=False) == movie_dir
    assert not (shadow_root / "Sing (2016) FSK0").exists()


def test_reconcile_matches_radarr_for_suffix_folder_name(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Sing (2016) FSK0"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Sing.2016.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    service = LibrariArrService(config)

    fake = FakeRadarr(
        movies=[
            {
                "id": 2,
                "title": "Sing",
                "year": 2016,
                "path": "/old/path",
                "movieFile": {"id": 12},
                "monitored": True,
            }
        ]
    )
    service.radarr = fake

    service.reconcile()

    assert fake.get_movies_calls == 1
    assert fake.updated_paths and fake.updated_paths[0][0] == 2
    assert (shadow_root / "Sing (2016)").is_symlink()


def test_reconcile_matches_existing_radarr_movie_for_alias_title_same_year(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Fixture Title - Variant (2017)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Fixture.Title.2017.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(
        nested_root,
        shadow_root,
        sync_enabled=True,
        auto_add_unmatched=True,
        auto_add_quality_profile_id=7,
    )
    config.runtime.arr_root_poll_interval_minutes = 1
    service = LibrariArrService(config)

    fake = FakeRadarr(
        movies=[
            {
                "id": 4,
                "title": "Fixture Title",
                "year": 2017,
                "path": "/old/path",
                "movieFile": {"id": 114},
                "monitored": True,
            }
        ],
        lookup_results=[{"title": "Fixture Title", "year": 2017, "tmdbId": 260514}],
        add_movie_result={
            "id": 4,
            "title": "Fixture Title",
            "year": 2017,
            "path": str(shadow_root / "Fixture Title (2017)"),
            "movieFile": {"id": 114},
            "monitored": True,
        },
    )
    service.radarr = fake

    service.reconcile()

    assert fake.lookup_terms == []
    assert fake.added_movies == []
    assert fake.updated_paths and fake.updated_paths[0][0] == 4
    assert (shadow_root / "Fixture Title (2017)").is_symlink()
    assert not (shadow_root / "Fixture Title - Variant (2017)").exists()


def test_reconcile_matches_existing_radarr_movie_by_tmdb_id_from_nfo(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Totally Custom Folder Name"
    movie_dir.mkdir(parents=True)
    (movie_dir / "movie.mkv").write_text("x", encoding="utf-8")
    (movie_dir / "movie.nfo").write_text(
        "<movie><title>Something Else</title><tmdbid>260514</tmdbid></movie>",
        encoding="utf-8",
    )

    config = make_config(
        nested_root,
        shadow_root,
        sync_enabled=True,
        auto_add_unmatched=True,
        auto_add_quality_profile_id=7,
    )
    service = LibrariArrService(config)

    fake = FakeRadarr(
        movies=[
            {
                "id": 44,
                "title": "Fixture Title",
                "year": 2017,
                "tmdbId": 260514,
                "path": "/old/path",
                "movieFile": {"id": 144},
                "monitored": True,
            }
        ],
        lookup_results=[{"title": "Fixture Title", "year": 2017, "tmdbId": 260514}],
        add_movie_result={
            "id": 44,
            "title": "Fixture Title",
            "year": 2017,
            "path": str(shadow_root / "Fixture Title (2017)"),
            "movieFile": {"id": 144},
            "monitored": True,
        },
    )
    service.radarr = fake

    service.reconcile()

    assert fake.lookup_terms == []
    assert fake.added_movies == []
    assert fake.updated_paths and fake.updated_paths[0][0] == 44
    assert (shadow_root / "Fixture Title (2017)").is_symlink()


def test_reconcile_auto_adds_unmatched_folder_with_canonical_link(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Fixture Title - Variant (2017)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Fixture.Title.2017.1080p.x265.mkv").write_text("x", encoding="utf-8")

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
        lookup_results=[{"title": "Fixture Title", "year": 2017, "tmdbId": 260514}],
        add_movie_result={
            "id": 10,
            "title": "Fixture Title",
            "year": 2017,
            "path": str(shadow_root / "Fixture Title (2017)"),
            "movieFile": {"id": 110},
            "monitored": True,
        },
    )
    service.radarr = fake

    service.reconcile()

    canonical_link = shadow_root / "Fixture Title (2017)"
    assert canonical_link.is_symlink()
    assert canonical_link.resolve(strict=False) == movie_dir
    assert not (shadow_root / "Fixture Title - Variant (2017)").exists()
    assert fake.lookup_terms == ["fixture title - variant 2017"]
    assert fake.added_movies and fake.added_movies[0]["quality_profile_id"] == 7
    assert fake.updated_paths == []
    assert fake.updated_qualities == [(10, 7)]
    assert fake.refreshed == [10]


def test_reconcile_skips_auto_add_when_radarr_root_is_missing(tmp_path: Path, caplog) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Fixture Title (2017)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Fixture.Title.2017.1080p.x265.mkv").write_text("x", encoding="utf-8")

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
        root_folders=[],
        lookup_results=[{"title": "Fixture Title", "year": 2017, "tmdbId": 260514}],
        add_movie_result={
            "id": 10,
            "title": "Fixture Title",
            "year": 2017,
            "path": str(shadow_root / "Fixture Title (2017)"),
            "movieFile": {"id": 110},
            "monitored": True,
        },
    )
    service.radarr = fake
    service._update_arr_root_folder_availability(force=True)

    caplog.set_level("DEBUG", logger="librariarr.service")
    service.reconcile()

    assert fake.lookup_terms == []
    assert fake.added_movies == []
    assert (shadow_root / "Fixture Title (2017)").is_symlink()
    assert "Skipping Radarr matching/sync for shadow root not configured in Radarr" in caplog.text
    assert "No Radarr match for folder after auto-add attempt" not in caplog.text


def test_reconcile_preserves_existing_radarr_link_when_root_is_missing(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Fixture Title - Variant (2017)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Fixture.Title.2017.1080p.x265.mkv").write_text("x", encoding="utf-8")

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
        root_folders=[],
        lookup_results=[{"title": "Fixture Title", "year": 2017, "tmdbId": 260514}],
    )
    service.radarr = fake
    service._update_arr_root_folder_availability(force=True)

    preserved_link = shadow_root / "Fixture Canonical (2017)"
    preserved_link.parent.mkdir(parents=True, exist_ok=True)
    preserved_link.symlink_to(movie_dir, target_is_directory=True)

    service.reconcile()

    assert preserved_link.is_symlink()
    assert not (shadow_root / "Fixture Title (2017)").exists()
    assert fake.lookup_terms == []


def test_poll_trigger_requests_reconcile_when_radarr_root_appears(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    config = make_config(
        nested_root,
        shadow_root,
        sync_enabled=True,
        auto_add_unmatched=True,
    )
    config.runtime.arr_root_poll_interval_minutes = 1
    service = LibrariArrService(config)

    fake = FakeRadarr(movies=[], root_folders=[])
    service.radarr = fake

    service._update_arr_root_folder_availability(force=True)
    assert service._radarr_missing_shadow_roots == {str(shadow_root)}

    fake.root_folders = [{"path": str(shadow_root)}]
    service._next_arr_root_poll_at = 0.0
    assert service._poll_arr_root_reconcile_trigger() is True
    assert service._radarr_missing_shadow_roots == set()

    service._next_arr_root_poll_at = 0.0
    assert service._poll_arr_root_reconcile_trigger() is False


def test_reconcile_reuses_existing_link_path_for_localized_folder_name(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Cap und Capper (1981) FSK0"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Cap.und.Capper.1981.1080p.h265.AC3.mkv").write_text("x", encoding="utf-8")

    config = make_config(
        nested_root,
        shadow_root,
        sync_enabled=True,
        auto_add_unmatched=True,
        auto_add_quality_profile_id=1,
    )
    service = LibrariArrService(config)

    canonical_link = shadow_root / "Fixture Canonical (1981)"
    fake = FakeRadarr(
        movies=[],
        lookup_results=[{"title": "Fixture Canonical", "year": 1981, "tmdbId": 10957}],
        add_movie_result={
            "id": 21,
            "title": "Fixture Canonical",
            "year": 1981,
            "path": str(canonical_link),
            "movieFile": {"id": 121},
            "monitored": True,
        },
    )
    service.radarr = fake

    service.reconcile()
    assert canonical_link.is_symlink()

    fake.movies = [
        {
            "id": 21,
            "title": "Fixture Canonical",
            "year": 1981,
            "path": str(canonical_link),
            "movieFile": {"id": 121},
            "monitored": True,
        }
    ]

    service.reconcile()

    assert len(fake.added_movies) == 1
    assert fake.updated_qualities == [(21, 7)]
    assert canonical_link.is_symlink()
    assert not (shadow_root / "Cap und Capper (1981)").exists()
