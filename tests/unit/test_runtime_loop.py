from __future__ import annotations

import threading
import time

from librariarr.config.models import RuntimeConfig
from librariarr.core.engine import SCOPE_CONSISTENCY, SCOPE_FULL, SCOPE_TARGETED
from librariarr.runtime.loop import RuntimeLoop


class RecordingService:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.targeted: list[tuple[list[int], list[int]]] = []
        self.drift_polls = 0
        self.event = threading.Event()

    def reconcile(self, *, scope: str, dry_run: bool = False):
        self.calls.append(scope)
        self.event.set()

    def reconcile_targeted(self, *, radarr_movie_ids=(), sonarr_series_ids=(), dry_run=False):
        self.calls.append(SCOPE_TARGETED)
        self.targeted.append((list(radarr_movie_ids), list(sonarr_series_ids)))
        self.event.set()

    def reconcile_bucket_drift(self, *, dry_run: bool = False):
        self.drift_polls += 1
        self.event.set()
        return None


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


def test_targeted_trigger_runs_only_the_named_items():
    service = RecordingService()
    config = RuntimeConfig(
        startup_scope="off",
        debounce_seconds=0,
        consistency_interval_seconds=3600,
        full_interval_minutes=600,
    )
    loop = RuntimeLoop(service, config)
    run_loop_briefly(loop, lambda: loop.trigger_targeted("webhook:Download", movie_ids=[4473]))
    assert service.calls == [SCOPE_TARGETED]
    assert service.targeted == [([4473], [])]


def test_targeted_triggers_in_one_window_collapse_into_a_single_pass():
    """A download burst for the same movie must not queue N passes."""
    service = RecordingService()
    config = RuntimeConfig(
        startup_scope="off",
        debounce_seconds=0,
        consistency_interval_seconds=3600,
        full_interval_minutes=600,
    )
    loop = RuntimeLoop(service, config)

    def burst():
        loop.trigger_targeted("a", movie_ids=[7])
        loop.trigger_targeted("b", movie_ids=[7])
        loop.trigger_targeted("c", movie_ids=[9], series_ids=[3])

    run_loop_briefly(loop, burst)
    assert service.calls == [SCOPE_TARGETED]
    assert service.targeted == [([7, 9], [3])]


def test_consistency_trigger_widens_a_pending_targeted_pass():
    """A trigger without an item id covers everything the ids would have."""
    service = RecordingService()
    config = RuntimeConfig(
        startup_scope="off",
        debounce_seconds=0,
        consistency_interval_seconds=3600,
        full_interval_minutes=600,
    )
    loop = RuntimeLoop(service, config)

    def both():
        loop.trigger_targeted("webhook:Download", movie_ids=[1])
        loop.trigger_consistency("webhook:Test")

    run_loop_briefly(loop, both)
    assert service.calls[0] == SCOPE_CONSISTENCY
    assert service.targeted == []


def test_bucket_drift_poll_can_be_disabled():
    service = RecordingService()
    config = RuntimeConfig(
        startup_scope="off",
        debounce_seconds=0,
        consistency_interval_seconds=3600,
        full_interval_minutes=600,
        bucket_drift_interval_seconds=0,
    )
    loop = RuntimeLoop(service, config)
    run_loop_briefly(loop, lambda: time.sleep(0.3), timeout=0.5)
    assert service.drift_polls == 0
    assert service.calls == []


def test_loop_survives_a_failing_targeted_pass():
    class FailingService(RecordingService):
        def reconcile_targeted(self, **kwargs):
            self.calls.append(SCOPE_TARGETED)
            self.event.set()
            raise RuntimeError("boom")

    service = FailingService()
    config = RuntimeConfig(
        startup_scope="off",
        debounce_seconds=0,
        consistency_interval_seconds=3600,
        full_interval_minutes=600,
    )
    loop = RuntimeLoop(service, config)
    run_loop_briefly(loop, lambda: loop.trigger_targeted("x", movie_ids=[1]))
    assert service.calls == [SCOPE_TARGETED]

    # The loop is still alive and accepts the next trigger.
    service.event.clear()
    run_loop_briefly(loop, lambda: loop.trigger_consistency("after"))
    assert SCOPE_CONSISTENCY in service.calls


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
