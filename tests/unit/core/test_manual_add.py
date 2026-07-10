from __future__ import annotations

from librariarr.core.engine import ReconcileEngine

from .conftest import FakeRadarr, FakeSonarr, write_file


def make_engine(config, cache, radarr=None, sonarr=None) -> ReconcileEngine:
    return ReconcileEngine(config, radarr=radarr, sonarr=sonarr, cache=cache)


def test_manual_add_bypasses_auto_add_flag(config, cache, roots):
    assert config.radarr.auto_add_unmatched is False
    config.radarr.auto_add_quality_profile_id = 4
    managed = write_file(roots["managed_movies"] / "Manual (2021)" / "Manual.mkv")
    radarr = FakeRadarr([])
    radarr.lookup_results = [{"title": "Manual", "year": 2021, "tmdbId": 42}]
    engine = make_engine(config, cache, radarr=radarr)

    result = engine.manual_add(str(managed.parent))

    assert result["ok"] is True, result
    assert len(radarr.added) == 1
    assert radarr.added[0]["id"] in radarr.refreshed


def test_manual_add_reports_ambiguous_with_candidates(config, cache, roots):
    config.radarr.auto_add_quality_profile_id = 4
    managed = write_file(roots["managed_movies"] / "Twin (2020)" / "Twin.mkv")
    radarr = FakeRadarr([])
    radarr.lookup_results = [
        {"title": "Twin", "year": 2020, "tmdbId": 1},
        {"title": "Twin", "year": 2020, "tmdbId": 2},
    ]
    engine = make_engine(config, cache, radarr=radarr)

    result = engine.manual_add(str(managed.parent))

    assert result["ok"] is False
    assert result["reason"] == "ambiguous"
    assert len(result["candidates"]) == 2
    assert not radarr.added


def test_manual_add_requires_quality_profile(config, cache, roots):
    managed = write_file(roots["managed_movies"] / "NoProfile (2020)" / "NoProfile.mkv")
    radarr = FakeRadarr([])
    radarr.lookup_results = [{"title": "NoProfile", "year": 2020}]
    engine = make_engine(config, cache, radarr=radarr)

    result = engine.manual_add(str(managed.parent))

    assert result["ok"] is False
    assert result["reason"] == "auto_add_disabled"
    assert "quality_profile" in (result["detail"] or "")


def test_manual_add_outside_managed_roots(config, cache, tmp_path):
    foreign = tmp_path / "elsewhere" / "Foo (2020)"
    foreign.mkdir(parents=True)
    engine = make_engine(config, cache, radarr=FakeRadarr([]), sonarr=FakeSonarr([]))

    result = engine.manual_add(str(foreign))

    assert result["ok"] is False
    assert result["reason"] == "outside_roots"


def test_manual_add_missing_folder(config, cache):
    engine = make_engine(config, cache, radarr=FakeRadarr([]))
    result = engine.manual_add("/nowhere/at/all")
    assert result["ok"] is False
    assert result["reason"] == "not_found"


def test_manual_add_series_folder(config, cache, roots):
    config.sonarr.auto_add_quality_profile_id = 3
    managed = write_file(
        roots["managed_series"] / "Manual Show (2022)" / "Season 01" / "Manual.S01E01.mkv"
    )
    sonarr = FakeSonarr([], {})
    sonarr.lookup_results = [{"title": "Manual Show", "year": 2022, "tvdbId": 9}]
    engine = make_engine(config, cache, sonarr=sonarr)

    result = engine.manual_add(str(managed.parent.parent))

    assert result["ok"] is True, result
    assert len(sonarr.added) == 1


def test_manual_add_surfaces_arr_rejection(config, cache, roots):
    config.radarr.auto_add_quality_profile_id = 4
    managed = write_file(roots["managed_movies"] / "Dupe (2020)" / "Dupe.mkv")
    radarr = FakeRadarr([])
    radarr.lookup_results = [{"title": "Dupe", "year": 2020, "tmdbId": 7}]

    def rejecting_add(*args, **kwargs):
        raise RuntimeError("This movie has already been added (tmdbId 7)")

    radarr.add_movie_from_lookup = rejecting_add
    engine = make_engine(config, cache, radarr=radarr)

    result = engine.manual_add(str(managed.parent))

    assert result["ok"] is False
    assert result["reason"] == "add_failed"
    assert "already been added" in (result["detail"] or "")
