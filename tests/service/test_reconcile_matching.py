from pathlib import Path

from librariarr.config import (
    CustomFormatRule,
)
from librariarr.service import LibrariArrService
from tests.service.helpers import FakeRadarr, make_config


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
    config.radarr.mapping.quality_map = []
    config.analysis.use_nfo = True
    config.radarr.mapping.custom_format_map = [CustomFormatRule(match=["german"], format_id=42)]
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
    config.radarr.mapping.quality_map = []
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
