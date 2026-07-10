from __future__ import annotations

from requests import HTTPError

from librariarr.core.engine import SCOPE_FULL, ReconcileEngine

from .conftest import FakeRadarr, movie_payload, write_file


def make_engine(config, cache, radarr: FakeRadarr) -> ReconcileEngine:
    return ReconcileEngine(config, radarr=radarr, sonarr=None, cache=cache)


def test_unmatched_folder_is_reported_when_auto_add_disabled(config, cache, roots):
    write_file(roots["managed_movies"] / "kids" / "Unknown Movie (2019)" / "movie.mkv")
    radarr = FakeRadarr([])

    report = make_engine(config, cache, radarr).run(scope=SCOPE_FULL)

    assert len(report.unmatched) == 1
    entry = report.unmatched[0]
    assert entry.parsed_title == "Unknown Movie"
    assert entry.parsed_year == 2019
    assert entry.reason == "auto_add_disabled"


def test_unparseable_folder_is_reported(config, cache, roots):
    write_file(roots["managed_movies"] / "some-random-rip" / "movie.mkv")
    radarr = FakeRadarr([])

    report = make_engine(config, cache, radarr).run(scope=SCOPE_FULL)

    assert [u.reason for u in report.unmatched] == ["unparseable"]


def test_confident_match_is_auto_added_and_projected(config, cache, roots):
    config.radarr.auto_add_unmatched = True
    config.radarr.auto_add_quality_profile_id = 4
    managed = write_file(roots["managed_movies"] / "kids" / "New Movie (2021)" / "New.mkv")
    radarr = FakeRadarr([])
    radarr.lookup_results = [{"title": "New Movie", "year": 2021, "tmdbId": 42}]

    report = make_engine(config, cache, radarr).run(scope=SCOPE_FULL)

    assert len(radarr.added) == 1
    added = radarr.added[0]
    library_copy = roots["library_movies"] / "New Movie (2021)" / "New.mkv"
    assert library_copy.exists()
    assert library_copy.stat().st_ino == managed.stat().st_ino
    assert added["id"] in radarr.refreshed
    assert cache.get_folder("radarr", added["id"]) == managed.parent
    assert not report.unmatched


def test_ambiguous_lookup_is_reported_not_added(config, cache, roots):
    config.radarr.auto_add_unmatched = True
    config.radarr.auto_add_quality_profile_id = 4
    write_file(roots["managed_movies"] / "Twin (2020)" / "Twin.mkv")
    radarr = FakeRadarr([])
    radarr.lookup_results = [
        {"title": "Twin", "year": 2020, "tmdbId": 1},
        {"title": "Twin", "year": 2020, "tmdbId": 2},
    ]

    report = make_engine(config, cache, radarr).run(scope=SCOPE_FULL)

    assert not radarr.added
    assert [u.reason for u in report.unmatched] == ["ambiguous"]


def test_no_lookup_match_is_reported(config, cache, roots):
    config.radarr.auto_add_unmatched = True
    config.radarr.auto_add_quality_profile_id = 4
    write_file(roots["managed_movies"] / "Obscure (1971)" / "Obscure.mkv")
    radarr = FakeRadarr([])
    radarr.lookup_results = [{"title": "Different", "year": 1999}]

    report = make_engine(config, cache, radarr).run(scope=SCOPE_FULL)

    assert not radarr.added
    assert [u.reason for u in report.unmatched] == ["no_match"]


def test_auto_add_failure_is_reported_and_does_not_fail_reconcile(config, cache, roots):
    config.radarr.auto_add_unmatched = True
    config.radarr.auto_add_quality_profile_id = 4
    write_file(roots["managed_movies"] / "Bad Add (2022)" / "Bad.mkv")
    radarr = FakeRadarr([])
    radarr.lookup_results = [{"title": "Bad Add", "year": 2022, "tmdbId": 77}]

    def _fail_add(*_args, **_kwargs):
        raise HTTPError("400 Client Error: Bad Request for url: http://radarr:7878/api/v3/movie")

    radarr.add_movie_from_lookup = _fail_add

    report = make_engine(config, cache, radarr).run(scope=SCOPE_FULL)

    assert [u.reason for u in report.unmatched] == ["add_failed"]
    assert report.errors == []
    assert report.warnings
    assert "radarr auto-add failed" in report.warnings[0]


def test_fileless_arr_movie_is_adopted_by_matching_folder(config, cache, roots):
    managed = write_file(roots["managed_movies"] / "Adopt Me (2018)" / "Adopt.mkv")
    library_folder = roots["library_movies"] / "Adopt Me (2018)"
    radarr = FakeRadarr([movie_payload(5, "Adopt Me", 2018, library_folder, None)])

    report = make_engine(config, cache, radarr).run(scope=SCOPE_FULL)

    library_copy = library_folder / "Adopt.mkv"
    assert library_copy.exists()
    assert library_copy.stat().st_ino == managed.stat().st_ino
    assert 5 in radarr.refreshed
    assert cache.get_folder("radarr", 5) == managed.parent
    assert not report.unmatched
    assert any(a.kind == "adopt" for a in report.actions)


def test_matched_folders_are_not_reported_unmatched(config, cache, roots):
    from .conftest import hardlink

    managed = write_file(roots["managed_movies"] / "Known (2020)" / "Known.mkv")
    lib_file = hardlink(managed, roots["library_movies"] / "Known (2020)" / "Known.mkv")
    radarr = FakeRadarr([movie_payload(1, "Known", 2020, lib_file.parent, lib_file)])

    report = make_engine(config, cache, radarr).run(scope=SCOPE_FULL)

    assert not report.unmatched


def test_sample_files_do_not_create_candidates(config, cache, roots):
    write_file(roots["managed_movies"] / "Extras Only (2000)" / "movie-sample.mkv")
    radarr = FakeRadarr([])

    report = make_engine(config, cache, radarr).run(scope=SCOPE_FULL)

    assert not report.unmatched


def test_trash_dir_is_never_discovered(config, cache, roots):
    write_file(roots["managed_movies"] / ".deletedByLibrariarr" / "Old (1990)" / "Old.mkv")
    radarr = FakeRadarr([])

    report = make_engine(config, cache, radarr).run(scope=SCOPE_FULL)

    assert not report.unmatched
