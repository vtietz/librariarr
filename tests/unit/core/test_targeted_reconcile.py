"""Targeted scope: the per-item flow for an explicit list of Arr ids.

The point of this scope is cost, not behavior — a webhook that names one movie
must not pay for a pass over the whole library. So the tests here check two
things: that the work really is narrowed (no library-wide Arr fetch, no
per-item work for anything else), and that narrowing changed no decision, by
comparing a targeted pass against a consistency pass over the same state.
"""

from __future__ import annotations

import os
import time

from librariarr.core.engine import SCOPE_CONSISTENCY, SCOPE_TARGETED, ReconcileEngine

from .conftest import FakeRadarr, FakeSonarr, hardlink, movie_payload, series_payload, write_file


def make_engine(config, cache, radarr=None, sonarr=None) -> ReconcileEngine:
    return ReconcileEngine(config, radarr=radarr, sonarr=sonarr, cache=cache)


def action_pairs(report) -> set[tuple[str, str | None, str | None]]:
    return {(action.kind, action.source, action.target) for action in report.actions}


def test_targeted_import_ingests_only_the_named_movie(config, cache, roots):
    """Scenario 1 via the targeted scope: the named movie is ingested and the
    other movie in the library is not even fetched."""
    named = write_file(roots["library_movies"] / "Named (2021)" / "Named.mkv")
    other = write_file(roots["library_movies"] / "Other (2022)" / "Other.mkv")
    radarr = FakeRadarr(
        [
            movie_payload(1, "Named", 2021, named.parent, named),
            movie_payload(2, "Other", 2022, other.parent, other),
        ]
    )
    engine = make_engine(config, cache, radarr=radarr)

    report = engine.run(scope=SCOPE_TARGETED, radarr_movie_ids=[1])

    managed = roots["managed_movies"] / "Named (2021)" / "Named.mkv"
    assert managed.exists(), "the named movie must be ingested"
    assert managed.stat().st_ino == named.stat().st_ino
    assert not (roots["managed_movies"] / "Other (2022)").exists(), "other movies stay untouched"
    assert report.items_seen == 1
    assert radarr.calls == ["get_movies_by_ids:[1]"], "a targeted pass must not list all movies"


def test_targeted_pass_matches_a_consistency_pass_for_the_same_item(config, cache, roots):
    """The narrowing must not change a single decision: same actions, same
    filesystem result as the pass that covers everything."""
    lib_file = write_file(roots["library_movies"] / "Same (2020)" / "Same.mkv")
    radarr = FakeRadarr([movie_payload(1, "Same", 2020, lib_file.parent, lib_file)])
    engine = make_engine(config, cache, radarr=radarr)

    targeted = engine.run(scope=SCOPE_TARGETED, radarr_movie_ids=[1], dry_run=True)
    consistency = engine.run(scope=SCOPE_CONSISTENCY, dry_run=True)

    assert action_pairs(targeted) == action_pairs(consistency)
    assert targeted.items_changed == consistency.items_changed


def test_targeted_dry_run_plans_exactly_what_the_mutating_run_does(config, cache, roots):
    lib_file = write_file(roots["library_movies"] / "Planned (2020)" / "Planned.mkv")
    radarr = FakeRadarr([movie_payload(1, "Planned", 2020, lib_file.parent, lib_file)])
    engine = make_engine(config, cache, radarr=radarr)

    planned = engine.run(scope=SCOPE_TARGETED, radarr_movie_ids=[1], dry_run=True)
    assert not (roots["managed_movies"] / "Planned (2020)").exists(), "dry run must not touch disk"

    applied = engine.run(scope=SCOPE_TARGETED, radarr_movie_ids=[1])
    assert action_pairs(planned) == action_pairs(applied)


def test_targeted_upgrade_supersedes_the_old_managed_video(config, cache, roots):
    """Scenario 2 via the targeted scope — the frequent webhook case."""
    managed_old = write_file(roots["managed_movies"] / "Up (2020)" / "Up.old.mkv")
    hardlink(managed_old, roots["library_movies"] / "Up (2020)" / "Up.old.mkv")
    cache.set_folder("radarr", 1, managed_old.parent)

    # Radarr imported a better release: new inode, and it is the newer file.
    new_lib_file = write_file(roots["library_movies"] / "Up (2020)" / "Up.new.mkv", "better")
    os.utime(new_lib_file, (time.time(), time.time()))
    (roots["library_movies"] / "Up (2020)" / "Up.old.mkv").unlink()
    radarr = FakeRadarr([movie_payload(1, "Up", 2020, new_lib_file.parent, new_lib_file)])
    engine = make_engine(config, cache, radarr=radarr)

    report = engine.run(scope=SCOPE_TARGETED, radarr_movie_ids=[1])

    managed_new = roots["managed_movies"] / "Up (2020)" / "Up.new.mkv"
    assert managed_new.exists(), "the upgrade must be ingested into the managed folder"
    assert managed_new.stat().st_ino == new_lib_file.stat().st_ino
    assert not managed_old.exists(), "the superseded managed video must be quarantined"
    assert (
        roots["managed_movies"] / ".deletedByLibrariarr" / "Up (2020)" / "Up.old.mkv"
    ).exists(), "managed data is quarantined, never destroyed"
    assert any(action.kind == "trash" for action in report.actions)


def test_targeted_movie_ids_do_not_touch_sonarr(config, cache, roots):
    """A Radarr webhook must not drag the Sonarr library along — that is where
    most of the saved work goes."""
    lib_file = write_file(roots["library_movies"] / "Solo (2020)" / "Solo.mkv")
    radarr = FakeRadarr([movie_payload(1, "Solo", 2020, lib_file.parent, lib_file)])
    shadow_ep = write_file(roots["shadow_series"] / "Show (2020)" / "Season 01" / "Show.S01E01.mkv")
    sonarr = FakeSonarr(
        [series_payload(1, "Show", 2020, shadow_ep.parent.parent)],
        {1: [{"path": str(shadow_ep), "relativePath": "Season 01/Show.S01E01.mkv"}]},
    )
    engine = make_engine(config, cache, radarr=radarr, sonarr=sonarr)

    engine.run(scope=SCOPE_TARGETED, radarr_movie_ids=[1])

    assert sonarr.calls == [], "Sonarr must not be consulted at all"
    assert not (roots["managed_series"] / "Show (2020)").exists()


def test_targeted_series_ids_do_not_touch_radarr(config, cache, roots):
    shadow_ep = write_file(roots["shadow_series"] / "Show (2020)" / "Season 01" / "Show.S01E01.mkv")
    sonarr = FakeSonarr(
        [series_payload(1, "Show", 2020, shadow_ep.parent.parent)],
        {1: [{"path": str(shadow_ep), "relativePath": "Season 01/Show.S01E01.mkv"}]},
    )
    radarr = FakeRadarr([])
    engine = make_engine(config, cache, radarr=radarr, sonarr=sonarr)

    engine.run(scope=SCOPE_TARGETED, sonarr_series_ids=[1])

    assert radarr.calls == []
    managed_ep = roots["managed_series"] / "Show (2020)" / "Season 01" / "Show.S01E01.mkv"
    assert managed_ep.exists(), "the named series must still be reconciled"
    assert sonarr.calls == ["get_series_by_ids:[1]"]


def test_targeted_pass_never_prunes_library_folders(config, cache, roots):
    """A targeted pass sees a partial item list, so pruning ("delete what Arr no
    longer lists") must stay off — otherwise every folder outside the subset
    would look stale."""
    named = write_file(roots["library_movies"] / "Named (2021)" / "Named.mkv")
    stale = write_file(roots["library_movies"] / "Gone (1999)" / "Gone.mkv")
    radarr = FakeRadarr([movie_payload(1, "Named", 2021, named.parent, named)])
    engine = make_engine(config, cache, radarr=radarr)

    engine.run(scope=SCOPE_TARGETED, radarr_movie_ids=[1])

    assert stale.exists(), "a targeted pass must not prune anything"


def test_targeted_pass_without_ids_does_nothing(config, cache, roots):
    write_file(roots["library_movies"] / "Untouched (2020)" / "Untouched.mkv")
    radarr = FakeRadarr([])
    engine = make_engine(config, cache, radarr=radarr)

    report = engine.run(scope=SCOPE_TARGETED)

    assert radarr.calls == []
    assert report.items_seen == 0
    assert report.warnings, "the no-op must be visible rather than silent"


def test_targeted_pass_ignores_unusable_ids(config, cache):
    radarr = FakeRadarr([])
    engine = make_engine(config, cache, radarr=radarr)

    report = engine.run(scope=SCOPE_TARGETED, radarr_movie_ids=[0, -5])

    assert radarr.calls == [], "a malformed id must not widen the scope"
    assert report.warnings


def test_targeted_pass_for_an_unknown_id_is_a_noop(config, cache):
    radarr = FakeRadarr([])
    engine = make_engine(config, cache, radarr=radarr)

    report = engine.run(scope=SCOPE_TARGETED, radarr_movie_ids=[4473])

    assert radarr.calls == ["get_movies_by_ids:[4473]"]
    assert report.items_seen == 0
    assert report.actions == []


def test_targeted_pass_deduplicates_ids(config, cache, roots):
    lib_file = write_file(roots["library_movies"] / "Once (2020)" / "Once.mkv")
    radarr = FakeRadarr([movie_payload(1, "Once", 2020, lib_file.parent, lib_file)])
    engine = make_engine(config, cache, radarr=radarr)

    report = engine.run(scope=SCOPE_TARGETED, radarr_movie_ids=[1, 1, 1])

    assert radarr.calls == ["get_movies_by_ids:[1]"]
    assert report.items_seen == 1
