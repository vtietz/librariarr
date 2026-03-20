import time
from pathlib import Path

from librariarr.web.jobs import JobManager
from librariarr.web.state_store import PersistentStateStore


def _wait_for_terminal_state(manager: JobManager, job_id: str, timeout: float = 3.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        item = manager.get(job_id)
        assert item is not None
        status = str(item.get("status") or "")
        if status in {"succeeded", "failed", "canceled"}:
            return status
        time.sleep(0.02)
    raise AssertionError(f"Timed out waiting for {job_id}")


def test_submit_deduplicates_active_task_key(tmp_path: Path) -> None:
    store = PersistentStateStore(tmp_path / "state.json")
    manager = JobManager(state_store=store)

    try:
        first_id = manager.submit(
            kind="reconcile-manual",
            name="Manual Reconcile",
            source="job-manager",
            detail="queued",
            task_key="reconcile-full",
            func=lambda: {"ok": True},
        )
        second_id = manager.submit(
            kind="reconcile-manual",
            name="Manual Reconcile",
            source="job-manager",
            detail="queued",
            task_key="reconcile-full",
            func=lambda: {"ok": True},
        )

        assert second_id == first_id
        assert _wait_for_terminal_state(manager, first_id) == "succeeded"
    finally:
        manager.stop()


def test_submit_reuses_task_key_only_while_active(tmp_path: Path) -> None:
    store = PersistentStateStore(tmp_path / "state.json")
    manager = JobManager(state_store=store)

    try:
        first_id = manager.submit(
            kind="reconcile-manual",
            name="Manual Reconcile",
            source="job-manager",
            detail="queued",
            task_key="reconcile-incremental",
            func=lambda: {"ok": True},
        )
        assert _wait_for_terminal_state(manager, first_id) == "succeeded"

        second_id = manager.submit(
            kind="reconcile-manual",
            name="Manual Reconcile",
            source="job-manager",
            detail="queued",
            task_key="reconcile-incremental",
            func=lambda: {"ok": True},
        )

        assert second_id != first_id
        assert _wait_for_terminal_state(manager, second_id) == "succeeded"
    finally:
        manager.stop()
