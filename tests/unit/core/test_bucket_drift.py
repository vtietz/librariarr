"""Bucket-drift detection: finding pending root-folder reassignments.

Radarr/Sonarr send no webhook for a root-folder move (MovieMovedEvent reaches
health checks only, never notification providers), so scenario 11 has to be
noticed by polling. That only pays off if the poll is genuinely cheap, which is
what most of these tests pin down: one Arr list call, no tree walk, and a
targeted reconcile afterwards that touches nothing but the drifted items.
"""

from __future__ import annotations

import os

from librariarr.core.engine import ReconcileEngine
from librariarr.service import LibrariArrService

from .conftest import (
    FakeRadarr,
    FakeSonarr,
    hardlink,
    move_same_filesystem,
    movie_payload,
    series_payload,
    write_file,
)


def drifted_movie(multi_bucket_config, cache, buckets, radarr_id: int = 1):
    """A movie whose Radarr root folder was changed to the second bucket while
    its managed folder still sits in the first."""
    managed_file = write_file(buckets["managed_a"] / "Foo (2020)" / "Foo.mkv")
    lib_file = hardlink(managed_file, buckets["library_a"] / "Foo (2020)" / "Foo.mkv")
    cache.set_folder("radarr", radarr_id, managed_file.parent)
    radarr = FakeRadarr([movie_payload(radarr_id, "Foo", 2020, lib_file.parent, lib_file)])
    new_lib_file = move_same_filesystem(lib_file, buckets["library_b"] / "Foo (2020)" / "Foo.mkv")
    radarr.movies[0]["path"] = str(new_lib_file.parent)
    radarr.movies[0]["movieFile"]["path"] = str(new_lib_file)
    return radarr, managed_file


def test_detects_a_pending_bucket_move(multi_bucket_config, cache, buckets):
    radarr, managed_file = drifted_movie(multi_bucket_config, cache, buckets)
    engine = ReconcileEngine(multi_bucket_config, radarr=radarr, sonarr=None, cache=cache)

    drift = engine.list_bucket_drift()

    assert len(drift) == 1
    entry = drift[0]
    assert entry["kind"] == "movie"
    assert entry["id"] == 1
    assert entry["title"] == "Foo"
    assert entry["managed_path"] == str(managed_file.parent)
    assert entry["current_bucket"] == str(buckets["managed_a"])
    assert entry["target_bucket"] == str(buckets["managed_b"])


def test_detection_does_not_walk_the_filesystem(multi_bucket_config, cache, buckets, monkeypatch):
    """The whole point of polling instead of running a pass: detection must not
    walk the tree, whatever the library size."""
    radarr, _ = drifted_movie(multi_bucket_config, cache, buckets)
    engine = ReconcileEngine(multi_bucket_config, radarr=radarr, sonarr=None, cache=cache)

    def fail_walk(*args, **kwargs):
        raise AssertionError("bucket-drift detection must not walk the tree")

    monkeypatch.setattr(os, "walk", fail_walk)

    assert len(engine.list_bucket_drift()) == 1
    assert radarr.calls == ["get_movies"], "one Arr list call, nothing else"


def test_no_drift_when_the_bucket_still_matches(multi_bucket_config, cache, buckets):
    managed_file = write_file(buckets["managed_a"] / "Foo (2020)" / "Foo.mkv")
    lib_file = hardlink(managed_file, buckets["library_a"] / "Foo (2020)" / "Foo.mkv")
    cache.set_folder("radarr", 1, managed_file.parent)
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, lib_file.parent, lib_file)])
    engine = ReconcileEngine(multi_bucket_config, radarr=radarr, sonarr=None, cache=cache)

    assert engine.list_bucket_drift() == []


def test_items_without_a_cached_folder_are_skipped(multi_bucket_config, cache, buckets):
    """The cache stays advisory: what the poll cannot see, the full pass owns."""
    lib_file = write_file(buckets["library_b"] / "Foo (2020)" / "Foo.mkv")
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, lib_file.parent, lib_file)])
    engine = ReconcileEngine(multi_bucket_config, radarr=radarr, sonarr=None, cache=cache)

    assert engine.list_bucket_drift() == []


def test_stale_cache_entry_is_not_reported_as_drift(multi_bucket_config, cache, buckets):
    lib_file = write_file(buckets["library_b"] / "Foo (2020)" / "Foo.mkv")
    cache.set_folder("radarr", 1, buckets["managed_a"] / "Gone (2020)")  # folder no longer exists
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, lib_file.parent, lib_file)])
    engine = ReconcileEngine(multi_bucket_config, radarr=radarr, sonarr=None, cache=cache)

    assert engine.list_bucket_drift() == []


def test_arr_path_outside_every_library_root_is_skipped(multi_bucket_config, cache, buckets):
    """Production has movies whose Radarr path points straight at a managed
    folder; those are not a bucket move and must not be reported as one."""
    managed_file = write_file(buckets["managed_a"] / "Foo (2020)" / "Foo.mkv")
    cache.set_folder("radarr", 1, managed_file.parent)
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, managed_file.parent, managed_file)])
    engine = ReconcileEngine(multi_bucket_config, radarr=radarr, sonarr=None, cache=cache)

    assert engine.list_bucket_drift() == []


def test_detects_a_pending_series_bucket_move(multi_bucket_config, cache, buckets):
    managed_ep = write_file(
        buckets["series_managed_a"] / "Show (2020)" / "Season 01" / "Show.S01E01.mkv"
    )
    shadow_ep = hardlink(
        managed_ep, buckets["series_shadow_a"] / "Show (2020)" / "Season 01" / "Show.S01E01.mkv"
    )
    cache.set_folder("sonarr", 1, managed_ep.parent.parent)
    sonarr = FakeSonarr(
        [series_payload(1, "Show", 2020, shadow_ep.parent.parent)],
        {1: [{"path": str(shadow_ep), "relativePath": "Season 01/Show.S01E01.mkv"}]},
    )
    new_shadow_ep = move_same_filesystem(
        shadow_ep, buckets["series_shadow_b"] / "Show (2020)" / "Season 01" / "Show.S01E01.mkv"
    )
    sonarr.series[0]["path"] = str(new_shadow_ep.parent.parent)
    engine = ReconcileEngine(multi_bucket_config, radarr=None, sonarr=sonarr, cache=cache)

    drift = engine.list_bucket_drift()

    assert len(drift) == 1
    assert drift[0]["kind"] == "series"
    assert drift[0]["target_bucket"] == str(buckets["series_managed_b"])


def test_service_reconciles_only_the_drifted_items(multi_bucket_config, cache, buckets):
    """End of the chain: detection hands its ids to a targeted pass, and nothing
    else in the library is fetched or touched."""
    radarr, managed_file = drifted_movie(multi_bucket_config, cache, buckets)
    settled = write_file(buckets["managed_b"] / "Settled (2019)" / "Settled.mkv")
    settled_lib = hardlink(settled, buckets["library_b"] / "Settled (2019)" / "Settled.mkv")
    cache.set_folder("radarr", 2, settled.parent)
    radarr.movies.append(movie_payload(2, "Settled", 2019, settled_lib.parent, settled_lib))
    engine = ReconcileEngine(multi_bucket_config, radarr=radarr, sonarr=None, cache=cache)
    service = LibrariArrService(multi_bucket_config, engine=engine)

    report = service.reconcile_bucket_drift()

    assert report is not None
    assert report.scope == "targeted"
    assert radarr.calls == ["get_movies", "get_movies_by_ids:[1]"]
    assert (buckets["managed_b"] / "Foo (2020)" / "Foo.mkv").exists()
    assert not managed_file.exists()


def test_service_returns_none_when_nothing_drifted(multi_bucket_config, cache, buckets):
    managed_file = write_file(buckets["managed_a"] / "Foo (2020)" / "Foo.mkv")
    lib_file = hardlink(managed_file, buckets["library_a"] / "Foo (2020)" / "Foo.mkv")
    cache.set_folder("radarr", 1, managed_file.parent)
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, lib_file.parent, lib_file)])
    engine = ReconcileEngine(multi_bucket_config, radarr=radarr, sonarr=None, cache=cache)
    service = LibrariArrService(multi_bucket_config, engine=engine)

    assert service.reconcile_bucket_drift() is None
    assert radarr.calls == ["get_movies"], "the quiet case costs one list call"
