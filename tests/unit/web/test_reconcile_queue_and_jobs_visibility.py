import time
from pathlib import Path

from fastapi.testclient import TestClient

from librariarr.web import create_app


def _wait_for_job(client: TestClient, job_id: str, timeout: float = 3.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {"succeeded", "failed"}:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for job {job_id}")


def _write_config(path: Path, nested_root: Path, shadow_root: Path) -> None:
    path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            f"    - nested_root: {nested_root}\n"
            f"      shadow_root: {shadow_root}\n"
            "  movie_root_mappings:\n"
            f"    - managed_root: {nested_root}\n"
            f"      library_root: {shadow_root}\n"
            "radarr:\n"
            "  enabled: true\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "  sync_enabled: false\n"
            "sonarr:\n"
            "  enabled: false\n"
            "  url: http://sonarr:8989\n"
            "  api_key: test-key\n"
            "  sync_enabled: false\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )


def test_maintenance_reconcile_waits_for_active_reconcile(tmp_path: Path, monkeypatch) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    class StubService:
        def __init__(self, *_args, **_kwargs):
            pass

        def reconcile(
            self,
            affected_paths=None,
            *,
            refresh_arr_root_availability: bool = True,
        ):
            return False

    monkeypatch.setattr("librariarr.web.maintenance_ops.LibrariArrService", StubService)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    runtime_status = app.state.runtime_status
    runtime_status.mark_reconcile_started(trigger_source="startup", phase="startup_full_reconcile")
    try:
        queued = client.post("/api/maintenance/reconcile")
    finally:
        runtime_status.mark_reconcile_finished(success=True)

    assert queued.status_code == 200
    assert queued.json()["queued"] is True
    job = _wait_for_job(client, queued.json()["job_id"])
    assert job["status"] == "succeeded"


def test_full_reconcile_waits_for_active_reconcile(tmp_path: Path, monkeypatch) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    class StubService:
        def __init__(self, *_args, **_kwargs):
            pass

        def reconcile_full(self):
            return False

    monkeypatch.setattr("librariarr.web.full_reconcile_ops.LibrariArrService", StubService)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    runtime_status = app.state.runtime_status
    runtime_status.mark_reconcile_started(trigger_source="startup", phase="startup_full_reconcile")
    try:
        queued = client.post("/api/maintenance/full-reconcile")
    finally:
        runtime_status.mark_reconcile_finished(success=True)

    assert queued.status_code == 200
    assert queued.json()["queued"] is True
    job = _wait_for_job(client, queued.json()["job_id"])
    assert job["status"] == "succeeded"


def test_jobs_endpoints_include_hidden_tasks_when_requested(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    manager = app.state.web.job_manager
    assert manager is not None
    manager.begin_external_task(
        kind="runtime-reconcile",
        name="Startup Full Reconcile",
        source="startup",
        detail="running",
        payload={"phase": "startup_full_reconcile"},
        task_key="reconcile:startup",
        history_visible=False,
    )

    client = TestClient(app)

    hidden_jobs = client.get("/api/jobs", params={"include_hidden": "true"})
    assert hidden_jobs.status_code == 200
    assert any(item["name"] == "Startup Full Reconcile" for item in hidden_jobs.json()["items"])

    hidden_summary = client.get("/api/jobs/summary", params={"include_hidden": "true"})
    assert hidden_summary.status_code == 200
    assert hidden_summary.json()["running"] >= 1
