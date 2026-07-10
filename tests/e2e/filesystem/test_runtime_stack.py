"""Production-shaped stack test: service + runtime loop + trigger + status.

Exercises the same wiring the deployed container runs — LibrariArrService
wrapping the engine, RuntimeLoop in a background thread, triggers issued the
way the webhook handler and the API issue them — over a real filesystem, with
only the Arr HTTP clients faked.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from librariarr.core.engine import ReconcileEngine
from librariarr.core.status import get_status_tracker
from librariarr.runtime.loop import RuntimeLoop
from librariarr.service import LibrariArrService

from .conftest import FakeRadarr, write_file

pytestmark = pytest.mark.fs_e2e


def wait_until(predicate, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


@pytest.fixture
def stack(config, cache, roots):
    config.runtime.debounce_seconds = 0
    config.runtime.consistency_interval_seconds = 3600
    config.runtime.full_interval_minutes = 600
    config.runtime.startup_scope = "off"

    radarr = FakeRadarr([])
    engine = ReconcileEngine(config, radarr=radarr, sonarr=None, cache=cache)
    service = LibrariArrService(config, engine=engine)
    loop = RuntimeLoop(service, config.runtime)
    stop = threading.Event()
    thread = threading.Thread(target=loop.run, args=(stop,), daemon=True)
    thread.start()
    try:
        yield radarr, service, loop
    finally:
        stop.set()
        thread.join(timeout=5)


def test_webhook_trigger_converges_new_import_end_to_end(stack, roots):
    radarr, service, loop = stack
    lib_file = write_file(roots["library_movies"] / "Hooked (2021)" / "Hooked.mkv")
    radarr.movies.append(
        {
            "id": 1,
            "title": "Hooked",
            "year": 2021,
            "path": str(lib_file.parent),
            "movieFile": {"path": str(lib_file)},
        }
    )

    # Exactly what POST /api/hooks/radarr does after payload validation.
    loop.trigger_consistency("webhook:Download")

    managed = roots["managed_movies"] / "Hooked (2021)" / "Hooked.mkv"
    assert wait_until(managed.exists), "webhook-triggered ingest did not converge"
    assert managed.stat().st_ino == lib_file.stat().st_ino

    snapshot = get_status_tracker().snapshot()
    assert snapshot["last_report"] is not None
    assert snapshot["history"], "the run must be recorded in status history"


def test_api_full_trigger_runs_discovery_and_reports_unmatched(stack, roots):
    radarr, service, loop = stack
    write_file(roots["managed_movies"] / "kids" / "Dropped Movie (2020)" / "Dropped.mkv")

    # Exactly what POST /api/reconcile {"scope": "full"} does.
    loop.trigger_full("api")

    def unmatched_reported() -> bool:
        report = get_status_tracker().snapshot().get("last_report") or {}
        return any(
            entry.get("parsed_title") == "Dropped Movie" for entry in report.get("unmatched", [])
        )

    assert wait_until(unmatched_reported), "full pass did not report the dropped folder"


def test_concurrent_triggers_are_serialized(stack, roots):
    radarr, service, loop = stack
    lib_file = write_file(roots["library_movies"] / "Racy (2022)" / "Racy.mkv")
    radarr.movies.append(
        {
            "id": 2,
            "title": "Racy",
            "year": 2022,
            "path": str(lib_file.parent),
            "movieFile": {"path": str(lib_file)},
        }
    )

    results = []

    def direct_reconcile():
        results.append(service.reconcile(scope="full"))

    # An API-style direct reconcile racing the loop's webhook trigger must not
    # corrupt anything: the service lock serializes them, both converge.
    thread = threading.Thread(target=direct_reconcile)
    thread.start()
    loop.trigger_consistency("webhook:Download")
    thread.join(timeout=15)

    managed = roots["managed_movies"] / "Racy (2022)" / "Racy.mkv"
    assert wait_until(managed.exists)
    assert results and not results[0].errors

    # And a follow-up pass confirms convergence (idempotency under racing).
    final = service.reconcile(scope="full")
    assert final.actions == []


def test_startup_scope_full_reconciles_before_loop_waits(config, cache, roots):
    config.runtime.debounce_seconds = 0
    config.runtime.consistency_interval_seconds = 3600
    config.runtime.full_interval_minutes = 600
    config.runtime.startup_scope = "full"

    lib_file = write_file(roots["library_movies"] / "Bootup (2020)" / "Bootup.mkv")
    radarr = FakeRadarr(
        [
            {
                "id": 3,
                "title": "Bootup",
                "year": 2020,
                "path": str(lib_file.parent),
                "movieFile": {"path": str(lib_file)},
            }
        ]
    )
    engine = ReconcileEngine(config, radarr=radarr, sonarr=None, cache=cache)
    service = LibrariArrService(config, engine=engine)
    loop = RuntimeLoop(service, config.runtime)
    stop = threading.Event()
    thread = threading.Thread(target=loop.run, args=(stop,), daemon=True)
    thread.start()
    try:
        managed = roots["managed_movies"] / "Bootup (2020)" / "Bootup.mkv"
        assert wait_until(managed.exists), "startup reconcile did not run"
        assert managed.stat().st_ino == Path(lib_file).stat().st_ino
    finally:
        stop.set()
        thread.join(timeout=5)
