from pathlib import Path

from librariarr.sync.radarr_mapping import (
    extract_parse_custom_format_ids,
    extract_parse_quality_definition_id,
    format_id_name_pairs,
    parse_candidates_for_folder,
    pick_lookup_candidate,
)


def test_extract_parse_custom_format_ids_reads_ids() -> None:
    parse_result = {
        "customFormats": [
            {"id": 42, "name": "German"},
            {"id": 99, "name": "4K HEVC"},
        ]
    }

    assert extract_parse_custom_format_ids(parse_result) == {42, 99}


def test_extract_parse_quality_definition_id_reads_quality_shape() -> None:
    parse_result = {
        "quality": {
            "quality": {"id": 7, "name": "Bluray-1080p"},
        }
    }

    assert extract_parse_quality_definition_id(parse_result) == 7


def test_extract_parse_quality_definition_id_reads_parsed_movie_info_shape() -> None:
    parse_result = {
        "parsedMovieInfo": {
            "qualityDefinition": {"id": 19, "name": "Bluray-2160p"},
        }
    }

    assert extract_parse_quality_definition_id(parse_result) == 19


def test_format_id_name_pairs_handles_quality_and_plain_shapes() -> None:
    items = [
        {"quality": {"id": 7, "name": "Bluray-1080p"}},
        {"id": 42, "name": "German"},
    ]

    assert format_id_name_pairs(items) == "7:Bluray-1080p, 42:German"


def test_parse_candidates_for_folder_uses_name_then_first_video(tmp_path: Path) -> None:
    folder = tmp_path / "Fixture Title - Variant (2017)"
    folder.mkdir()
    (folder / "notes.txt").write_text("x", encoding="utf-8")
    (folder / "Fixture.Title.2017.1080p.x265.mkv").write_text("x", encoding="utf-8")

    candidates = parse_candidates_for_folder(folder, {".mkv"})

    assert candidates[0] == "Fixture Title - Variant (2017)"
    assert "Fixture.Title.2017.1080p.x265" in candidates
    assert "Fixture.Title.2017.1080p.x265.mkv" in candidates


def test_pick_lookup_candidate_prefers_year_and_best_title_match(tmp_path: Path) -> None:
    folder = tmp_path / "Fixture Title - Variant (2017)"
    folder.mkdir()

    candidates = [
        {"title": "Fixture Title", "year": 2017, "tmdbId": 1},
        {"title": "Fixture", "year": 2017, "tmdbId": 2},
        {"title": "Fixture Title", "year": 2018, "tmdbId": 3},
    ]

    selected = pick_lookup_candidate(folder, candidates)

    assert selected is not None
    assert selected.get("tmdbId") == 1


def test_pick_lookup_candidate_fallback_matches_localized_articles(tmp_path: Path) -> None:
    folder = tmp_path / "Die Simpsons"
    folder.mkdir()

    candidates = [
        {"title": "The Simpsons", "tmdbId": 1},
        {"title": "Simpsons Shorts", "tmdbId": 2},
    ]

    selected = pick_lookup_candidate(folder, candidates)

    assert selected is not None
    assert selected.get("tmdbId") == 1


def test_pick_lookup_candidate_considers_alternate_titles(tmp_path: Path) -> None:
    folder = tmp_path / "Die Simpsons"
    folder.mkdir()

    candidates = [
        {
            "title": "The Simpsons",
            "alternateTitles": [{"title": "Die Simpsons"}],
            "tmdbId": 1,
        },
        {
            "title": "Totally Different Show",
            "tmdbId": 2,
        },
    ]

    selected = pick_lookup_candidate(folder, candidates)

    assert selected is not None
    assert selected.get("tmdbId") == 1
