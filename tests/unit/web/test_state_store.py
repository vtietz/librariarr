from pathlib import Path

from librariarr.web.jobs import JobManager
from librariarr.web.state_store import PersistentStateStore


def test_persistent_state_store_round_trip_jobs_and_dashboard(tmp_path: Path) -> None:
    store = PersistentStateStore(tmp_path / "state.json")

    store.save_jobs(
        {
            "job-1": {
                "job_id": "job-1",
                "kind": "reconcile-manual",
                "status": "succeeded",
            }
        },
        ["job-1"],
    )
    store.save_dashboard({"updated_at": 123.0, "health": {"status": "ok", "reasons": []}})
    store.save_cache_snapshot(
        "mapped_directories",
        {"items": [{"virtual_path": "/shadow/Movie One"}], "version": 2},
    )

    items, order = store.load_jobs()
    dashboard = store.load_dashboard()
    mapped_snapshot = store.load_cache_snapshot("mapped_directories")

    assert order == ["job-1"]
    assert items["job-1"]["kind"] == "reconcile-manual"
    assert dashboard is not None
    assert dashboard["health"]["status"] == "ok"
    assert mapped_snapshot == {"items": [{"virtual_path": "/shadow/Movie One"}], "version": 2}


def test_job_manager_marks_running_jobs_interrupted_when_reloaded(tmp_path: Path) -> None:
    store = PersistentStateStore(tmp_path / "state.json")
    store.save_jobs(
        {
            "job-1": {
                "job_id": "job-1",
                "kind": "reconcile-manual",
                "status": "running",
                "queued_at": 1.0,
                "started_at": 2.0,
                "finished_at": None,
                "updated_at": 2.0,
                "error": None,
                "result": None,
            }
        },
        ["job-1"],
    )

    manager = JobManager(state_store=store)

    job = manager.get("job-1")
    assert job is not None
    assert job["status"] == "failed"
    assert job["error"] == "Interrupted by process restart."
    assert job["finished_at"] is not None

    persisted_items, persisted_order = store.load_jobs()
    assert persisted_order == ["job-1"]
    assert persisted_items["job-1"]["status"] == "failed"
    assert persisted_items["job-1"]["error"] == "Interrupted by process restart."


def test_job_manager_external_tasks_do_not_pollute_visible_job_summary(tmp_path: Path) -> None:
    store = PersistentStateStore(tmp_path / "state.json")
    manager = JobManager(state_store=store)

    task_id = manager.begin_external_task(
        kind="cache-refresh-mapped",
        name="Mapped Index Rebuild",
        source="cache",
        detail="Rebuilding mapped directory index",
        payload={"cache_name": "mapped_directories"},
        task_key="mapped-index",
        history_visible=False,
    )

    summary = manager.summary()
    active_tasks = manager.list_active_tasks(limit=10)

    assert summary["active"] == 0
    assert len(active_tasks) == 1
    assert active_tasks[0]["job_id"] == task_id
