from __future__ import annotations

import os
from pathlib import Path

from librariarr.core.engine import SCOPE_CONSISTENCY, SCOPE_FULL, ReconcileEngine
from librariarr.core.fsops import TRASH_DIR_NAME
from librariarr.core.index import AdvisoryCache

from .conftest import FakeRadarr, hardlink, movie_payload, write_file


def make_engine(config, cache, radarr: FakeRadarr) -> ReconcileEngine:
    return ReconcileEngine(config, radarr=radarr, sonarr=None, cache=cache)


def inode(path: Path) -> int:
    return path.stat().st_ino


def test_steady_state_produces_no_actions(config, cache, roots):
    managed = write_file(roots["managed_movies"] / "kids" / "Foo (2020)" / "Foo.2020.mkv")
    lib_file = hardlink(managed, roots["library_movies"] / "Foo (2020)" / "Foo.2020.mkv")
    cache.set_folder("radarr", 1, managed.parent)
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, lib_file.parent, lib_file)])

    report = make_engine(config, cache, radarr).run(scope=SCOPE_CONSISTENCY)

    assert report.actions == []
    assert report.errors == []
    assert report.items_seen == 1


def test_new_import_is_ingested_via_hardlink(config, cache, roots):
    lib_file = write_file(roots["library_movies"] / "Bar (2011)" / "Bar.2011.mkv")
    radarr = FakeRadarr([movie_payload(2, "Bar", 2011, lib_file.parent, lib_file)])

    report = make_engine(config, cache, radarr).run(scope=SCOPE_CONSISTENCY)

    managed_copy = roots["managed_movies"] / "Bar (2011)" / "Bar.2011.mkv"
    assert managed_copy.exists()
    assert inode(managed_copy) == inode(lib_file)
    assert any(a.kind == "ingest_link" for a in report.actions)
    assert cache.get_folder("radarr", 2) == managed_copy.parent


def test_new_import_ingests_extras_but_not_unknown_files(config, cache, roots):
    lib_folder = roots["library_movies"] / "Bar (2011)"
    lib_file = write_file(lib_folder / "Bar.2011.mkv")
    write_file(lib_folder / "Bar.2011.srt")
    write_file(lib_folder / "random.txt")
    radarr = FakeRadarr([movie_payload(2, "Bar", 2011, lib_folder, lib_file)])

    make_engine(config, cache, radarr).run(scope=SCOPE_CONSISTENCY)

    managed_folder = roots["managed_movies"] / "Bar (2011)"
    assert (managed_folder / "Bar.2011.srt").exists()
    assert not (managed_folder / "random.txt").exists()


def test_quality_upgrade_ingests_new_inode_and_quarantines_old(config, cache, roots):
    managed_old = write_file(roots["managed_movies"] / "Foo (2020)" / "Foo.old.mkv", "old")
    cache.set_folder("radarr", 1, managed_old.parent)
    lib_folder = roots["library_movies"] / "Foo (2020)"
    lib_new = write_file(lib_folder / "Foo.2020.remux.mkv", "new-better")
    os.utime(managed_old, (1000, 1000))
    os.utime(lib_new, (2000, 2000))
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, lib_folder, lib_new)])

    report = make_engine(config, cache, radarr).run(scope=SCOPE_CONSISTENCY)

    managed_new = managed_old.parent / "Foo.2020.remux.mkv"
    assert managed_new.exists()
    assert inode(managed_new) == inode(lib_new)
    assert not managed_old.exists()
    trash = roots["managed_movies"] / TRASH_DIR_NAME
    assert any(trash.rglob("Foo.old.mkv")), "old file should be quarantined"
    assert any(a.kind == "trash" for a in report.actions)


def test_user_replacement_wins_when_managed_file_is_newer(config, cache, roots):
    managed_folder = roots["managed_movies"] / "Foo (2020)"
    managed_new = write_file(managed_folder / "Foo.better.mkv", "user-upgrade")
    cache.set_folder("radarr", 1, managed_folder)
    lib_folder = roots["library_movies"] / "Foo (2020)"
    lib_old = write_file(lib_folder / "Foo.2020.mkv", "old-arr-file")
    os.utime(lib_old, (1000, 1000))
    os.utime(managed_new, (2000, 2000))
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, lib_folder, lib_old)])

    report = make_engine(config, cache, radarr).run(scope=SCOPE_CONSISTENCY)

    assert inode(lib_old) == inode(managed_new), "library must point at managed inode"
    assert managed_new.exists()
    assert any(a.kind == "relink" for a in report.actions)
    assert 1 in radarr.refreshed, "Radarr must rescan after relink"


def test_managed_rename_is_recovered_via_index(config, cache, roots):
    managed = write_file(roots["managed_movies"] / "old-bucket" / "Foo (2020)" / "Foo.mkv")
    lib_file = hardlink(managed, roots["library_movies"] / "Foo (2020)" / "Foo.mkv")
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, lib_file.parent, lib_file)])
    # No cache hint: simulate rename/move by having cache point nowhere.
    report = make_engine(config, cache, radarr).run(scope=SCOPE_FULL)

    assert cache.get_folder("radarr", 1) == managed.parent
    assert not any(a.kind in {"ingest_link", "trash"} for a in report.actions)


def test_extras_are_projected_and_unknown_left_alone(config, cache, roots):
    managed_folder = roots["managed_movies"] / "Foo (2020)"
    managed = write_file(managed_folder / "Foo.mkv")
    write_file(managed_folder / "poster.jpg")
    write_file(managed_folder / "Foo.srt")
    write_file(managed_folder / "notes.txt")
    lib_file = hardlink(managed, roots["library_movies"] / "Foo (2020)" / "Foo.mkv")
    cache.set_folder("radarr", 1, managed_folder)
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, lib_file.parent, lib_file)])

    make_engine(config, cache, radarr).run(scope=SCOPE_CONSISTENCY)

    lib_folder = lib_file.parent
    assert (lib_folder / "poster.jpg").exists()
    assert (lib_folder / "Foo.srt").exists()
    assert not (lib_folder / "notes.txt").exists()


def test_reconcile_is_idempotent(config, cache, roots):
    lib_file = write_file(roots["library_movies"] / "Bar (2011)" / "Bar.mkv")
    radarr = FakeRadarr([movie_payload(2, "Bar", 2011, lib_file.parent, lib_file)])
    engine = make_engine(config, cache, radarr)

    engine.run(scope=SCOPE_FULL)
    second = engine.run(scope=SCOPE_FULL)

    assert second.actions == []
    assert second.items_changed == 0


def test_stale_library_folder_is_pruned_and_managed_untouched(config, cache, roots):
    managed = write_file(roots["managed_movies"] / "Gone (1999)" / "Gone.mkv")
    lib_file = hardlink(managed, roots["library_movies"] / "Gone (1999)" / "Gone.mkv")
    radarr = FakeRadarr([])  # movie was removed from Radarr

    report = make_engine(config, cache, radarr).run(scope=SCOPE_FULL)

    assert managed.exists(), "managed file must never be deleted"
    assert not lib_file.exists()
    assert not lib_file.parent.exists()
    assert any(a.kind == "unlink" for a in report.actions)


def test_stale_library_folder_with_sole_copy_video_is_left(config, cache, roots):
    orphan = write_file(roots["library_movies"] / "Orphan (2000)" / "Orphan.mkv")
    radarr = FakeRadarr([])

    report = make_engine(config, cache, radarr).run(scope=SCOPE_FULL)

    assert orphan.exists()
    assert report.warnings


def test_missing_library_file_is_restored_from_cached_managed_folder(config, cache, roots):
    managed = write_file(roots["managed_movies"] / "Foo (2020)" / "Foo.mkv")
    cache.set_folder("radarr", 1, managed.parent)
    lib_folder = roots["library_movies"] / "Foo (2020)"
    lib_file = lib_folder / "Foo.mkv"  # does not exist on disk
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, lib_folder, lib_file)])

    report = make_engine(config, cache, radarr).run(scope=SCOPE_CONSISTENCY)

    assert lib_file.exists()
    assert inode(lib_file) == inode(managed)
    assert any(a.kind == "relink" for a in report.actions)
    assert 1 in radarr.refreshed


def test_missing_everywhere_warns_and_rescans_nothing_invalid(config, cache, roots):
    lib_folder = roots["library_movies"] / "Ghost (2015)"
    ghost_file = lib_folder / "Ghost.mkv"  # neither library nor managed side exists
    radarr = FakeRadarr([movie_payload(3, "Ghost", 2015, lib_folder, ghost_file)])

    report = make_engine(config, cache, radarr).run(scope=SCOPE_FULL)

    assert report.warnings
    assert not ghost_file.exists()
    assert not any(a.kind in {"link", "ingest_link"} for a in report.actions)


def test_dry_run_plans_but_does_not_touch_filesystem(config, cache, roots):
    lib_file = write_file(roots["library_movies"] / "Bar (2011)" / "Bar.mkv")
    radarr = FakeRadarr([movie_payload(2, "Bar", 2011, lib_file.parent, lib_file)])

    report = make_engine(config, cache, radarr).run(scope=SCOPE_FULL, dry_run=True)

    assert any(a.kind == "ingest_link" for a in report.actions)
    assert not (roots["managed_movies"] / "Bar (2011)").exists()


def test_movie_outside_configured_roots_is_ignored(config, cache, roots, tmp_path):
    foreign_file = write_file(tmp_path / "elsewhere" / "Zed (2001)" / "Zed.mkv")
    radarr = FakeRadarr([movie_payload(9, "Zed", 2001, foreign_file.parent, foreign_file)])

    report = make_engine(config, cache, radarr).run(scope=SCOPE_FULL)

    assert report.items_seen == 0
    assert report.actions == []


def test_cache_survives_reload(tmp_path, config, roots):
    cache_path = tmp_path / "idcache.json"
    cache = AdvisoryCache(cache_path)
    cache.set_folder("radarr", 7, roots["managed_movies"] / "X (2020)")
    cache.save()

    reloaded = AdvisoryCache(cache_path)
    assert reloaded.get_folder("radarr", 7) == roots["managed_movies"] / "X (2020)"
