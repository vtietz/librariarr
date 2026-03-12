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
        reconcile=lambda _paths=None: False,
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
        reconcile=lambda _paths=None: False,
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
        reconcile=lambda _paths=None: False,
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
        reconcile=lambda _paths=None: False,
        on_reconcile_error=lambda exc: None,
        logger=logging.getLogger("tests.runtime.loop"),
    )

    loop.mark_dirty(SimpleNamespace(event_type="modified", is_directory=False))
    assert schedule.last_event > 0.0


def test_runtime_sync_loop_mark_dirty_ignores_shadow_nested_event(tmp_path) -> None:
    schedule = ReconcileSchedule(debounce_seconds=5, maintenance_interval_seconds=None)
    shadow_root = tmp_path / "shadow"
    loop = RuntimeSyncLoop(
        nested_roots=[],
        shadow_roots=[shadow_root],
        schedule=schedule,
        reconcile=lambda _paths=None: False,
        on_reconcile_error=lambda exc: None,
        logger=logging.getLogger("tests.runtime.loop"),
    )

    loop.mark_dirty(
        SimpleNamespace(
            event_type="created",
            is_directory=False,
            src_path=str(shadow_root / "Movie (2024)" / "movie.mkv"),
        )
    )
    assert schedule.last_event == 0.0


def test_runtime_sync_loop_mark_dirty_accepts_shadow_top_level_event(tmp_path) -> None:
    schedule = ReconcileSchedule(debounce_seconds=5, maintenance_interval_seconds=None)
    shadow_root = tmp_path / "shadow"
    loop = RuntimeSyncLoop(
        nested_roots=[],
        shadow_roots=[shadow_root],
        schedule=schedule,
        reconcile=lambda _paths=None: False,
        on_reconcile_error=lambda exc: None,
        logger=logging.getLogger("tests.runtime.loop"),
    )

    loop.mark_dirty(
        SimpleNamespace(
            event_type="created",
            is_directory=True,
            src_path=str(shadow_root / "Movie (2024)"),
        )
    )
    assert schedule.last_event > 0.0


def test_runtime_sync_loop_handles_reconcile_exception() -> None:
    seen: list[Exception] = []

    def failing_reconcile(_paths=None) -> bool:
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

    result = loop._run_reconcile_with_handling("test failure")

    assert result is False
    assert len(seen) == 1
    assert isinstance(seen[0], RuntimeError)
    assert schedule.last_sync > 0.0


def test_runtime_sync_loop_returns_reconcile_pending_state() -> None:
    schedule = ReconcileSchedule(debounce_seconds=5, maintenance_interval_seconds=None)
    loop = RuntimeSyncLoop(
        nested_roots=[],
        shadow_roots=[],
        schedule=schedule,
        reconcile=lambda _paths=None: True,
        on_reconcile_error=lambda exc: None,
        logger=logging.getLogger("tests.runtime.loop"),
    )

    assert loop._run_reconcile_with_handling("test") is True


def test_runtime_sync_loop_tracks_dirty_paths_from_events(tmp_path) -> None:
    schedule = ReconcileSchedule(debounce_seconds=5, maintenance_interval_seconds=None)
    loop = RuntimeSyncLoop(
        nested_roots=[],
        shadow_roots=[],
        schedule=schedule,
        reconcile=lambda _paths=None: False,
        on_reconcile_error=lambda exc: None,
        logger=logging.getLogger("tests.runtime.loop"),
    )

    changed = tmp_path / "nested" / "Movie (2024)" / "file.mkv"
    loop.mark_dirty(
        SimpleNamespace(
            event_type="modified",
            is_directory=False,
            src_path=str(changed),
        )
    )

    assert loop._consume_dirty_paths() == {changed}


def test_runtime_sync_loop_passes_affected_paths_to_reconcile(tmp_path) -> None:
    captured: list[set] = []

    schedule = ReconcileSchedule(debounce_seconds=5, maintenance_interval_seconds=None)
    loop = RuntimeSyncLoop(
        nested_roots=[],
        shadow_roots=[],
        schedule=schedule,
        reconcile=lambda affected_paths=None: captured.append(affected_paths or set()) or False,
        on_reconcile_error=lambda exc: None,
        logger=logging.getLogger("tests.runtime.loop"),
    )

    changed = tmp_path / "nested" / "Movie (2024)" / "file.mkv"
    affected_paths = {changed}
    assert loop._run_reconcile_with_handling("test", affected_paths=affected_paths) is False

    assert captured == [affected_paths]
