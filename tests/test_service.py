from pathlib import Path

import requests

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    CustomFormatRule,
    IngestConfig,
    PathsConfig,
    QualityRule,
    RadarrConfig,
    RootMapping,
    RuntimeConfig,
)
from librariarr.service import LibrariArrService


class FakeRadarr:
    def __init__(
        self,
        movies: list[dict] | None = None,
        system_status: dict | None = None,
        system_status_error: Exception | None = None,
        quality_profiles: list[dict] | None = None,
        quality_definitions: list[dict] | None = None,
        custom_formats: list[dict] | None = None,
        parse_results: dict[str, dict] | None = None,
        lookup_results: list[dict] | None = None,
        add_movie_result: dict | None = None,
    ) -> None:
        self.movies = movies or []
        self.system_status = system_status or {"appName": "Radarr", "version": "0.0.0-test"}
        self.system_status_error = system_status_error
        self.quality_profiles = quality_profiles or []
        self.quality_definitions = quality_definitions or []
        self.custom_formats = custom_formats or []
        self.parse_results = parse_results or {}
        self.lookup_results = lookup_results or []
        self.add_movie_result = add_movie_result or {}
        self.updated_paths: list[tuple[int, str]] = []
        self.updated_qualities: list[tuple[int, int]] = []
        self.refreshed: list[int] = []
        self.unmonitored: list[int] = []
        self.deleted: list[int] = []
        self.lookup_terms: list[str] = []
        self.parse_titles: list[str] = []
        self.added_movies: list[dict] = []
        self.get_movies_calls = 0
        self.get_system_status_calls = 0
        self.get_quality_profiles_calls = 0
        self.get_quality_definitions_calls = 0
        self.get_custom_formats_calls = 0

    def get_movies(self) -> list[dict]:
        self.get_movies_calls += 1
        return self.movies

    def get_system_status(self) -> dict:
        self.get_system_status_calls += 1
        if self.system_status_error is not None:
            raise self.system_status_error
        return self.system_status

    def get_quality_profiles(self) -> list[dict]:
        self.get_quality_profiles_calls += 1
        return self.quality_profiles

    def get_quality_definitions(self) -> list[dict]:
        self.get_quality_definitions_calls += 1
        return self.quality_definitions

    def get_custom_formats(self) -> list[dict]:
        self.get_custom_formats_calls += 1
        return self.custom_formats

    def lookup_movies(self, term: str) -> list[dict]:
        self.lookup_terms.append(term)
        return self.lookup_results

    def parse_title(self, title: str) -> dict:
        self.parse_titles.append(title)
        return self.parse_results.get(title, {})

    def add_movie_from_lookup(
        self,
        lookup_movie: dict,
        path: str,
        root_folder_path: str,
        quality_profile_id: int,
        monitored: bool,
        search_for_movie: bool,
    ) -> dict:
        self.added_movies.append(
            {
                "lookup_movie": lookup_movie,
                "path": path,
                "root_folder_path": root_folder_path,
                "quality_profile_id": quality_profile_id,
                "monitored": monitored,
                "search_for_movie": search_for_movie,
            }
        )
        return self.add_movie_result

    def update_movie_path(self, movie: dict, new_path: str) -> None:
        self.updated_paths.append((int(movie["id"]), new_path))

    def try_update_moviefile_quality(self, movie: dict, quality_id: int) -> None:
        self.updated_qualities.append((int(movie["id"]), quality_id))

    def refresh_movie(self, movie_id: int) -> None:
        self.refreshed.append(movie_id)

    def unmonitor_movie(self, movie: dict) -> None:
        self.unmonitored.append(int(movie["id"]))

    def delete_movie(
        self,
        movie_id: int,
        delete_files: bool = False,
        add_import_exclusion: bool = False,
    ) -> None:
        del delete_files
        del add_import_exclusion
        self.deleted.append(movie_id)


def make_config(
    nested_root: Path,
    shadow_root: Path,
    sync_enabled: bool = True,
    delete_from_radarr_on_missing: bool = False,
    auto_add_unmatched: bool = False,
    auto_add_quality_profile_id: int | None = None,
) -> AppConfig:
    return AppConfig(
        paths=PathsConfig(
            root_mappings=[RootMapping(nested_root=str(nested_root), shadow_root=str(shadow_root))]
        ),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            sync_enabled=sync_enabled,
            auto_add_unmatched=auto_add_unmatched,
            auto_add_quality_profile_id=auto_add_quality_profile_id,
        ),
        quality_map=[QualityRule(match=["1080p", "x265"], target_id=7, name="Bluray-1080p")],
        cleanup=CleanupConfig(
            remove_orphaned_links=True,
            unmonitor_on_delete=True,
            delete_from_radarr_on_missing=delete_from_radarr_on_missing,
        ),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )


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
    assert fake.updated_qualities == [(1, 7)]
    assert fake.refreshed == [1]


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
    assert fake.updated_paths == [(10, str(canonical_link))]


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

    # Emulate Radarr state after a successful add so the next reconcile sees the movie.
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
    assert canonical_link.is_symlink()
    assert not (shadow_root / "Cap und Capper (1981)").exists()


def test_reconcile_auto_add_uses_mapped_profile_when_not_configured(tmp_path: Path) -> None:
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
    )
    service = LibrariArrService(config)

    fake = FakeRadarr(
        movies=[],
        quality_profiles=[
            {
                "id": 3,
                "name": "HD-720p",
                "items": [{"quality": {"id": 4, "name": "HDTV-1080p"}}],
            },
            {
                "id": 7,
                "name": "1080p x265",
                "items": [{"quality": {"id": 7, "name": "Bluray-1080p"}}],
            },
        ],
        lookup_results=[{"title": "Fixture Title", "year": 2017, "tmdbId": 260514}],
        add_movie_result={
            "id": 11,
            "title": "Fixture Title",
            "year": 2017,
            "path": str(shadow_root / "Fixture Title (2017)"),
            "movieFile": {"id": 111},
            "monitored": True,
        },
    )
    service.radarr = fake

    service.reconcile()

    assert fake.added_movies and fake.added_movies[0]["quality_profile_id"] == 7


def test_reconcile_auto_add_uses_custom_format_map_when_parse_is_empty(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Fixture Title - Variant (2017)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Fixture.Title.2017.1080p.x265.german.mkv").write_text("x", encoding="utf-8")
    (movie_dir / "movie.nfo").write_text("language: german", encoding="utf-8")

    config = make_config(
        nested_root,
        shadow_root,
        sync_enabled=True,
        auto_add_unmatched=True,
    )
    config.quality_map = []
    config.analysis.use_nfo = True
    config.custom_format_map = [
        CustomFormatRule(match=["german"], format_id=42, name="German Audio")
    ]
    service = LibrariArrService(config)

    fake = FakeRadarr(
        movies=[],
        quality_profiles=[
            {
                "id": 1,
                "name": "Any",
                "formatItems": [
                    {"format": 42, "name": "German Audio", "score": 10},
                ],
            },
            {
                "id": 7,
                "name": "German HEVC",
                "formatItems": [
                    {"format": 42, "name": "German Audio", "score": 100},
                ],
            },
        ],
        parse_results={
            # Simulate Radarr parse not yielding useful custom format matches.
            "Fixture Title - Variant (2017)": {"customFormats": []},
        },
        lookup_results=[{"title": "Fixture Title", "year": 2017, "tmdbId": 260514}],
        add_movie_result={
            "id": 17,
            "title": "Fixture Title",
            "year": 2017,
            "path": str(shadow_root / "Fixture Title (2017)"),
            "movieFile": {"id": 117},
            "monitored": True,
        },
    )
    service.radarr = fake

    service.reconcile()

    assert fake.added_movies and fake.added_movies[0]["quality_profile_id"] == 7


def test_reconcile_auto_add_uses_parse_custom_formats_without_quality_map(tmp_path: Path) -> None:
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
    )
    config.quality_map = []
    service = LibrariArrService(config)

    fake = FakeRadarr(
        movies=[],
        quality_profiles=[
            {
                "id": 1,
                "name": "Any",
                "formatItems": [
                    {"format": 99, "name": "Preferred Release", "score": 10},
                ],
            },
            {
                "id": 8,
                "name": "Specific Preferred",
                "formatItems": [
                    {"format": 99, "name": "Preferred Release", "score": 100},
                ],
            },
        ],
        parse_results={
            "Fixture Title - Variant (2017)": {
                "customFormats": [{"id": 99, "name": "Preferred Release"}],
            }
        },
        lookup_results=[{"title": "Fixture Title", "year": 2017, "tmdbId": 260514}],
        add_movie_result={
            "id": 18,
            "title": "Fixture Title",
            "year": 2017,
            "path": str(shadow_root / "Fixture Title (2017)"),
            "movieFile": {"id": 118},
            "monitored": True,
        },
    )
    service.radarr = fake

    service.reconcile()

    assert fake.added_movies and fake.added_movies[0]["quality_profile_id"] == 8


def test_reconcile_auto_add_prefers_cutoff_exact_profile(tmp_path: Path) -> None:
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
    )
    service = LibrariArrService(config)

    fake = FakeRadarr(
        movies=[],
        quality_profiles=[
            {
                "id": 2,
                "name": "Broad 1080p",
                "cutoff": {"id": 6, "name": "Web-DL 1080p"},
                "items": [{"quality": {"id": 7, "name": "Bluray-1080p"}}],
            },
            {
                "id": 9,
                "name": "Exact 1080p",
                "cutoff": {"id": 7, "name": "Bluray-1080p"},
                "items": [{"quality": {"id": 7, "name": "Bluray-1080p"}}],
            },
        ],
        quality_definitions=[
            {"id": 6, "name": "Web-DL 1080p"},
            {"id": 7, "name": "Bluray-1080p"},
        ],
        lookup_results=[{"title": "Fixture Title", "year": 2017, "tmdbId": 260514}],
        add_movie_result={
            "id": 111,
            "title": "Fixture Title",
            "year": 2017,
            "path": str(shadow_root / "Fixture Title (2017)"),
            "movieFile": {"id": 211},
            "monitored": True,
        },
    )
    service.radarr = fake

    service.reconcile()

    assert fake.added_movies and fake.added_movies[0]["quality_profile_id"] == 9


def test_reconcile_auto_add_prefers_specific_profile_over_any(tmp_path: Path) -> None:
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
    )
    service = LibrariArrService(config)

    fake = FakeRadarr(
        movies=[],
        quality_profiles=[
            {
                "id": 1,
                "name": "Any",
                "cutoff": {"id": 7, "name": "Bluray-1080p"},
                "items": [
                    {"quality": {"id": 4, "name": "HDTV-1080p"}},
                    {"quality": {"id": 7, "name": "Bluray-1080p"}},
                    {"quality": {"id": 19, "name": "Bluray-2160p"}},
                ],
            },
            {
                "id": 7,
                "name": "1080p German x265",
                "cutoff": {"id": 7, "name": "Bluray-1080p"},
                "items": [
                    {"quality": {"id": 7, "name": "Bluray-1080p"}},
                ],
            },
        ],
        quality_definitions=[
            {"id": 4, "name": "HDTV-1080p"},
            {"id": 7, "name": "Bluray-1080p"},
            {"id": 19, "name": "Bluray-2160p"},
        ],
        lookup_results=[{"title": "Fixture Title", "year": 2017, "tmdbId": 260514}],
        add_movie_result={
            "id": 114,
            "title": "Fixture Title",
            "year": 2017,
            "path": str(shadow_root / "Fixture Title (2017)"),
            "movieFile": {"id": 214},
            "monitored": True,
        },
    )
    service.radarr = fake

    service.reconcile()

    assert fake.added_movies and fake.added_movies[0]["quality_profile_id"] == 7


def test_reconcile_auto_add_skips_disallowed_profile_items(tmp_path: Path) -> None:
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
    )
    service = LibrariArrService(config)

    fake = FakeRadarr(
        movies=[],
        quality_profiles=[
            {
                "id": 1,
                "name": "Disallowed 1080p",
                "cutoff": {"id": 7, "name": "Bluray-1080p"},
                "items": [
                    {
                        "quality": {"id": 7, "name": "Bluray-1080p"},
                        "allowed": False,
                    }
                ],
            },
            {
                "id": 8,
                "name": "Allowed 1080p",
                "cutoff": {"id": 6, "name": "Web-DL 1080p"},
                "items": [{"quality": {"id": 7, "name": "Bluray-1080p"}}],
            },
        ],
        quality_definitions=[
            {"id": 6, "name": "Web-DL 1080p"},
            {"id": 7, "name": "Bluray-1080p"},
        ],
        lookup_results=[{"title": "Fixture Title", "year": 2017, "tmdbId": 260514}],
        add_movie_result={
            "id": 112,
            "title": "Fixture Title",
            "year": 2017,
            "path": str(shadow_root / "Fixture Title (2017)"),
            "movieFile": {"id": 212},
            "monitored": True,
        },
    )
    service.radarr = fake

    service.reconcile()

    assert fake.added_movies and fake.added_movies[0]["quality_profile_id"] == 8


def test_reconcile_auto_add_prefers_higher_nearest_cutoff(tmp_path: Path) -> None:
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
    )
    service = LibrariArrService(config)

    fake = FakeRadarr(
        movies=[],
        quality_profiles=[
            {
                "id": 4,
                "name": "Below cutoff",
                "cutoff": {"id": 6, "name": "Web-DL 1080p"},
                "items": [{"quality": {"id": 7, "name": "Bluray-1080p"}}],
            },
            {
                "id": 5,
                "name": "Above cutoff",
                "cutoff": {"id": 8, "name": "Bluray-1080p Remux"},
                "items": [{"quality": {"id": 7, "name": "Bluray-1080p"}}],
            },
        ],
        quality_definitions=[
            {"id": 6, "name": "Web-DL 1080p"},
            {"id": 7, "name": "Bluray-1080p"},
            {"id": 8, "name": "Bluray-1080p Remux"},
        ],
        lookup_results=[{"title": "Fixture Title", "year": 2017, "tmdbId": 260514}],
        add_movie_result={
            "id": 113,
            "title": "Fixture Title",
            "year": 2017,
            "path": str(shadow_root / "Fixture Title (2017)"),
            "movieFile": {"id": 213},
            "monitored": True,
        },
    )
    service.radarr = fake

    service.reconcile()

    assert fake.added_movies and fake.added_movies[0]["quality_profile_id"] == 5


def test_reconcile_auto_add_falls_back_to_lowest_profile_when_unmapped(tmp_path: Path) -> None:
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
    )
    service = LibrariArrService(config)

    fake = FakeRadarr(
        movies=[],
        quality_profiles=[
            {
                "id": 3,
                "name": "HD-720p",
                "items": [{"quality": {"id": 4, "name": "HDTV-1080p"}}],
            },
            {
                "id": 7,
                "name": "1080p x265",
                "items": [{"quality": {"id": 6, "name": "Web-DL 1080p"}}],
            },
        ],
        lookup_results=[{"title": "Fixture Title", "year": 2017, "tmdbId": 260514}],
        add_movie_result={
            "id": 12,
            "title": "Fixture Title",
            "year": 2017,
            "path": str(shadow_root / "Fixture Title (2017)"),
            "movieFile": {"id": 112},
            "monitored": True,
        },
    )
    service.radarr = fake

    service.reconcile()

    assert fake.added_movies and fake.added_movies[0]["quality_profile_id"] == 3


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
        ),
        quality_map=[QualityRule(match=["1080p", "x265"], target_id=7, name="Bluray-1080p")],
        cleanup=CleanupConfig(remove_orphaned_links=True, unmonitor_on_delete=True),
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
        delete_from_radarr_on_missing=True,
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
        ),
        quality_map=[QualityRule(match=["1080p", "x265"], target_id=7, name="Bluray-1080p")],
        cleanup=CleanupConfig(remove_orphaned_links=True, unmonitor_on_delete=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )

    service = LibrariArrService(config)
    service.reconcile()

    assert (age12_shadow / "Movie A (2020)").is_symlink()
    assert not (age16_shadow / "Movie A (2020)").exists()
    assert (age16_shadow / "Movie B (2021)").is_symlink()
    assert not (age12_shadow / "Movie B (2021)").exists()


def test_reconcile_uses_canonical_radarr_name_for_link(tmp_path: Path) -> None:
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

    canonical_link = shadow_root / "Fixture Legacy (1977)"
    assert canonical_link.is_symlink()
    assert not (shadow_root / "Fixture Legacy").exists()


def test_reconcile_skips_quality_update_when_quality_map_empty(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Fixture Catalog A (2008)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Big.Buck.Bunny.2008.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    config.quality_map = []
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


def test_reconcile_replaces_stale_non_canonical_link(tmp_path: Path) -> None:
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

    canonical_link = shadow_root / "Fixture Legacy (1977)"
    assert canonical_link.is_symlink()
    assert not stale_link.exists()


def test_service_disables_periodic_maintenance_when_configured(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = AppConfig(
        paths=PathsConfig(
            root_mappings=[RootMapping(nested_root=str(nested_root), shadow_root=str(shadow_root))]
        ),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            sync_enabled=False,
        ),
        quality_map=[QualityRule(match=["1080p", "x265"], target_id=7, name="Bluray-1080p")],
        cleanup=CleanupConfig(remove_orphaned_links=True, unmonitor_on_delete=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=0),
    )

    service = LibrariArrService(config)

    assert service._maintenance_interval is None


def test_sync_hint_logs_actionable_message_for_unauthorized_radarr(
    tmp_path: Path,
    caplog,
) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    service = LibrariArrService(config)

    response = requests.Response()
    response.status_code = 401
    response.url = "http://radarr:7878/api/v3/movie"
    err = requests.HTTPError("401 Client Error: Unauthorized", response=response)

    caplog.set_level("ERROR", logger="librariarr.service")
    service._log_sync_config_hint(err)

    assert "Radarr API auth failed while sync is enabled" in caplog.text
    assert "set radarr.sync_enabled=false for filesystem-only mode" in caplog.text

    caplog.clear()
    service._log_sync_config_hint(err)
    assert caplog.text == ""


def test_sync_hint_logs_url_for_connection_errors(tmp_path: Path, caplog) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    service = LibrariArrService(config)

    err = requests.ConnectionError("connection refused")

    caplog.set_level("WARNING", logger="librariarr.service")
    service._log_sync_config_hint(err)

    assert "Radarr is unreachable while sync is enabled" in caplog.text
    assert "url=http://radarr:7878" in caplog.text


def test_sync_preflight_warns_for_empty_api_key(tmp_path: Path, caplog) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    config.radarr.api_key = ""
    service = LibrariArrService(config)
    service.radarr = FakeRadarr()

    caplog.set_level("WARNING", logger="librariarr.service")
    service._run_sync_preflight_checks()

    assert "radarr.api_key is empty" in caplog.text


def test_sync_preflight_logs_failure_details_when_status_probe_fails(
    tmp_path: Path,
    caplog,
) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(system_status_error=requests.ConnectionError("refused"))

    caplog.set_level("WARNING", logger="librariarr.service")
    service._run_sync_preflight_checks()

    assert "Radarr preflight check failed" in caplog.text
    assert "error=refused" in caplog.text


def test_sync_preflight_logs_quality_catalog_and_validation(tmp_path: Path, caplog) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    config.quality_map = [
        QualityRule(match=["1080p"], target_id=4, name="HDTV-1080p"),
        QualityRule(match=["2160p"], target_id=13, name="4K"),
    ]
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        quality_profiles=[{"id": 6, "name": "Web-DL 1080p"}],
        quality_definitions=[{"id": 4, "name": "HDTV-1080p"}, {"id": 13, "name": "Bluray-2160p"}],
    )

    caplog.set_level("INFO", logger="librariarr.service")
    service._run_sync_preflight_checks()

    assert "Radarr quality profiles (id:name): 6:Web-DL 1080p" in caplog.text
    assert "Radarr quality definitions (id:name): 4:HDTV-1080p, 13:Bluray-2160p" in caplog.text
    assert "quality_map target_id values validated" in caplog.text


def test_sync_preflight_warns_when_quality_target_id_missing(tmp_path: Path, caplog) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    config.quality_map = [QualityRule(match=["2160p"], target_id=99, name="Missing")]
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(quality_definitions=[{"id": 4, "name": "HDTV-1080p"}])

    caplog.set_level("WARNING", logger="librariarr.service")
    service._run_sync_preflight_checks()

    assert "quality_map target_id values not found" in caplog.text
    assert "missing_ids=[99]" in caplog.text


def test_sync_preflight_parses_nested_quality_definition_shape(tmp_path: Path, caplog) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    config.quality_map = [QualityRule(match=["1080p"], target_id=4, name="HDTV-1080p")]
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        quality_definitions=[
            {"id": 901, "quality": {"id": 4, "name": "HDTV-1080p"}},
            {"id": 902, "quality": {"id": 13, "name": "Bluray-2160p"}},
        ]
    )

    caplog.set_level("INFO", logger="librariarr.service")
    service._run_sync_preflight_checks()

    assert "Radarr quality definitions (id:name): 4:HDTV-1080p, 13:Bluray-2160p" in caplog.text
    assert "quality_map target_id values validated" in caplog.text


def test_sync_preflight_logs_custom_format_catalog_and_validation(tmp_path: Path, caplog) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    config.custom_format_map = [
        CustomFormatRule(match=["german"], format_id=42, name="German Audio"),
        CustomFormatRule(match=["x265"], format_id=99, name="HEVC"),
    ]
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        custom_formats=[
            {"id": 42, "name": "German Audio"},
            {"id": 99, "name": "HEVC"},
        ]
    )

    caplog.set_level("INFO", logger="librariarr.service")
    service._run_sync_preflight_checks()

    assert (
        "custom_format_map contains format ids for local analysis fallback: [42, 99]" in caplog.text
    )
    assert "Radarr custom formats (id:name): 42:German Audio, 99:HEVC" in caplog.text
    assert "custom_format_map format_id values validated" in caplog.text


def test_sync_preflight_warns_when_custom_format_id_missing(tmp_path: Path, caplog) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    config.custom_format_map = [CustomFormatRule(match=["german"], format_id=999, name="Missing")]
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(custom_formats=[{"id": 42, "name": "German Audio"}])

    caplog.set_level("WARNING", logger="librariarr.service")
    service._run_sync_preflight_checks()

    assert "custom_format_map format_id values not found" in caplog.text
    assert "missing_ids=[999]" in caplog.text


def test_ingest_moves_real_shadow_folder_to_nested_and_replaces_symlink(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    incoming = shadow_root / "Incoming Movie (2024)"
    incoming.mkdir(parents=True)
    (incoming / "Incoming.Movie.2024.1080p.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=False)
    config.ingest = IngestConfig(enabled=True, min_age_seconds=0)
    service = LibrariArrService(config)

    service.reconcile()

    destination = nested_root / "Incoming Movie (2024)"
    shadow_link = shadow_root / "Incoming Movie (2024)"
    assert destination.exists()
    assert shadow_link.is_symlink()
    assert shadow_link.resolve(strict=False) == destination

    # Second run should be a no-op for this already-ingested path.
    service.reconcile()
    assert shadow_link.is_symlink()
    assert shadow_link.resolve(strict=False) == destination


def test_ingest_collision_skip_policy_leaves_source_untouched(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"

    existing = nested_root / "Collision Movie (2024)"
    existing.mkdir(parents=True)
    (existing / "Collision.Movie.2024.1080p.mkv").write_text("x", encoding="utf-8")

    incoming = shadow_root / "Collision Movie (2024)"
    incoming.mkdir(parents=True)
    (incoming / "Collision.Movie.2024.2160p.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=False)
    config.ingest = IngestConfig(enabled=True, min_age_seconds=0, collision_policy="skip")
    service = LibrariArrService(config)

    service.reconcile()

    assert incoming.exists()
    assert incoming.is_dir()
    assert not incoming.is_symlink()


def test_ingest_collision_qualify_policy_uses_suffix(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"

    existing = nested_root / "Collision Movie (2024)"
    existing.mkdir(parents=True)
    (existing / "existing.mkv").write_text("x", encoding="utf-8")

    incoming = shadow_root / "Collision Movie (2024)"
    incoming.mkdir(parents=True)
    (incoming / "incoming.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=False)
    config.ingest = IngestConfig(enabled=True, min_age_seconds=0, collision_policy="qualify")
    service = LibrariArrService(config)

    service.reconcile()

    qualified_destination = nested_root / "Collision Movie (2024) [ingest-2]"
    shadow_link = shadow_root / "Collision Movie (2024)"
    assert qualified_destination.exists()
    assert shadow_link.is_symlink()
    assert shadow_link.resolve(strict=False) == qualified_destination


def test_ingest_requires_one_to_one_shadow_root_mappings(tmp_path: Path) -> None:
    shadow_root = tmp_path / "radarr_library"
    nested_a = tmp_path / "nested_a"
    nested_b = tmp_path / "nested_b"

    config = AppConfig(
        paths=PathsConfig(
            root_mappings=[
                RootMapping(nested_root=str(nested_a), shadow_root=str(shadow_root)),
                RootMapping(nested_root=str(nested_b), shadow_root=str(shadow_root)),
            ]
        ),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            sync_enabled=False,
        ),
        quality_map=[QualityRule(match=["1080p", "x265"], target_id=7, name="Bluray-1080p")],
        cleanup=CleanupConfig(remove_orphaned_links=True, unmonitor_on_delete=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
        ingest=IngestConfig(enabled=True, min_age_seconds=0),
    )

    try:
        LibrariArrService(config)
    except ValueError as exc:
        assert "Ingest requires a 1:1 mapping" in str(exc)
    else:
        raise AssertionError("Expected ValueError for ambiguous ingest root mappings")
