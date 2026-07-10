from __future__ import annotations

from librariarr.core.model import ReconcileReport
from librariarr.core.status import StatusTracker


def make_report(scope: str, dry_run: bool = False, unmatched_paths: list[str] | None = None):
    report = ReconcileReport(scope=scope, dry_run=dry_run)
    from librariarr.core.model import UnmatchedFolder

    for path in unmatched_paths or []:
        report.unmatched.append(UnmatchedFolder(path, "T", 2020, reason="no_match"))
    return report


def test_full_report_survives_subsequent_consistency_passes():
    tracker = StatusTracker()
    tracker.begin("full")
    tracker.finish(make_report("full", unmatched_paths=["/data/movies/X (2020)"]))
    tracker.begin("consistency")
    tracker.finish(make_report("consistency"))

    snapshot = tracker.snapshot()
    assert snapshot["last_report"]["scope"] == "consistency"
    assert snapshot["last_full_report"]["scope"] == "full"
    assert len(snapshot["last_full_report"]["unmatched"]) == 1
    assert snapshot["last_full_finished_at"] is not None


def test_dry_run_full_does_not_replace_full_report():
    tracker = StatusTracker()
    tracker.begin("full")
    tracker.finish(make_report("full", unmatched_paths=["/a"]))
    tracker.begin("full")
    tracker.finish(make_report("full", dry_run=True))

    assert len(tracker.snapshot()["last_full_report"]["unmatched"]) == 1


def test_progress_visible_while_running_and_cleared_after():
    tracker = StatusTracker()
    tracker.begin("full")
    tracker.progress("movies", 3, 10)
    assert tracker.snapshot()["progress"] == {"phase": "movies", "current": 3, "total": 10}
    tracker.finish(make_report("full"))
    assert tracker.snapshot()["progress"] is None
