"""Supersession: an import may replace managed data, never destroy it.

The case these cover is the one that used to slip through: an Arr import whose
*filename matches* the managed file it replaces. Ordinary supersession works by
name (keep the ingested names, quarantine the rest), so a same-named upgrade was
overwritten in place by the hardlink itself — no quarantine, and irrecoverable
when the managed copy had no second link. The invariant is "managed files are
never deleted; the only destructive path is supersession → quarantine", so this
has to go through the same route as any other superseded file.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from librariarr.core.engine import SCOPE_CONSISTENCY, ReconcileEngine
from librariarr.core.fsops import TRASH_DIR_NAME

from .conftest import FakeRadarr, FakeSonarr, hardlink, movie_payload, series_payload, write_file


def aged(path: Path, seconds_ago: float = 3600) -> Path:
    stamp = time.time() - seconds_ago
    os.utime(path, (stamp, stamp))
    return path


def trashed(managed_root: Path, name: str) -> list[Path]:
    return list((managed_root / TRASH_DIR_NAME).rglob(name))


def same_named_upgrade(config, cache, roots, managed_content="old", library_content="new"):
    """A managed video, and a Radarr import of a different file under the very
    same name — the collision that used to lose data."""
    managed = aged(write_file(roots["managed_movies"] / "Foo (2020)" / "Foo.mkv", managed_content))
    cache.set_folder("radarr", 1, managed.parent)
    lib_file = write_file(roots["library_movies"] / "Foo (2020)" / "Foo.mkv", library_content)
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, lib_file.parent, lib_file)])
    engine = ReconcileEngine(config, radarr=radarr, sonarr=None, cache=cache)
    return engine, managed, lib_file


def test_same_named_upgrade_quarantines_the_managed_video(config, cache, roots):
    engine, managed, lib_file = same_named_upgrade(config, cache, roots)

    report = engine.run(scope=SCOPE_CONSISTENCY)

    assert managed.read_text() == "new", "the upgrade must be in place"
    assert managed.stat().st_ino == lib_file.stat().st_ino, "identity with Radarr holds"
    quarantined = trashed(roots["managed_movies"], "Foo.mkv")
    assert quarantined, "the replaced managed video must be recoverable, not destroyed"
    assert quarantined[0].read_text() == "old", "and it must still be the original data"
    assert any(action.kind == "trash" for action in report.actions)


def test_same_named_upgrade_honors_hard_delete_mode(config, cache, roots):
    config.ingest.replacement_delete_mode = "hard"
    engine, managed, lib_file = same_named_upgrade(config, cache, roots)

    report = engine.run(scope=SCOPE_CONSISTENCY)

    assert managed.stat().st_ino == lib_file.stat().st_ino
    assert not trashed(roots["managed_movies"], "Foo.mkv"), "hard mode does not quarantine"
    assert any(
        action.kind == "unlink" and "superseded" in action.detail for action in report.actions
    )


def test_same_named_upgrade_dry_run_destroys_nothing(config, cache, roots):
    engine, managed, lib_file = same_named_upgrade(config, cache, roots)
    original_inode = managed.stat().st_ino

    report = engine.run(scope=SCOPE_CONSISTENCY, dry_run=True)

    assert managed.read_text() == "old", "dry run must not touch the managed file"
    assert managed.stat().st_ino == original_inode
    assert not (roots["managed_movies"] / TRASH_DIR_NAME).exists()
    kinds = {action.kind for action in report.actions}
    assert {"trash", "ingest_link"} <= kinds, "but it must still report both steps"


def test_same_named_upgrade_is_reported_once_not_twice(config, cache, roots):
    """The rescue happens before the link; the name-based sweep afterwards must
    not report the same file again."""
    engine, _, _ = same_named_upgrade(config, cache, roots)

    report = engine.run(scope=SCOPE_CONSISTENCY)

    assert len([a for a in report.actions if a.kind == "trash"]) == 1


def test_reingest_of_the_same_file_quarantines_nothing(config, cache, roots):
    """Idempotency: once ingested, the managed file and Radarr's are one inode,
    so there is nothing to supersede on any later pass."""
    engine, _, _ = same_named_upgrade(config, cache, roots)
    engine.run(scope=SCOPE_CONSISTENCY)
    before = len(trashed(roots["managed_movies"], "Foo.mkv"))

    report = engine.run(scope=SCOPE_CONSISTENCY)

    assert report.actions == []
    assert len(trashed(roots["managed_movies"], "Foo.mkv")) == before


def test_same_named_extra_is_quarantined_rather_than_overwritten(config, cache, roots):
    """Ingest still wins for allowlisted extras, but the replaced copy — which
    may be the user's own subtitle — stays recoverable."""
    managed_video = aged(write_file(roots["managed_movies"] / "Foo (2020)" / "Foo.old.mkv", "old"))
    aged(write_file(roots["managed_movies"] / "Foo (2020)" / "Foo.srt", "user subs"))
    cache.set_folder("radarr", 1, managed_video.parent)
    lib_file = write_file(roots["library_movies"] / "Foo (2020)" / "Foo.new.mkv", "new")
    write_file(roots["library_movies"] / "Foo (2020)" / "Foo.srt", "arr subs")
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, lib_file.parent, lib_file)])

    ReconcileEngine(config, radarr=radarr, sonarr=None, cache=cache).run(scope=SCOPE_CONSISTENCY)

    assert (roots["managed_movies"] / "Foo (2020)" / "Foo.srt").read_text() == "arr subs"
    quarantined = trashed(roots["managed_movies"], "Foo.srt")
    assert quarantined and quarantined[0].read_text() == "user subs"


def test_same_named_episode_upgrade_quarantines_the_managed_episode(config, cache, roots):
    """Same hole on the Sonarr side: the supersede loop skips the target path, so
    only the pre-link rescue protects a same-named episode upgrade."""
    relative = "Season 01/Show.S01E01.mkv"
    managed_ep = aged(write_file(roots["managed_series"] / "Show (2020)" / relative, "old"))
    cache.set_folder("sonarr", 1, roots["managed_series"] / "Show (2020)")
    shadow_ep = write_file(roots["shadow_series"] / "Show (2020)" / relative, "new")
    sonarr = FakeSonarr(
        [series_payload(1, "Show", 2020, roots["shadow_series"] / "Show (2020)")],
        {1: [{"path": str(shadow_ep), "relativePath": relative}]},
    )

    report = ReconcileEngine(config, radarr=None, sonarr=sonarr, cache=cache).run(
        scope=SCOPE_CONSISTENCY
    )

    assert managed_ep.read_text() == "new"
    assert managed_ep.stat().st_ino == shadow_ep.stat().st_ino
    quarantined = trashed(roots["managed_series"], "Show.S01E01.mkv")
    assert quarantined, "the replaced managed episode must be recoverable"
    assert quarantined[0].read_text() == "old"
    assert any(action.kind == "trash" for action in report.actions)


def test_differently_named_upgrade_still_supersedes_by_name(config, cache, roots):
    """Regression guard for the path that already worked: the rescue must not
    have displaced the name-based sweep."""
    managed_old = aged(write_file(roots["managed_movies"] / "Foo (2020)" / "Foo.old.mkv", "old"))
    old_lib = hardlink(managed_old, roots["library_movies"] / "Foo (2020)" / "Foo.old.mkv")
    cache.set_folder("radarr", 1, managed_old.parent)
    old_lib.unlink()
    lib_file = write_file(roots["library_movies"] / "Foo (2020)" / "Foo.new.mkv", "new")
    radarr = FakeRadarr([movie_payload(1, "Foo", 2020, lib_file.parent, lib_file)])

    ReconcileEngine(config, radarr=radarr, sonarr=None, cache=cache).run(scope=SCOPE_CONSISTENCY)

    assert (roots["managed_movies"] / "Foo (2020)" / "Foo.new.mkv").exists()
    assert not managed_old.exists()
    assert trashed(roots["managed_movies"], "Foo.old.mkv")
