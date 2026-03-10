import logging
from types import SimpleNamespace

from librariarr.runtime.loop import ReconcileSchedule, RuntimeSyncLoop


def test_reconcile_schedule_event_due_after_debounce() -> None:
    schedule = ReconcileSchedule(debounce_seconds=5, maintenance_interval_seconds=None)
    schedule.mark_event(now=10)

    maintenance_due, event_due = schedule.due(now=14)
    assert maintenance_due is False
    assert event_due is False

    maintenance_due, event_due = schedule.due(now=15)
    assert maintenance_due is False
    assert event_due is True


def test_reconcile_schedule_maintenance_due_after_interval() -> None:
    schedule = ReconcileSchedule(debounce_seconds=5, maintenance_interval_seconds=60)
    schedule.mark_sync(now=100)

    maintenance_due, event_due = schedule.due(now=159)
    assert maintenance_due is False
    assert event_due is False

    maintenance_due, event_due = schedule.due(now=160)
    assert maintenance_due is True
    assert event_due is False


def test_runtime_sync_loop_mark_dirty_sets_event() -> None:
    schedule = ReconcileSchedule(debounce_seconds=5, maintenance_interval_seconds=None)
    loop = RuntimeSyncLoop(
        nested_roots=[],
        shadow_roots=[],
        schedule=schedule,
        reconcile=lambda: None,
        on_reconcile_error=lambda exc: None,
        logger=logging.getLogger("tests.runtime.loop"),
    )

    assert schedule.last_event == 0.0
    loop.mark_dirty()
    assert schedule.last_event > 0.0


def test_runtime_sync_loop_mark_dirty_ignores_opened_event() -> None:
    schedule = ReconcileSchedule(debounce_seconds=5, maintenance_interval_seconds=None)
    loop = RuntimeSyncLoop(
        nested_roots=[],
        shadow_roots=[],
        schedule=schedule,
        reconcile=lambda: None,
        on_reconcile_error=lambda exc: None,
        logger=logging.getLogger("tests.runtime.loop"),
    )

    loop.mark_dirty(SimpleNamespace(event_type="opened", is_directory=False))
    assert schedule.last_event == 0.0


def test_runtime_sync_loop_mark_dirty_ignores_directory_modified_event() -> None:
    schedule = ReconcileSchedule(debounce_seconds=5, maintenance_interval_seconds=None)
    loop = RuntimeSyncLoop(
        nested_roots=[],
        shadow_roots=[],
        schedule=schedule,
        reconcile=lambda: None,
        on_reconcile_error=lambda exc: None,
        logger=logging.getLogger("tests.runtime.loop"),
    )

    loop.mark_dirty(SimpleNamespace(event_type="modified", is_directory=True))
    assert schedule.last_event == 0.0


def test_runtime_sync_loop_mark_dirty_accepts_file_modified_event() -> None:
    schedule = ReconcileSchedule(debounce_seconds=5, maintenance_interval_seconds=None)
    loop = RuntimeSyncLoop(
        nested_roots=[],
        shadow_roots=[],
        schedule=schedule,
        reconcile=lambda: None,
        on_reconcile_error=lambda exc: None,
        logger=logging.getLogger("tests.runtime.loop"),
    )

    loop.mark_dirty(SimpleNamespace(event_type="modified", is_directory=False))
    assert schedule.last_event > 0.0


def test_runtime_sync_loop_handles_reconcile_exception() -> None:
    seen: list[Exception] = []

    def failing_reconcile() -> None:
        raise RuntimeError("boom")

    schedule = ReconcileSchedule(debounce_seconds=5, maintenance_interval_seconds=None)
    loop = RuntimeSyncLoop(
        nested_roots=[],
        shadow_roots=[],
        schedule=schedule,
        reconcile=failing_reconcile,
        on_reconcile_error=lambda exc: seen.append(exc),
        logger=logging.getLogger("tests.runtime.loop"),
    )

    loop._run_reconcile_with_handling("test failure")

    assert len(seen) == 1
    assert isinstance(seen[0], RuntimeError)
    assert schedule.last_sync > 0.0
