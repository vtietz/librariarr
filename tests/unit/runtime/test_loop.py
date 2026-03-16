import errno
import logging
from types import SimpleNamespace

import requests

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


def test_runtime_sync_loop_mark_dirty_accepts_shadow_nested_event_for_real_dir(tmp_path) -> None:
    schedule = ReconcileSchedule(debounce_seconds=5, maintenance_interval_seconds=None)
    shadow_root = tmp_path / "shadow"
    (shadow_root / "Movie (2024)").mkdir(parents=True)
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
    assert schedule.last_event > 0.0


def test_runtime_sync_loop_mark_dirty_ignores_shadow_nested_event_under_symlink(tmp_path) -> None:
    schedule = ReconcileSchedule(debounce_seconds=5, maintenance_interval_seconds=None)
    shadow_root = tmp_path / "shadow"
    target_root = tmp_path / "target"
    target_movie = target_root / "Movie (2024)"
    target_movie.mkdir(parents=True)
    shadow_root.mkdir(parents=True)
    (shadow_root / "Movie (2024)").symlink_to(target_movie, target_is_directory=True)

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


def test_runtime_sync_loop_handles_reconcile_exception(caplog) -> None:
    seen: list[Exception] = []

    def failing_reconcile(_paths=None) -> bool:
        raise RuntimeError("boom")

    schedule = ReconcileSchedule(debounce_seconds=5, maintenance_interval_seconds=None)
    logger = logging.getLogger("tests.runtime.loop")
    loop = RuntimeSyncLoop(
        nested_roots=[],
        shadow_roots=[],
        schedule=schedule,
        reconcile=failing_reconcile,
        on_reconcile_error=lambda exc: seen.append(exc),
        logger=logger,
    )

    with caplog.at_level(logging.ERROR, logger=logger.name):
        result = loop._run_reconcile_with_handling("test failure")

    assert result is False
    assert len(seen) == 1
    assert isinstance(seen[0], RuntimeError)
    assert schedule.last_sync > 0.0
    records = [record for record in caplog.records if record.message == "test failure"]
    assert len(records) == 1
    assert records[0].exc_info is not None


def test_runtime_sync_loop_logs_request_exception_as_single_line(caplog) -> None:
    seen: list[Exception] = []

    def failing_reconcile(_paths=None) -> bool:
        raise requests.Timeout("read timed out")

    schedule = ReconcileSchedule(debounce_seconds=5, maintenance_interval_seconds=None)
    logger = logging.getLogger("tests.runtime.loop.request")
    loop = RuntimeSyncLoop(
        nested_roots=[],
        shadow_roots=[],
        schedule=schedule,
        reconcile=failing_reconcile,
        on_reconcile_error=lambda exc: seen.append(exc),
        logger=logger,
    )

    with caplog.at_level(logging.WARNING, logger=logger.name):
        result = loop._run_reconcile_with_handling("test failure")

    assert result is False
    assert len(seen) == 1
    assert isinstance(seen[0], requests.Timeout)
    assert schedule.last_sync > 0.0

    records = [
        record
        for record in caplog.records
        if record.levelname == "WARNING" and record.message.startswith("test failure: ")
    ]
    assert len(records) == 1
    assert "read timed out" in records[0].message
    assert "Timeout" in records[0].message
    assert records[0].exc_info is None


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


def test_runtime_sync_loop_logs_reconcile_mode_for_event_cycle(caplog) -> None:
    schedule = ReconcileSchedule(debounce_seconds=0, maintenance_interval_seconds=None)
    logger = logging.getLogger("tests.runtime.loop.mode")
    loop = RuntimeSyncLoop(
        nested_roots=[],
        shadow_roots=[],
        schedule=schedule,
        reconcile=lambda _paths=None: False,
        on_reconcile_error=lambda exc: None,
        logger=logger,
    )

    schedule.mark_event()

    with caplog.at_level(logging.INFO, logger=logger.name):
        loop._run_due_reconcile_cycle(poll_triggered=False)

    messages = [record.message for record in caplog.records]
    assert any(
        message.startswith("Starting reconcile cycle (mode=incremental, trigger=filesystem)")
        for message in messages
    )


def test_on_reconcile_complete_callback_called_after_success() -> None:
    schedule = ReconcileSchedule(debounce_seconds=0, maintenance_interval_seconds=None)
    completed: list[bool] = []
    loop = RuntimeSyncLoop(
        nested_roots=[],
        shadow_roots=[],
        schedule=schedule,
        reconcile=lambda _paths=None: False,
        on_reconcile_error=lambda exc: None,
        logger=logging.getLogger("tests.runtime.loop.complete"),
        on_reconcile_complete=lambda: completed.append(True),
    )
    schedule.mark_event()
    loop._run_due_reconcile_cycle(poll_triggered=False)
    assert completed == [True]


def test_on_reconcile_complete_not_called_on_failure() -> None:
    schedule = ReconcileSchedule(debounce_seconds=0, maintenance_interval_seconds=None)
    completed: list[bool] = []
    errors: list[Exception] = []
    loop = RuntimeSyncLoop(
        nested_roots=[],
        shadow_roots=[],
        schedule=schedule,
        reconcile=lambda _paths=None: (_ for _ in ()).throw(RuntimeError("boom")),
        on_reconcile_error=lambda exc: errors.append(exc),
        logger=logging.getLogger("tests.runtime.loop.complete_err"),
        on_reconcile_complete=lambda: completed.append(True),
    )
    schedule.mark_event()
    loop._run_due_reconcile_cycle(poll_triggered=False)
    assert completed == []
    assert len(errors) == 1


def test_runtime_sync_loop_falls_back_to_polling_on_inotify_limit(
    tmp_path,
    monkeypatch,
    caplog,
) -> None:
    class BrokenObserver:
        def schedule(self, *_args, **_kwargs) -> None:
            return None

        def start(self) -> None:
            raise OSError(errno.ENOSPC, "inotify watch limit reached")

        def stop(self) -> None:
            return None

        def join(self) -> None:
            return None

    class WorkingPollingObserver:
        started = False

        def schedule(self, *_args, **_kwargs) -> None:
            return None

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            return None

        def join(self) -> None:
            return None

    monkeypatch.setattr("librariarr.runtime.loop.Observer", BrokenObserver)
    monkeypatch.setattr("librariarr.runtime.loop.PollingObserver", WorkingPollingObserver)

    stop_event = SimpleNamespace(is_set=lambda: True, wait=lambda _timeout: True)
    schedule = ReconcileSchedule(debounce_seconds=1, maintenance_interval_seconds=None)
    logger = logging.getLogger("tests.runtime.loop.polling")
    loop = RuntimeSyncLoop(
        nested_roots=[tmp_path / "nested"],
        shadow_roots=[tmp_path / "shadow"],
        schedule=schedule,
        reconcile=lambda _paths=None: False,
        on_reconcile_error=lambda exc: None,
        logger=logger,
    )

    with caplog.at_level(logging.INFO, logger=logger.name):
        loop.run(stop_event=stop_event)

    messages = [record.message for record in caplog.records]
    assert any(
        "Inotify watch limit reached; falling back to polling observer mode" in m for m in messages
    )
    assert any(m == "Runtime observer mode: polling" for m in messages)
