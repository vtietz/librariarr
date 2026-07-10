from __future__ import annotations

import os
from pathlib import Path

from librariarr.core.engine import SCOPE_CONSISTENCY, SCOPE_FULL, ReconcileEngine
from librariarr.core.fsops import TRASH_DIR_NAME
from librariarr.core.series import episode_key

from .conftest import FakeSonarr, hardlink, series_payload, write_file


def make_engine(config, cache, sonarr: FakeSonarr) -> ReconcileEngine:
    return ReconcileEngine(config, radarr=None, sonarr=sonarr, cache=cache)


def inode(path: Path) -> int:
    return path.stat().st_ino


def episode_file(path: Path, relative: str) -> dict:
    return {"path": str(path), "relativePath": relative}


def test_episode_key_parsing():
    assert episode_key("Show.S01E02.mkv") == (1, 2)
    assert episode_key("show s2e03 name.mkv") == (2, 3)
    assert episode_key("no-episode.mkv") is None


def test_steady_state_series_produces_no_actions(config, cache, roots):
    managed = write_file(
        roots["managed_series"] / "kids" / "Show (2020)" / "Season 01" / "Show.S01E01.mkv"
    )
    shadow = hardlink(
        managed, roots["shadow_series"] / "Show (2020)" / "Season 01" / "Show.S01E01.mkv"
    )
    cache.set_folder("sonarr", 1, managed.parent.parent)
    sonarr = FakeSonarr(
        [series_payload(1, "Show", 2020, roots["shadow_series"] / "Show (2020)")],
        {1: [episode_file(shadow, "Season 01/Show.S01E01.mkv")]},
    )

    report = make_engine(config, cache, sonarr).run(scope=SCOPE_CONSISTENCY)

    assert report.actions == []
    assert report.errors == []


def test_new_series_import_is_ingested(config, cache, roots):
    shadow_folder = roots["shadow_series"] / "Fresh (2022)"
    shadow_ep = write_file(shadow_folder / "Season 01" / "Fresh.S01E01.mkv")
    sonarr = FakeSonarr(
        [series_payload(2, "Fresh", 2022, shadow_folder)],
        {2: [episode_file(shadow_ep, "Season 01/Fresh.S01E01.mkv")]},
    )

    make_engine(config, cache, sonarr).run(scope=SCOPE_CONSISTENCY)

    managed_copy = roots["managed_series"] / "Fresh (2022)" / "Season 01" / "Fresh.S01E01.mkv"
    assert managed_copy.exists()
    assert inode(managed_copy) == inode(shadow_ep)
    assert cache.get_folder("sonarr", 2) == roots["managed_series"] / "Fresh (2022)"


def test_episode_upgrade_ingests_and_quarantines_old(config, cache, roots):
    series_folder = roots["managed_series"] / "Show (2020)"
    managed_old = write_file(series_folder / "Season 01" / "Show.S01E01.old.mkv", "old")
    cache.set_folder("sonarr", 1, series_folder)
    shadow_folder = roots["shadow_series"] / "Show (2020)"
    shadow_new = write_file(shadow_folder / "Season 01" / "Show.S01E01.remux.mkv", "new")
    os.utime(managed_old, (1000, 1000))
    os.utime(shadow_new, (2000, 2000))
    sonarr = FakeSonarr(
        [series_payload(1, "Show", 2020, shadow_folder)],
        {1: [episode_file(shadow_new, "Season 01/Show.S01E01.remux.mkv")]},
    )

    report = make_engine(config, cache, sonarr).run(scope=SCOPE_CONSISTENCY)

    managed_new = series_folder / "Season 01" / "Show.S01E01.remux.mkv"
    assert managed_new.exists()
    assert inode(managed_new) == inode(shadow_new)
    assert not managed_old.exists()
    trash = roots["managed_series"] / TRASH_DIR_NAME
    assert any(trash.rglob("Show.S01E01.old.mkv"))
    assert any(a.kind == "trash" for a in report.actions)


def test_episode_upgrade_does_not_touch_other_episodes(config, cache, roots):
    series_folder = roots["managed_series"] / "Show (2020)"
    other_ep = write_file(series_folder / "Season 01" / "Show.S01E02.mkv", "other")
    cache.set_folder("sonarr", 1, series_folder)
    shadow_folder = roots["shadow_series"] / "Show (2020)"
    shadow_other = hardlink(other_ep, shadow_folder / "Season 01" / "Show.S01E02.mkv")
    shadow_new = write_file(shadow_folder / "Season 01" / "Show.S01E01.mkv", "new")
    sonarr = FakeSonarr(
        [series_payload(1, "Show", 2020, shadow_folder)],
        {
            1: [
                episode_file(shadow_new, "Season 01/Show.S01E01.mkv"),
                episode_file(shadow_other, "Season 01/Show.S01E02.mkv"),
            ]
        },
    )

    make_engine(config, cache, sonarr).run(scope=SCOPE_CONSISTENCY)

    assert other_ep.exists(), "unrelated episode must not be superseded"
    managed_new = series_folder / "Season 01" / "Show.S01E01.mkv"
    assert managed_new.exists()


def test_user_replaced_episode_wins_when_newer(config, cache, roots):
    series_folder = roots["managed_series"] / "Show (2020)"
    managed_new = write_file(series_folder / "Season 01" / "Show.S01E01.better.mkv", "better")
    cache.set_folder("sonarr", 1, series_folder)
    shadow_folder = roots["shadow_series"] / "Show (2020)"
    shadow_old = write_file(shadow_folder / "Season 01" / "Show.S01E01.mkv", "old")
    os.utime(shadow_old, (1000, 1000))
    os.utime(managed_new, (2000, 2000))
    sonarr = FakeSonarr(
        [series_payload(1, "Show", 2020, shadow_folder)],
        {1: [episode_file(shadow_old, "Season 01/Show.S01E01.mkv")]},
    )

    report = make_engine(config, cache, sonarr).run(scope=SCOPE_CONSISTENCY)

    assert inode(shadow_old) == inode(managed_new)
    assert any(a.kind == "relink" for a in report.actions)
    assert 1 in sonarr.refreshed


def test_user_added_episode_is_projected_and_rescanned(config, cache, roots):
    series_folder = roots["managed_series"] / "Show (2020)"
    known = write_file(series_folder / "Season 01" / "Show.S01E01.mkv")
    new_ep = write_file(series_folder / "Season 01" / "Show.S01E02.mkv")
    shadow_folder = roots["shadow_series"] / "Show (2020)"
    shadow_known = hardlink(known, shadow_folder / "Season 01" / "Show.S01E01.mkv")
    cache.set_folder("sonarr", 1, series_folder)
    sonarr = FakeSonarr(
        [series_payload(1, "Show", 2020, shadow_folder)],
        {1: [episode_file(shadow_known, "Season 01/Show.S01E01.mkv")]},
    )

    make_engine(config, cache, sonarr).run(scope=SCOPE_CONSISTENCY)

    projected = shadow_folder / "Season 01" / "Show.S01E02.mkv"
    assert projected.exists()
    assert inode(projected) == inode(new_ep)
    assert 1 in sonarr.refreshed, "Sonarr must rescan to import the projected episode"


def test_series_folder_derived_from_index_after_user_move(config, cache, roots):
    managed = write_file(
        roots["managed_series"] / "moved-bucket" / "Show (2020)" / "Season 01" / "Show.S01E01.mkv"
    )
    shadow_folder = roots["shadow_series"] / "Show (2020)"
    shadow_ep = hardlink(managed, shadow_folder / "Season 01" / "Show.S01E01.mkv")
    sonarr = FakeSonarr(
        [series_payload(1, "Show", 2020, shadow_folder)],
        {1: [episode_file(shadow_ep, "Season 01/Show.S01E01.mkv")]},
    )

    make_engine(config, cache, sonarr).run(scope=SCOPE_FULL)

    expected = roots["managed_series"] / "moved-bucket" / "Show (2020)"
    assert cache.get_folder("sonarr", 1) == expected


def test_stale_shadow_folder_is_pruned(config, cache, roots):
    managed = write_file(roots["managed_series"] / "Gone (1999)" / "Season 01" / "Gone.S01E01.mkv")
    shadow_ep = hardlink(
        managed, roots["shadow_series"] / "Gone (1999)" / "Season 01" / "Gone.S01E01.mkv"
    )
    sonarr = FakeSonarr([], {})

    make_engine(config, cache, sonarr).run(scope=SCOPE_FULL)

    assert managed.exists()
    assert not shadow_ep.exists()
    assert not (roots["shadow_series"] / "Gone (1999)").exists()


def test_series_auto_add_confident_match(config, cache, roots):
    config.sonarr.auto_add_unmatched = True
    config.sonarr.auto_add_quality_profile_id = 3
    managed = write_file(
        roots["managed_series"] / "New Show (2023)" / "Season 01" / "New.Show.S01E01.mkv"
    )
    sonarr = FakeSonarr([], {})
    sonarr.lookup_results = [{"title": "New Show", "year": 2023, "tvdbId": 77}]

    report = make_engine(config, cache, sonarr).run(scope=SCOPE_FULL)

    assert len(sonarr.added) == 1
    added = sonarr.added[0]
    projected = Path(added["path"]) / "Season 01" / "New.Show.S01E01.mkv"
    assert projected.exists()
    assert inode(projected) == inode(managed)
    assert added["id"] in sonarr.refreshed
    assert not report.unmatched


def test_missing_shadow_episode_is_restored_by_filename(config, cache, roots):
    series_folder = roots["managed_series"] / "Show (2020)"
    managed_ep = write_file(series_folder / "Season 01" / "Show.S01E01.mkv")
    cache.set_folder("sonarr", 1, series_folder)
    shadow_folder = roots["shadow_series"] / "Show (2020)"
    shadow_ep = shadow_folder / "Season 01" / "Show.S01E01.mkv"  # missing on disk
    sonarr = FakeSonarr(
        [series_payload(1, "Show", 2020, shadow_folder)],
        {1: [episode_file(shadow_ep, "Season 01/Show.S01E01.mkv")]},
    )

    report = make_engine(config, cache, sonarr).run(scope=SCOPE_CONSISTENCY)

    assert shadow_ep.exists()
    assert inode(shadow_ep) == inode(managed_ep)
    assert any(a.kind == "relink" for a in report.actions)
    assert 1 in sonarr.refreshed


def test_series_extras_are_projected_and_unknown_left_alone(config, cache, roots):
    series_folder = roots["managed_series"] / "Show (2020)"
    managed_ep = write_file(series_folder / "Season 01" / "Show.S01E01.mkv")
    write_file(series_folder / "tvshow.nfo")
    write_file(series_folder / "random.txt")
    cache.set_folder("sonarr", 1, series_folder)
    shadow_folder = roots["shadow_series"] / "Show (2020)"
    shadow_ep = hardlink(managed_ep, shadow_folder / "Season 01" / "Show.S01E01.mkv")
    sonarr = FakeSonarr(
        [series_payload(1, "Show", 2020, shadow_folder)],
        {1: [episode_file(shadow_ep, "Season 01/Show.S01E01.mkv")]},
    )

    make_engine(config, cache, sonarr).run(scope=SCOPE_CONSISTENCY)

    assert (shadow_folder / "tvshow.nfo").exists()
    assert not (shadow_folder / "random.txt").exists()


def test_stale_shadow_folder_with_sole_copy_episode_is_left(config, cache, roots):
    orphan = write_file(
        roots["shadow_series"] / "Orphan (2001)" / "Season 01" / "Orphan.S01E01.mkv"
    )
    sonarr = FakeSonarr([], {})

    report = make_engine(config, cache, sonarr).run(scope=SCOPE_FULL)

    assert orphan.exists()
    assert report.warnings


def test_fileless_sonarr_series_is_adopted_by_matching_folder(config, cache, roots):
    managed_ep = write_file(
        roots["managed_series"] / "Adopt Show (2019)" / "Season 01" / "Adopt.S01E01.mkv"
    )
    shadow_folder = roots["shadow_series"] / "Adopt Show (2019)"
    fileless = series_payload(6, "Adopt Show", 2019, shadow_folder, episode_file_count=0)
    sonarr = FakeSonarr([fileless], {6: []})

    report = make_engine(config, cache, sonarr).run(scope=SCOPE_FULL)

    projected = shadow_folder / "Season 01" / "Adopt.S01E01.mkv"
    assert projected.exists()
    assert inode(projected) == inode(managed_ep)
    assert 6 in sonarr.refreshed
    assert cache.get_folder("sonarr", 6) == managed_ep.parent.parent
    assert not report.unmatched


def test_series_unmatched_reported_when_auto_add_disabled(config, cache, roots):
    write_file(
        roots["managed_series"] / "grouping" / "Unknown Show" / "Season 02" / "Unknown.S02E05.mkv"
    )
    sonarr = FakeSonarr([], {})

    report = make_engine(config, cache, sonarr).run(scope=SCOPE_FULL)

    assert len(report.unmatched) == 1
    assert report.unmatched[0].path.endswith("Unknown Show")
    assert report.unmatched[0].reason == "auto_add_disabled"
