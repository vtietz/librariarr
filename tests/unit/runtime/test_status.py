import time

from librariarr.runtime.status import RuntimeStatusTracker


def test_fail_stale_running_task_marks_error_and_last_reconcile() -> None:
    tracker = RuntimeStatusTracker()
    tracker.mark_reconcile_started(trigger_source="filesystem", phase="inventory_fetched")

    snapshot = tracker.snapshot()
    current_task = snapshot["current_task"]
    # Simulate a stale running task that has not reported progress for > max age.
    current_task["updated_at"] = time.time() - 1200
    tracker._state["current_task"] = current_task  # noqa: SLF001

    changed = tracker.fail_stale_running_task(max_age_seconds=900)

    assert changed is True
    post = tracker.snapshot()
    assert post["current_task"]["state"] == "error"
    assert "timed out" in str(post["current_task"]["error"])
    assert post["last_reconcile"]["state"] == "error"
    assert post["last_reconcile"]["phase"] == "inventory_fetched"


def test_fail_stale_running_task_ignores_fresh_task() -> None:
    tracker = RuntimeStatusTracker()
    tracker.mark_reconcile_started(trigger_source="filesystem", phase="inventory_fetched")

    changed = tracker.fail_stale_running_task(max_age_seconds=900)

    assert changed is False
    post = tracker.snapshot()
    assert post["current_task"]["state"] == "running"
