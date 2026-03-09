from librariarr.sync.naming import (
    MovieRef,
    canonical_name_from_folder,
    extract_title_year,
    parse_movie_ref,
)


def test_extract_title_year_parses_with_suffix() -> None:
    parsed = extract_title_year("Sing (2016) FSK0")

    assert parsed == ("Sing", 2016)


def test_extract_title_year_returns_none_for_non_matching_name() -> None:
    assert extract_title_year("NoYearTitle") is None


def test_canonical_name_from_folder_normalizes_year_suffix() -> None:
    assert canonical_name_from_folder("Sing (2016) FSK0") == "Sing (2016)"


def test_parse_movie_ref_normalizes_case_and_year() -> None:
    assert parse_movie_ref("SING (2016)") == MovieRef(title="sing", year=2016)
    assert parse_movie_ref("Unknown Title") == MovieRef(title="unknown title", year=None)
