"""Arr-side root-folder reassignment ("move to another root folder") is
treated as a deliberate reclassification: the managed folder is relocated to
match. This needs two configured buckets (movie/series_root_mappings), unlike
the single-mapping fixtures in conftest.py, so it builds its own config.
"""

from __future__ import annotations

import os
import time

from librariarr.core.engine import SCOPE_CONSISTENCY, SCOPE_FULL, ReconcileEngine

from .conftest import (
    FakeRadarr,
    FakeSonarr,
    hardlink,
    move_same_filesystem,
    movie_payload,
    series_payload,
    write_file,
)


def test_movie_follows_radarr_root_folder_change_to_new_bucket(multi_bucket_config, cache, buckets):
    managed_file = write_file(buckets["managed_a"] / "Foo (2020)" / "Foo.mkv")
    old_lib_file = hardlink(managed_file, buckets["library_a"] / "Foo (2020)" / "Foo.mkv")
    cache.set_folder("radarr", 1, managed_file.parent)
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, old_lib_file.parent, old_lib_file)])
    engine = ReconcileEngine(multi_bucket_config, radarr=radarr, sonarr=None, cache=cache)
    engine.run(scope=SCOPE_FULL)

    # User changes the movie's Root Folder in Radarr to FSK16 ("Move files").
    new_lib_file = buckets["library_b"] / "Foo (2020)" / "Foo.mkv"
    move_same_filesystem(old_lib_file, new_lib_file)
    old_lib_file.parent.rmdir()
    radarr.movies[0]["path"] = str(new_lib_file.parent)
    radarr.movies[0]["movieFile"]["path"] = str(new_lib_file)

    report = engine.run(scope=SCOPE_FULL)

    new_managed_location = buckets["managed_b"] / "Foo (2020)" / "Foo.mkv"
    assert new_managed_location.exists(), "managed file must follow into the new bucket"
    assert not managed_file.exists(), "old bucket location must be gone (real move, not a copy)"
    assert new_managed_location.stat().st_ino == new_lib_file.stat().st_ino
    assert cache.get_folder("radarr", 1) == new_managed_location.parent
    assert any(a.kind == "relocate" for a in report.actions)
    assert not (buckets["managed_a"] / "Foo (2020)").exists(), "empty old folder is pruned"


def test_movie_relocation_preserves_user_custom_naming(multi_bucket_config, cache, buckets):
    # User nested it under a custom subfolder and gave it a name of their own.
    managed_file = write_file(
        buckets["managed_a"] / "Studio X" / "My Custom Name (2020)" / "Foo.mkv"
    )
    old_lib_file = hardlink(managed_file, buckets["library_a"] / "Foo (2020)" / "Foo.mkv")
    cache.set_folder("radarr", 1, managed_file.parent)
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, old_lib_file.parent, old_lib_file)])
    engine = ReconcileEngine(multi_bucket_config, radarr=radarr, sonarr=None, cache=cache)
    engine.run(scope=SCOPE_FULL)

    new_lib_file = buckets["library_b"] / "Foo (2020)" / "Foo.mkv"
    move_same_filesystem(old_lib_file, new_lib_file)
    old_lib_file.parent.rmdir()
    radarr.movies[0]["path"] = str(new_lib_file.parent)
    radarr.movies[0]["movieFile"]["path"] = str(new_lib_file)

    engine.run(scope=SCOPE_FULL)

    expected = buckets["managed_b"] / "Studio X" / "My Custom Name (2020)" / "Foo.mkv"
    assert expected.exists(), "custom subfolder structure and naming must be preserved verbatim"


def test_movie_relocation_refuses_to_clobber_existing_destination(
    multi_bucket_config, cache, buckets
):
    managed_file = write_file(buckets["managed_a"] / "Foo (2020)" / "Foo.mkv")
    old_lib_file = hardlink(managed_file, buckets["library_a"] / "Foo (2020)" / "Foo.mkv")
    cache.set_folder("radarr", 1, managed_file.parent)
    # Something already occupies the destination.
    write_file(buckets["managed_b"] / "Foo (2020)" / "unrelated.mkv")
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, old_lib_file.parent, old_lib_file)])
    engine = ReconcileEngine(multi_bucket_config, radarr=radarr, sonarr=None, cache=cache)
    engine.run(scope=SCOPE_FULL)

    new_lib_file = buckets["library_b"] / "Foo (2020)" / "Foo.mkv"
    move_same_filesystem(old_lib_file, new_lib_file)
    old_lib_file.parent.rmdir()
    radarr.movies[0]["path"] = str(new_lib_file.parent)
    radarr.movies[0]["movieFile"]["path"] = str(new_lib_file)

    report = engine.run(scope=SCOPE_FULL)

    assert managed_file.exists(), "original must be untouched when destination is occupied"
    assert not any(a.kind == "relocate" for a in report.actions)
    assert report.warnings


def test_movie_relocation_dry_run_reports_without_moving(multi_bucket_config, cache, buckets):
    managed_file = write_file(buckets["managed_a"] / "Foo (2020)" / "Foo.mkv")
    old_lib_file = hardlink(managed_file, buckets["library_a"] / "Foo (2020)" / "Foo.mkv")
    cache.set_folder("radarr", 1, managed_file.parent)
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, old_lib_file.parent, old_lib_file)])
    engine = ReconcileEngine(multi_bucket_config, radarr=radarr, sonarr=None, cache=cache)
    engine.run(scope=SCOPE_FULL)

    new_lib_file = buckets["library_b"] / "Foo (2020)" / "Foo.mkv"
    move_same_filesystem(old_lib_file, new_lib_file)
    old_lib_file.parent.rmdir()
    radarr.movies[0]["path"] = str(new_lib_file.parent)
    radarr.movies[0]["movieFile"]["path"] = str(new_lib_file)

    report = engine.run(scope=SCOPE_FULL, dry_run=True)

    assert managed_file.exists(), "dry-run must not move anything"
    assert not (buckets["managed_b"] / "Foo (2020)").exists()
    assert any(a.kind == "relocate" for a in report.actions)


def test_relocation_moves_the_whole_movie_folder_not_just_the_videos_parent(
    multi_bucket_config, cache, buckets
):
    """Multi-disc / subfolder layout: the video sits below the movie folder, so
    relocating only its parent would strand the rest of the movie in the old
    bucket."""
    managed_folder = buckets["managed_a"] / "Foo (2020)"
    managed_file = write_file(managed_folder / "Disc1" / "Foo.mkv")
    write_file(managed_folder / "movie.nfo", "meta")
    old_lib_file = hardlink(managed_file, buckets["library_a"] / "Foo (2020)" / "Foo.mkv")
    cache.set_folder("radarr", 1, managed_folder)
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, old_lib_file.parent, old_lib_file)])
    engine = ReconcileEngine(multi_bucket_config, radarr=radarr, sonarr=None, cache=cache)

    new_lib_file = buckets["library_b"] / "Foo (2020)" / "Foo.mkv"
    move_same_filesystem(old_lib_file, new_lib_file)
    radarr.movies[0]["path"] = str(new_lib_file.parent)
    radarr.movies[0]["movieFile"]["path"] = str(new_lib_file)

    engine.run(scope=SCOPE_CONSISTENCY)

    assert (buckets["managed_b"] / "Foo (2020)" / "Disc1" / "Foo.mkv").exists()
    assert (buckets["managed_b"] / "Foo (2020)" / "movie.nfo").exists(), (
        "the whole movie folder must move, not just the video's parent"
    )
    assert not managed_folder.exists(), "nothing may be left behind in the old bucket"


def test_relocation_refuses_when_two_arr_items_claim_the_same_managed_folder(
    multi_bucket_config, cache, buckets
):
    """A folder with two owners cannot be reclassified on behalf of one of them
    without silently reclassifying the other."""
    managed_file = write_file(buckets["managed_a"] / "Foo (2020)" / "Foo.mkv")
    old_lib_file = hardlink(managed_file, buckets["library_a"] / "Foo (2020)" / "Foo.mkv")
    cache.set_folder("radarr", 1, managed_file.parent)
    cache.set_folder("radarr", 2, managed_file.parent)  # duplicate Radarr entry
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, old_lib_file.parent, old_lib_file)])
    engine = ReconcileEngine(multi_bucket_config, radarr=radarr, sonarr=None, cache=cache)

    new_lib_file = buckets["library_b"] / "Foo (2020)" / "Foo.mkv"
    move_same_filesystem(old_lib_file, new_lib_file)
    radarr.movies[0]["path"] = str(new_lib_file.parent)
    radarr.movies[0]["movieFile"]["path"] = str(new_lib_file)

    report = engine.run(scope=SCOPE_CONSISTENCY)

    assert managed_file.exists(), "an ambiguous folder must stay put"
    assert not (buckets["managed_b"] / "Foo (2020)").exists()
    assert not any(action.kind == "relocate" for action in report.actions)
    assert report.stats.get("relocations_blocked_ambiguous_owner") == 1
    assert any("more than one owner" in warning for warning in report.warnings)


def test_relocation_happens_even_when_the_library_inode_is_unresolved(
    multi_bucket_config, cache, buckets
):
    """Known coverage gap, now closed: a bucket move can coincide with an
    unresolved inode (Radarr copied instead of renaming, or an upgrade landed in
    the same cycle). The relocation must happen first, so the ingest lands in
    the new bucket instead of duplicating into the old one."""
    managed_file = write_file(buckets["managed_a"] / "Foo (2020)" / "Foo.old.mkv", "old")
    old_mtime = time.time() - 3600
    os.utime(managed_file, (old_mtime, old_mtime))
    cache.set_folder("radarr", 1, managed_file.parent)

    # Radarr's file is in the new bucket *and* a different inode than ours.
    new_lib_file = write_file(buckets["library_b"] / "Foo (2020)" / "Foo.new.mkv", "new")
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, new_lib_file.parent, new_lib_file)])
    engine = ReconcileEngine(multi_bucket_config, radarr=radarr, sonarr=None, cache=cache)

    report = engine.run(scope=SCOPE_CONSISTENCY)

    assert any(action.kind == "relocate" for action in report.actions)
    assert not (buckets["managed_a"] / "Foo (2020)").exists(), (
        "the managed folder must not stay in the old bucket"
    )
    ingested = buckets["managed_b"] / "Foo (2020)" / "Foo.new.mkv"
    assert ingested.exists() and ingested.stat().st_ino == new_lib_file.stat().st_ino
    assert cache.get_folder("radarr", 1) == buckets["managed_b"] / "Foo (2020)"
    assert (
        buckets["managed_b"] / ".deletedByLibrariarr" / "Foo (2020)" / "Foo.old.mkv"
    ).exists(), "the superseded managed video is quarantined in the new bucket"


def test_series_follows_sonarr_root_folder_change_to_new_bucket(
    multi_bucket_config, cache, buckets
):
    managed_ep = write_file(
        buckets["series_managed_a"] / "Show (2020)" / "Season 01" / "Show.S01E01.mkv"
    )
    old_shadow_ep = hardlink(
        managed_ep, buckets["series_shadow_a"] / "Show (2020)" / "Season 01" / "Show.S01E01.mkv"
    )
    cache.set_folder("sonarr", 1, managed_ep.parent.parent)
    sonarr = FakeSonarr(
        [series_payload(1, "Show", 2020, buckets["series_shadow_a"] / "Show (2020)")],
        {1: [{"path": str(old_shadow_ep), "relativePath": "Season 01/Show.S01E01.mkv"}]},
    )
    engine = ReconcileEngine(multi_bucket_config, radarr=None, sonarr=sonarr, cache=cache)
    engine.run(scope=SCOPE_FULL)

    new_shadow_ep = buckets["series_shadow_b"] / "Show (2020)" / "Season 01" / "Show.S01E01.mkv"
    move_same_filesystem(old_shadow_ep, new_shadow_ep)
    sonarr.series[0]["path"] = str(new_shadow_ep.parent.parent)
    sonarr.episode_files[1] = [
        {"path": str(new_shadow_ep), "relativePath": "Season 01/Show.S01E01.mkv"}
    ]

    report = engine.run(scope=SCOPE_FULL)

    new_managed_ep = buckets["series_managed_b"] / "Show (2020)" / "Season 01" / "Show.S01E01.mkv"
    assert new_managed_ep.exists(), "managed episode must follow into the new bucket"
    assert not managed_ep.exists()
    assert new_managed_ep.stat().st_ino == new_shadow_ep.stat().st_ino
    assert cache.get_folder("sonarr", 1) == new_managed_ep.parent.parent
    assert any(a.kind == "relocate" for a in report.actions)
