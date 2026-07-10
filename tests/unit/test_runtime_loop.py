from __future__ import annotations

import threading
import time

from librariarr.config.models import RuntimeConfig
from librariarr.core.engine import SCOPE_CONSISTENCY, SCOPE_FULL
from librariarr.runtime.loop import RuntimeLoop


class RecordingService:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.event = threading.Event()

    def reconcile(self, *, scope: str, dry_run: bool = False):
        self.calls.append(scope)
        self.event.set()


def run_loop_briefly(loop: RuntimeLoop, action, timeout: float = 5.0) -> None:
    stop = threading.Event()
    thread = threading.Thread(target=loop.run, args=(stop,), daemon=True)
    thread.start()
    try:
        action()
        deadline = time.time() + timeout
        while time.time() < deadline and not loop.service.event.is_set():
            time.sleep(0.05)
    finally:
        stop.set()
        thread.join(timeout=5)


def test_startup_scope_off_runs_nothing_immediately():
    service = RecordingService()
    config = RuntimeConfig(
        startup_scope="off",
        debounce_seconds=0,
        consistency_interval_seconds=3600,
        full_interval_minutes=600,
    )
    loop = RuntimeLoop(service, config)
    run_loop_briefly(loop, lambda: time.sleep(0.3), timeout=0.5)
    assert service.calls == []


def test_webhook_trigger_runs_consistency_after_debounce():
    service = RecordingService()
    config = RuntimeConfig(
        startup_scope="off",
        debounce_seconds=0,
        consistency_interval_seconds=3600,
        full_interval_minutes=600,
    )
    loop = RuntimeLoop(service, config)
    run_loop_briefly(loop, lambda: loop.trigger_consistency("test"))
    assert SCOPE_CONSISTENCY in service.calls


def test_full_trigger_wins_over_consistency():
    service = RecordingService()
    config = RuntimeConfig(
        startup_scope="off",
        debounce_seconds=0,
        consistency_interval_seconds=3600,
        full_interval_minutes=600,
    )
    loop = RuntimeLoop(service, config)

    def both():
        loop.trigger_consistency("a")
        loop.trigger_full("b")

    run_loop_briefly(loop, both)
    assert service.calls[0] == SCOPE_FULL


def test_startup_scope_full_runs_full_pass():
    service = RecordingService()
    config = RuntimeConfig(
        startup_scope="full",
        debounce_seconds=0,
        consistency_interval_seconds=3600,
        full_interval_minutes=600,
    )
    loop = RuntimeLoop(service, config)
    run_loop_briefly(loop, lambda: None)
    assert service.calls[:1] == [SCOPE_FULL]
