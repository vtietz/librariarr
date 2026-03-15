from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .state_store import PersistentStateStore

LOG = logging.getLogger(__name__)

JobCallable = Callable[[], dict[str, Any]]


@dataclass
class _QueuedJob:
    job_id: str
    func: JobCallable


class JobManager:
    def __init__(
        self,
        *,
        max_history: int = 200,
        state_store: PersistentStateStore | None = None,
    ) -> None:
        self._max_history = max(50, int(max_history))
        self._state_store = state_store
        self._jobs, self._order, persist_loaded_jobs = self._load_persisted_jobs()
        self._queue: queue.Queue[_QueuedJob] = queue.Queue()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        if persist_loaded_jobs:
            self._persist_locked()

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

    def submit(
        self,
        *,
        kind: str,
        func: JobCallable,
        name: str | None = None,
        source: str = "job-manager",
        detail: str | None = None,
        payload: dict[str, Any] | None = None,
        history_visible: bool = True,
    ) -> str:
        self.start()
        job_id = uuid.uuid4().hex
        now = time.time()
        record = {
            "job_id": job_id,
            "kind": kind,
            "name": name or kind,
            "source": source,
            "status": "queued",
            "detail": detail or "queued",
            "queued_at": now,
            "started_at": None,
            "finished_at": None,
            "updated_at": now,
            "error": None,
            "result": None,
            "cancel_requested": False,
            "cancel_requested_at": None,
            "payload": payload or {},
            "history_visible": bool(history_visible),
            "authoritative": True,
            "task_key": None,
            "attempt": 1,
            "max_attempts": 1,
        }
        with self._lock:
            self._jobs[job_id] = record
            self._order.append(job_id)
            self._trim_history_locked()
            self._persist_locked()
        self._queue.put(_QueuedJob(job_id=job_id, func=func))
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._sync_from_store_locked()
            item = self._jobs.get(job_id)
            if item is None:
                return None
            return dict(item)

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            self._sync_from_store_locked()
            item = self._jobs.get(job_id)
            if item is None:
                return None

            state = str(item.get("status") or "")
            if state in {"succeeded", "failed", "canceled"}:
                return {
                    "ok": False,
                    "job_id": job_id,
                    "status": state,
                    "message": f"Job is already {state}.",
                }

            if state == "queued":
                item["status"] = "canceled"
                item["updated_at"] = now
                item["finished_at"] = now
                item["error"] = "Canceled by user."
                item["result"] = None
                item["cancel_requested"] = True
                item["cancel_requested_at"] = now
                self._persist_locked()
                return {
                    "ok": True,
                    "job_id": job_id,
                    "status": "canceled",
                    "message": "Queued job canceled.",
                }

            item["cancel_requested"] = True
            item["cancel_requested_at"] = now
            item["updated_at"] = now
            self._persist_locked()
            return {
                "ok": True,
                "job_id": job_id,
                "status": state,
                "message": "Cancellation requested for running job.",
            }

    def list(self, *, limit: int = 20, status: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self._sync_from_store_locked()
            ordered = [
                self._jobs[job_id]
                for job_id in reversed(self._order)
                if job_id in self._jobs and bool(self._jobs[job_id].get("history_visible", True))
            ]
            if status is not None:
                ordered = [item for item in ordered if item.get("status") == status]
            return [dict(item) for item in ordered[: max(1, int(limit))]]

    def list_active_tasks(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            self._sync_from_store_locked()
            ordered = [
                self._jobs[job_id]
                for job_id in reversed(self._order)
                if job_id in self._jobs
                and self._jobs[job_id].get("status") in {"queued", "running"}
            ]
            return [dict(item) for item in ordered[: max(1, int(limit))]]

    def summary(self) -> dict[str, Any]:
        with self._lock:
            self._sync_from_store_locked()
            queued = 0
            running = 0
            succeeded = 0
            failed = 0
            canceled = 0
            latest_finished: dict[str, Any] | None = None

            for item in self._jobs.values():
                if not bool(item.get("history_visible", True)):
                    continue
                state = item.get("status")
                if state == "queued":
                    queued += 1
                elif state == "running":
                    running += 1
                elif state == "succeeded":
                    succeeded += 1
                elif state == "failed":
                    failed += 1
                elif state == "canceled":
                    canceled += 1

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
                "canceled": canceled,
                "latest_finished": dict(latest_finished) if latest_finished is not None else None,
                "updated_at": time.time(),
            }

    def begin_external_task(
        self,
        *,
        kind: str,
        name: str,
        source: str,
        detail: str,
        payload: dict[str, Any] | None = None,
        task_key: str | None = None,
        history_visible: bool = False,
    ) -> str:
        now = time.time()
        with self._lock:
            existing = self._find_active_task_by_key_locked(task_key)
            if existing is not None:
                item = self._jobs[existing]
                item.update(
                    {
                        "kind": kind,
                        "name": name,
                        "source": source,
                        "detail": detail,
                        "payload": payload or item.get("payload") or {},
                        "updated_at": now,
                        "authoritative": True,
                        "history_visible": bool(history_visible),
                    }
                )
                if item.get("status") != "running":
                    item["status"] = "running"
                    item["started_at"] = now
                self._persist_locked()
                return existing

            task_id = uuid.uuid4().hex
            self._jobs[task_id] = {
                "job_id": task_id,
                "kind": kind,
                "name": name,
                "source": source,
                "status": "running",
                "detail": detail,
                "queued_at": now,
                "started_at": now,
                "finished_at": None,
                "updated_at": now,
                "error": None,
                "result": None,
                "cancel_requested": False,
                "cancel_requested_at": None,
                "payload": payload or {},
                "history_visible": bool(history_visible),
                "authoritative": True,
                "task_key": task_key,
                "attempt": 1,
                "max_attempts": 1,
            }
            self._order.append(task_id)
            self._trim_history_locked()
            self._persist_locked()
            return task_id

    def update_external_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        detail: str | None = None,
        payload_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            item = self._jobs.get(task_id)
            if item is None:
                return None
            if status is not None:
                item["status"] = status
                if status == "running" and item.get("started_at") is None:
                    item["started_at"] = now
            if detail is not None:
                item["detail"] = detail
            if payload_updates:
                current_payload = dict(item.get("payload") or {})
                current_payload.update(payload_updates)
                item["payload"] = current_payload
            item["updated_at"] = now
            self._persist_locked()
            return dict(item)

    def finish_external_task(
        self,
        task_id: str,
        *,
        success: bool,
        detail: str | None = None,
        error: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            item = self._jobs.get(task_id)
            if item is None:
                return None
            item["status"] = "succeeded" if success else "failed"
            item["finished_at"] = now
            item["updated_at"] = now
            item["error"] = None if success else (error or item.get("error"))
            item["result"] = result
            if detail is not None:
                item["detail"] = detail
            self._persist_locked()
            return dict(item)

    def _run(self) -> None:
        while not self._stop.is_set():
            queued_job = self._queue.get()
            if queued_job.job_id == "__stop__":
                continue

            with self._lock:
                item = self._jobs.get(queued_job.job_id)
                if item is None:
                    continue
                if item.get("status") == "canceled":
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
            item["detail"] = "running"
            item["started_at"] = now
            item["updated_at"] = now
            self._persist_locked()

    def _mark_failed(self, job_id: str, error: str) -> None:
        now = time.time()
        with self._lock:
            item = self._jobs.get(job_id)
            if item is None:
                return
            item["status"] = "failed"
            item["detail"] = "failed"
            item["finished_at"] = now
            item["updated_at"] = now
            item["error"] = error
            item["result"] = None
            self._persist_locked()

    def _mark_succeeded(self, job_id: str, result: dict[str, Any]) -> None:
        now = time.time()
        with self._lock:
            item = self._jobs.get(job_id)
            if item is None:
                return
            item["status"] = "succeeded"
            item["detail"] = "completed"
            item["finished_at"] = now
            item["updated_at"] = now
            item["error"] = None
            item["result"] = result
            self._persist_locked()

    def _trim_history_locked(self) -> None:
        if len(self._order) <= self._max_history:
            return
        overflow = len(self._order) - self._max_history
        for _ in range(overflow):
            old_job_id = self._order.pop(0)
            self._jobs.pop(old_job_id, None)

    def _load_persisted_jobs(self) -> tuple[dict[str, dict[str, Any]], list[str], bool]:
        if self._state_store is None:
            return {}, [], False
        items, order = self._state_store.load_jobs()
        if not items:
            return {}, [], False

        now = time.time()
        mutated = False
        for record in items.values():
            record.setdefault("name", str(record.get("kind") or "Background Job"))
            record.setdefault("source", "job-manager")
            record.setdefault("detail", str(record.get("status") or "unknown"))
            record.setdefault("payload", {})
            record.setdefault("history_visible", True)
            record.setdefault("authoritative", True)
            record.setdefault("task_key", None)
            record.setdefault("attempt", 1)
            record.setdefault("max_attempts", 1)
            status = str(record.get("status") or "")
            if status not in {"queued", "running"}:
                continue
            record["status"] = "failed"
            record["detail"] = "interrupted"
            record["finished_at"] = now
            record["updated_at"] = now
            record["error"] = "Interrupted by process restart."
            record["result"] = None
            mutated = True
        return items, order, mutated

    def _find_active_task_by_key_locked(self, task_key: str | None) -> str | None:
        if not task_key:
            return None
        for job_id in reversed(self._order):
            item = self._jobs.get(job_id)
            if item is None:
                continue
            if item.get("task_key") != task_key:
                continue
            if item.get("status") in {"queued", "running"}:
                return job_id
        return None

    def _persist_locked(self) -> None:
        if self._state_store is None:
            return
        self._state_store.save_jobs(self._jobs, self._order)

    def _sync_from_store_locked(self) -> None:
        if self._state_store is None:
            return
        items, order = self._state_store.load_jobs()
        self._jobs = items
        self._order = order
