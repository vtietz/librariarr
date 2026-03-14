from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

LOG = logging.getLogger(__name__)

JobCallable = Callable[[], dict[str, Any]]


@dataclass
class _QueuedJob:
    job_id: str
    func: JobCallable


class JobManager:
    def __init__(self, *, max_history: int = 200) -> None:
        self._max_history = max(50, int(max_history))
        self._jobs: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []
        self._queue: queue.Queue[_QueuedJob] = queue.Queue()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._stop.clear()
            self._worker = threading.Thread(
                target=self._run,
                daemon=True,
                name="librariarr-job-worker",
            )
            self._worker.start()
            LOG.info("Job manager started")

    def stop(self, *, timeout: float = 3.0) -> None:
        with self._lock:
            worker = self._worker
            self._worker = None
            self._stop.set()
            self._queue.put(_QueuedJob(job_id="__stop__", func=lambda: {}))

        if worker is not None and worker.is_alive():
            worker.join(timeout=timeout)
            if worker.is_alive():
                LOG.warning("Job manager worker did not stop within timeout")

    def submit(self, *, kind: str, func: JobCallable, payload: dict[str, Any] | None = None) -> str:
        self.start()
        job_id = uuid.uuid4().hex
        now = time.time()
        record = {
            "job_id": job_id,
            "kind": kind,
            "status": "queued",
            "queued_at": now,
            "started_at": None,
            "finished_at": None,
            "updated_at": now,
            "error": None,
            "result": None,
            "payload": payload or {},
        }
        with self._lock:
            self._jobs[job_id] = record
            self._order.append(job_id)
            self._trim_history_locked()
        self._queue.put(_QueuedJob(job_id=job_id, func=func))
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._jobs.get(job_id)
            if item is None:
                return None
            return dict(item)

    def list(self, *, limit: int = 20, status: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            ordered = [
                self._jobs[job_id] for job_id in reversed(self._order) if job_id in self._jobs
            ]
            if status is not None:
                ordered = [item for item in ordered if item.get("status") == status]
            return [dict(item) for item in ordered[: max(1, int(limit))]]

    def summary(self) -> dict[str, Any]:
        with self._lock:
            queued = 0
            running = 0
            succeeded = 0
            failed = 0
            latest_finished: dict[str, Any] | None = None

            for item in self._jobs.values():
                state = item.get("status")
                if state == "queued":
                    queued += 1
                elif state == "running":
                    running += 1
                elif state == "succeeded":
                    succeeded += 1
                elif state == "failed":
                    failed += 1

                finished_at = item.get("finished_at")
                if finished_at is None:
                    continue
                if latest_finished is None or float(finished_at) > float(
                    latest_finished.get("finished_at") or 0
                ):
                    latest_finished = item

            return {
                "queued": queued,
                "running": running,
                "active": queued + running,
                "succeeded": succeeded,
                "failed": failed,
                "latest_finished": dict(latest_finished) if latest_finished is not None else None,
                "updated_at": time.time(),
            }

    def _run(self) -> None:
        while not self._stop.is_set():
            queued_job = self._queue.get()
            if queued_job.job_id == "__stop__":
                continue
            self._mark_running(queued_job.job_id)
            try:
                result = queued_job.func()
            except Exception as exc:
                LOG.exception("Job %s failed", queued_job.job_id)
                self._mark_failed(queued_job.job_id, str(exc))
                continue
            self._mark_succeeded(queued_job.job_id, result)

    def _mark_running(self, job_id: str) -> None:
        now = time.time()
        with self._lock:
            item = self._jobs.get(job_id)
            if item is None:
                return
            item["status"] = "running"
            item["started_at"] = now
            item["updated_at"] = now

    def _mark_failed(self, job_id: str, error: str) -> None:
        now = time.time()
        with self._lock:
            item = self._jobs.get(job_id)
            if item is None:
                return
            item["status"] = "failed"
            item["finished_at"] = now
            item["updated_at"] = now
            item["error"] = error
            item["result"] = None

    def _mark_succeeded(self, job_id: str, result: dict[str, Any]) -> None:
        now = time.time()
        with self._lock:
            item = self._jobs.get(job_id)
            if item is None:
                return
            item["status"] = "succeeded"
            item["finished_at"] = now
            item["updated_at"] = now
            item["error"] = None
            item["result"] = result

    def _trim_history_locked(self) -> None:
        if len(self._order) <= self._max_history:
            return
        overflow = len(self._order) - self._max_history
        for _ in range(overflow):
            old_job_id = self._order.pop(0)
            self._jobs.pop(old_job_id, None)
