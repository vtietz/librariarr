from __future__ import annotations

import logging
import threading
import time
from copy import deepcopy
from typing import Any

from ..runtime.status import RuntimeStatusTracker
from .dashboard_tasks import build_pending_tasks
from .discovery_cache import DiscoveryWarningsCache
from .jobs import JobManager
from .mapped_cache import MappedDirectoriesCache
from .state_store import PersistentStateStore

LOG = logging.getLogger(__name__)


class DashboardReadModel:
    _TASK_STALE_AFTER_SECONDS = 300
    _TASK_AUTO_FAIL_AFTER_SECONDS = 900

    def __init__(
        self,
        *,
        runtime_status_tracker: RuntimeStatusTracker,
        job_manager: JobManager,
        mapped_cache: MappedDirectoriesCache,
        discovery_cache: DiscoveryWarningsCache,
        state_store: PersistentStateStore,
        refresh_interval_seconds: float = 1.0,
    ) -> None:
        self.runtime_status_tracker = runtime_status_tracker
        self.job_manager = job_manager
        self.mapped_cache = mapped_cache
        self.discovery_cache = discovery_cache
        self.state_store = state_store
        self.refresh_interval_seconds = max(0.5, float(refresh_interval_seconds))
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot = state_store.load_dashboard() or {
            "health": {"status": "starting", "reasons": ["dashboard snapshot not ready"]},
            "updated_at": None,
        }
        self._failure_count = 0
        self._last_refresh_error: str | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run,
                daemon=True,
                name="librariarr-dashboard-read-model",
            )
            self._thread.start()

    def stop(self, *, timeout: float = 3.0) -> None:
        with self._lock:
            thread = self._thread
            self._thread = None
            self._stop.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._snapshot)

    def refresh_now(self) -> dict[str, Any]:
        payload = self._build_snapshot()
        with self._lock:
            self._snapshot = payload
        self.state_store.save_dashboard(payload)
        return deepcopy(payload)

    def _run(self) -> None:
        while not self._stop.wait(self.refresh_interval_seconds):
            try:
                self.refresh_now()
                self._failure_count = 0
                self._last_refresh_error = None
            except Exception as exc:
                self._failure_count += 1
                self._last_refresh_error = str(exc)
                LOG.exception("Dashboard read model refresh failed")
                with self._lock:
                    stale_snapshot = deepcopy(self._snapshot)
                    health = dict(stale_snapshot.get("health") or {})
                    reasons = list(health.get("reasons") or [])
                    reasons.append(f"read model refresh failed: {exc}")
                    health.update(
                        {
                            "status": "degraded",
                            "reasons": reasons,
                            "consecutive_refresh_failures": self._failure_count,
                            "last_refresh_error": str(exc),
                        }
                    )
                    stale_snapshot["health"] = health
                    self._snapshot = stale_snapshot
                    self.state_store.save_dashboard(stale_snapshot)

    def _build_snapshot(self) -> dict[str, Any]:
        self.runtime_status_tracker.fail_stale_running_task(
            max_age_seconds=self._TASK_AUTO_FAIL_AFTER_SECONDS,
            error="reconcile task timed out waiting for progress updates",
        )
        runtime_payload = self.runtime_status_tracker.snapshot()
        jobs_summary_payload = self.job_manager.summary()
        active_tasks_payload = self.job_manager.list_active_tasks(limit=30)
        mapped_snapshot = self.mapped_cache.snapshot()
        discovery_snapshot = self.discovery_cache.snapshot(limit=50)

        payload = deepcopy(runtime_payload)
        payload["known_links_in_memory"] = int(len(mapped_snapshot.get("items") or []))
        payload["mapped_cache"] = {
            "ready": bool(mapped_snapshot.get("ready")),
            "building": bool(mapped_snapshot.get("building")),
            "updated_at_ms": mapped_snapshot.get("updated_at_ms"),
            "entries_total": int(len(mapped_snapshot.get("items") or [])),
            "version": int(mapped_snapshot.get("version") or 0),
            "last_error": mapped_snapshot.get("last_error"),
            "last_build_duration_ms": mapped_snapshot.get("last_build_duration_ms"),
        }
        payload["discovery_cache"] = discovery_snapshot.get("cache")
        payload["tasks_active_total"] = len(active_tasks_payload)
        payload["pending_tasks"] = build_pending_tasks(
            runtime_payload=payload,
            authoritative_tasks=active_tasks_payload,
        )
        payload["health"] = self._build_health(payload, jobs_summary_payload)
        payload["updated_at"] = time.time()
        return payload

    def _build_health(
        self,
        payload: dict[str, Any],
        jobs_summary_payload: dict[str, Any],
    ) -> dict[str, Any]:
        now = time.time()
        reasons: list[str] = []
        status = "ok"

        current_task = payload.get("current_task") or {}
        reconcile_running = bool(
            isinstance(current_task, dict) and current_task.get("state") == "running"
        )

        if not bool(payload.get("runtime_running")):
            status = "degraded"
            reasons.append("background runtime is not running")

        status = self._apply_cache_health(
            status=status,
            reasons=reasons,
            cache_payload=payload.get("mapped_cache"),
            cache_name="mapped cache",
            stale_after_seconds=120,
            now=now,
            mark_not_ready=True,
            allow_stale_while_running=reconcile_running,
        )
        status = self._apply_cache_health(
            status=status,
            reasons=reasons,
            cache_payload=payload.get("discovery_cache"),
            cache_name="discovery cache",
            stale_after_seconds=180,
            now=now,
            mark_not_ready=False,
            allow_stale_while_running=reconcile_running,
        )

        if int(jobs_summary_payload.get("failed") or 0) > 0:
            status = "degraded"
            reasons.append(f"{jobs_summary_payload['failed']} background jobs failed")

        if self._failure_count > 0 and self._last_refresh_error:
            status = "degraded"
            reasons.append(self._last_refresh_error)

        if isinstance(current_task, dict) and current_task.get("state") == "running":
            updated_at = current_task.get("updated_at")
            if isinstance(updated_at, int | float):
                stale_age = max(0.0, now - float(updated_at))
                if stale_age > self._TASK_STALE_AFTER_SECONDS:
                    status = "degraded"
                    reasons.append(
                        f"reconcile task appears stuck ({int(stale_age)}s without progress update)"
                    )

        active = max(
            int(jobs_summary_payload.get("active") or 0),
            int(payload.get("tasks_active_total") or 0),
        )
        worker_busy = bool(active > 0 or payload.get("current_task", {}).get("state") == "running")
        return {
            "status": status,
            "reasons": reasons,
            "worker_busy": worker_busy,
            "jobs_active": active,
            "consecutive_refresh_failures": self._failure_count,
            "last_refresh_error": self._last_refresh_error,
        }

    def _apply_cache_health(
        self,
        *,
        status: str,
        reasons: list[str],
        cache_payload: Any,
        cache_name: str,
        stale_after_seconds: int,
        now: float,
        mark_not_ready: bool,
        allow_stale_while_running: bool,
    ) -> str:
        if not isinstance(cache_payload, dict):
            return status

        updated_at_ms = cache_payload.get("updated_at_ms")
        last_error = cache_payload.get("last_error")
        if last_error:
            status = "degraded"
            reasons.append(f"{cache_name} error: {last_error}")

        if isinstance(updated_at_ms, int | float):
            age_seconds = max(0.0, now - (float(updated_at_ms) / 1000.0))
            if age_seconds > stale_after_seconds:
                if allow_stale_while_running:
                    reasons.append(
                        f"{cache_name} is stale ({int(age_seconds)}s old); "
                        "refresh deferred while sync is running"
                    )
                else:
                    status = "degraded"
                    reasons.append(f"{cache_name} is stale ({int(age_seconds)}s old)")
            return status

        if mark_not_ready and not cache_payload.get("building"):
            status = "degraded"
            reasons.append(f"{cache_name} not ready")
        return status
