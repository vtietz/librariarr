"""Executable scenario matrix (docs/reconciliation_scenarios.md) on a real filesystem.

Each test number references a scenario row; Radarr and Sonarr variants share
the numbering.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from librariarr.core.engine import SCOPE_CONSISTENCY, SCOPE_FULL
from librariarr.core.fsops import TRASH_DIR_NAME

from .conftest import FakeRadarr, FakeSonarr, hardlink, write_file

pytestmark = pytest.mark.fs_e2e


def inode(path: Path) -> int:
    return path.stat().st_ino


def movie(movie_id: int, title: str, year: int, folder: Path, file_path: Path | None) -> dict:
    payload: dict = {"id": movie_id, "title": title, "year": year, "path": str(folder)}
    if file_path is not None:
        payload["movieFile"] = {"path": str(file_path)}
    return payload


def series(series_id: int, title: str, year: int, folder: Path) -> dict:
    return {
        "id": series_id,
        "title": title,
        "year": year,
        "path": str(folder),
        "statistics": {"episodeFileCount": 1},
    }


def episode(path: Path, relative: str) -> dict:
    return {"path": str(path), "relativePath": relative}


# -- Scenario 1: new Arr import ------------------------------------------------


def test_s1_new_radarr_import_lands_in_managed_tree(make_engine, roots):
    lib_file = write_file(roots["library_movies"] / "Bar (2011)" / "Bar.mkv")
    radarr = FakeRadarr([movie(1, "Bar", 2011, lib_file.parent, lib_file)])

    make_engine(radarr=radarr).run(scope=SCOPE_CONSISTENCY)

    managed = roots["managed_movies"] / "Bar (2011)" / "Bar.mkv"
    assert managed.exists() and inode(managed) == inode(lib_file)
    assert lib_file.exists(), "Radarr's file must never disappear"


def test_s1_new_sonarr_import_lands_in_managed_tree(make_engine, roots):
    shadow_folder = roots["shadow_series"] / "Fresh (2022)"
    shadow_ep = write_file(shadow_folder / "Season 01" / "Fresh.S01E01.mkv")
    sonarr = FakeSonarr(
        [series(1, "Fresh", 2022, shadow_folder)],
        {1: [episode(shadow_ep, "Season 01/Fresh.S01E01.mkv")]},
    )

    make_engine(sonarr=sonarr).run(scope=SCOPE_CONSISTENCY)

    managed = roots["managed_series"] / "Fresh (2022)" / "Season 01" / "Fresh.S01E01.mkv"
    assert managed.exists() and inode(managed) == inode(shadow_ep)


# -- Scenario 2: quality/file replacement -------------------------------------


def test_s2_radarr_upgrade_replaces_managed_file(make_engine, cache, roots):
    managed_old = write_file(roots["managed_movies"] / "Foo (2020)" / "Foo.old.mkv", "old")
    cache.set_folder("radarr", 1, managed_old.parent)
    lib_new = write_file(roots["library_movies"] / "Foo (2020)" / "Foo.remux.mkv", "new")
    os.utime(managed_old, (1000, 1000))
    os.utime(lib_new, (2000, 2000))
    radarr = FakeRadarr([movie(1, "Foo", 2020, lib_new.parent, lib_new)])

    make_engine(radarr=radarr).run(scope=SCOPE_CONSISTENCY)

    managed_new = managed_old.parent / "Foo.remux.mkv"
    assert managed_new.exists() and inode(managed_new) == inode(lib_new)
    assert not managed_old.exists()
    assert any((roots["managed_movies"] / TRASH_DIR_NAME).rglob("Foo.old.mkv"))


def test_s2_sonarr_upgrade_replaces_only_same_episode(make_engine, cache, roots):
    series_folder = roots["managed_series"] / "Show (2020)"
    old_e1 = write_file(series_folder / "Season 01" / "Show.S01E01.old.mkv", "old")
    keep_e2 = write_file(series_folder / "Season 01" / "Show.S01E02.mkv", "keep")
    cache.set_folder("sonarr", 1, series_folder)
    shadow_folder = roots["shadow_series"] / "Show (2020)"
    shadow_e2 = hardlink(keep_e2, shadow_folder / "Season 01" / "Show.S01E02.mkv")
    new_e1 = write_file(shadow_folder / "Season 01" / "Show.S01E01.mkv", "new")
    os.utime(old_e1, (1000, 1000))
    os.utime(new_e1, (2000, 2000))
    sonarr = FakeSonarr(
        [series(1, "Show", 2020, shadow_folder)],
        {
            1: [
                episode(new_e1, "Season 01/Show.S01E01.mkv"),
                episode(shadow_e2, "Season 01/Show.S01E02.mkv"),
            ]
        },
    )

    make_engine(sonarr=sonarr).run(scope=SCOPE_CONSISTENCY)

    assert (series_folder / "Season 01" / "Show.S01E01.mkv").exists()
    assert not old_e1.exists()
    assert keep_e2.exists(), "other episodes must be untouched"


# -- Scenario 3: user rename/move in managed root ------------------------------


def test_s3_user_move_in_managed_tree_survives_via_inode(make_engine, cache, roots):
    managed = write_file(roots["managed_movies"] / "new-bucket" / "Foo (2020)" / "Foo.mkv")
    lib_file = hardlink(managed, roots["library_movies"] / "Foo (2020)" / "Foo.mkv")
    radarr = FakeRadarr([movie(1, "Foo", 2020, lib_file.parent, lib_file)])

    report = make_engine(radarr=radarr).run(scope=SCOPE_FULL)

    assert cache.get_folder("radarr", 1) == managed.parent
    assert not any(a.kind in {"ingest_link", "trash"} for a in report.actions)
    assert lib_file.exists()


# -- Scenario 4: manual add in managed root (auto-add / report) ----------------


def test_s4_confident_unmatched_folder_is_auto_added(make_engine, config, cache, roots):
    config.radarr.auto_add_unmatched = True
    config.radarr.auto_add_quality_profile_id = 1
    managed = write_file(roots["managed_movies"] / "New Movie (2021)" / "New.mkv")
    radarr = FakeRadarr([])
    radarr.lookup_results = [{"title": "New Movie", "year": 2021, "tmdbId": 42}]

    report = make_engine(radarr=radarr).run(scope=SCOPE_FULL)

    assert len(radarr.added) == 1
    projected = Path(radarr.added[0]["path"]) / "New.mkv"
    assert projected.exists() and inode(projected) == inode(managed)
    assert not report.unmatched


def test_s4_ambiguous_folder_is_reported_and_skipped(make_engine, config, roots):
    config.radarr.auto_add_unmatched = True
    config.radarr.auto_add_quality_profile_id = 1
    write_file(roots["managed_movies"] / "Twin (2020)" / "Twin.mkv")
    radarr = FakeRadarr([])
    radarr.lookup_results = [
        {"title": "Twin", "year": 2020, "tmdbId": 1},
        {"title": "Twin", "year": 2020, "tmdbId": 2},
    ]

    report = make_engine(radarr=radarr).run(scope=SCOPE_FULL)

    assert not radarr.added
    assert [u.reason for u in report.unmatched] == ["ambiguous"]


def test_s4_fileless_arr_entry_adopts_matching_folder(make_engine, roots):
    managed = write_file(roots["managed_movies"] / "Adopt Me (2018)" / "Adopt.mkv")
    library_folder = roots["library_movies"] / "Adopt Me (2018)"
    radarr = FakeRadarr([movie(5, "Adopt Me", 2018, library_folder, None)])

    make_engine(radarr=radarr).run(scope=SCOPE_FULL)

    assert (library_folder / "Adopt.mkv").exists()
    assert inode(library_folder / "Adopt.mkv") == inode(managed)
    assert 5 in radarr.refreshed


# -- Scenario 6: extras and unknown files policy --------------------------------


def test_s6_extras_allowlist_is_projected_unknown_files_stay(make_engine, cache, roots):
    managed_folder = roots["managed_movies"] / "Foo (2020)"
    managed = write_file(managed_folder / "Foo.mkv")
    write_file(managed_folder / "poster.jpg")
    write_file(managed_folder / "notes.txt")
    lib_file = hardlink(managed, roots["library_movies"] / "Foo (2020)" / "Foo.mkv")
    cache.set_folder("radarr", 1, managed_folder)
    radarr = FakeRadarr([movie(1, "Foo", 2020, lib_file.parent, lib_file)])

    make_engine(radarr=radarr).run(scope=SCOPE_CONSISTENCY)

    assert (lib_file.parent / "poster.jpg").exists()
    assert not (lib_file.parent / "notes.txt").exists()
    assert (managed_folder / "notes.txt").exists()


# -- Scenario 7: missing managed source ----------------------------------------


def test_s7_missing_everything_warns_and_skips(make_engine, roots):
    lib_folder = roots["library_movies"] / "Ghost (2015)"
    ghost_file = lib_folder / "Ghost.mkv"  # never created
    radarr = FakeRadarr([movie(3, "Ghost", 2015, lib_folder, ghost_file)])

    report = make_engine(radarr=radarr).run(scope=SCOPE_FULL)

    assert report.warnings
    assert not ghost_file.exists()


# -- Scenario 8: idempotency / duplicate prevention -----------------------------


def test_s8_repeated_full_reconcile_is_idempotent(make_engine, roots):
    lib_file = write_file(roots["library_movies"] / "Bar (2011)" / "Bar.mkv")
    radarr = FakeRadarr([movie(1, "Bar", 2011, lib_file.parent, lib_file)])
    engine = make_engine(radarr=radarr)

    engine.run(scope=SCOPE_FULL)
    second = engine.run(scope=SCOPE_FULL)
    third = engine.run(scope=SCOPE_CONSISTENCY)

    assert second.actions == []
    assert third.actions == []


# -- Scenario 9: stale library/shadow leftovers ---------------------------------


def test_s9_stale_library_folder_is_pruned_managed_kept(make_engine, roots):
    managed = write_file(roots["managed_movies"] / "Gone (1999)" / "Gone.mkv")
    lib_file = hardlink(managed, roots["library_movies"] / "Gone (1999)" / "Gone.mkv")
    radarr = FakeRadarr([])

    make_engine(radarr=radarr).run(scope=SCOPE_FULL)

    assert managed.exists()
    assert not lib_file.parent.exists()


def test_s9_sole_copy_video_in_stale_folder_is_never_deleted(make_engine, roots):
    orphan = write_file(roots["library_movies"] / "Orphan (2000)" / "Orphan.mkv")
    radarr = FakeRadarr([])

    report = make_engine(radarr=radarr).run(scope=SCOPE_FULL)

    assert orphan.exists()
    assert report.warnings


# -- Scenario 10: user replacement in managed tree ------------------------------


def test_s10_user_replacement_wins_when_managed_newer(make_engine, cache, roots):
    managed_folder = roots["managed_movies"] / "Foo (2020)"
    managed_new = write_file(managed_folder / "Foo.better.mkv", "better")
    cache.set_folder("radarr", 1, managed_folder)
    lib_old = write_file(roots["library_movies"] / "Foo (2020)" / "Foo.mkv", "old")
    os.utime(lib_old, (1000, 1000))
    os.utime(managed_new, (2000, 2000))
    radarr = FakeRadarr([movie(1, "Foo", 2020, lib_old.parent, lib_old)])

    make_engine(radarr=radarr).run(scope=SCOPE_CONSISTENCY)

    assert inode(lib_old) == inode(managed_new)
    assert 1 in radarr.refreshed
