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


def test_existing_movie_with_lost_file_is_adopted_and_self_heals(config, cache, roots):
    """Radarr still records a file, but it is gone on disk and the cache lost the
    managed association (the production add_failed loop): the folder must be
    adopted instead of auto-added, and the next pass restores the library file."""
    config.radarr.auto_add_unmatched = True
    config.radarr.auto_add_quality_profile_id = 4
    managed = write_file(roots["managed_movies"] / "Lady Bird (2017)" / "Lady.Bird.mkv")
    lib_folder = roots["library_movies"] / "Lady Bird (2017)"
    lib_file = lib_folder / "Lady.Bird.old.mkv"  # recorded in Radarr, gone on disk
    radarr = FakeRadarr([movie_payload(6, "Lady Bird", 2017, lib_folder, lib_file)])
    engine = make_engine(config, cache, radarr)

    report = engine.run(scope=SCOPE_FULL)

    assert not radarr.added, "must not attempt a doomed auto-add"
    assert cache.get_folder("radarr", 6) == managed.parent
    assert any(a.kind == "adopt" for a in report.actions)
    assert not report.unmatched

    second = engine.run(scope=SCOPE_FULL)
    assert lib_file.exists()
    assert lib_file.stat().st_ino == managed.stat().st_ino
    assert any(a.kind == "relink" for a in second.actions)


def test_second_folder_for_synced_movie_is_reported_as_duplicate(config, cache, roots):
    from .conftest import hardlink

    config.radarr.auto_add_unmatched = True
    config.radarr.auto_add_quality_profile_id = 4
    managed_a = write_file(roots["managed_movies"] / "kids" / "Twice (1994)" / "Twice.mkv")
    lib_file = hardlink(managed_a, roots["library_movies"] / "Twice (1994)" / "Twice.mkv")
    write_file(roots["managed_movies"] / "adults" / "Twice (1994)" / "Twice.other.mkv")
    radarr = FakeRadarr([movie_payload(7, "Twice", 1994, lib_file.parent, lib_file)])

    report = make_engine(config, cache, radarr).run(scope=SCOPE_FULL)

    assert not radarr.added
    assert [u.reason for u in report.unmatched] == ["duplicate"]
    assert cache.get_folder("radarr", 7) == managed_a.parent, "sync association must not move"


def test_existing_movie_outside_library_roots_is_reported(config, cache, roots, tmp_path):
    config.radarr.auto_add_unmatched = True
    config.radarr.auto_add_quality_profile_id = 4
    write_file(roots["managed_movies"] / "Elsewhere (2005)" / "Elsewhere.mkv")
    foreign_folder = tmp_path / "old-root" / "Elsewhere (2005)"
    foreign_file = write_file(foreign_folder / "Elsewhere.mkv")
    radarr = FakeRadarr([movie_payload(8, "Elsewhere", 2005, foreign_folder, foreign_file)])

    report = make_engine(config, cache, radarr).run(scope=SCOPE_FULL)

    assert not radarr.added
    assert [u.reason for u in report.unmatched] == ["already_in_arr"]
    assert "move its root folder" in report.unmatched[0].candidates[0]


def test_auto_add_is_skipped_when_tmdb_id_already_in_radarr(config, cache, roots, tmp_path):
    config.radarr.auto_add_unmatched = True
    config.radarr.auto_add_quality_profile_id = 4
    write_file(roots["managed_movies"] / "Retitled (2012)" / "Retitled.mkv")
    foreign_folder = tmp_path / "old-root" / "Original Title (2012)"
    foreign_file = write_file(foreign_folder / "Original.mkv")
    existing = movie_payload(9, "Original Title", 2012, foreign_folder, foreign_file)
    existing["tmdbId"] = 555
    radarr = FakeRadarr([existing])
    radarr.lookup_results = [{"title": "Retitled", "year": 2012, "tmdbId": 555}]

    report = make_engine(config, cache, radarr).run(scope=SCOPE_FULL)

    assert not radarr.added, "adding an already-present tmdbId would 400 forever"
    assert [u.reason for u in report.unmatched] == ["already_in_arr"]


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
