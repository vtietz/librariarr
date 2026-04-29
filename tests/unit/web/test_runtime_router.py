from pathlib import Path

from fastapi.testclient import TestClient

from librariarr.web import create_app


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


def test_runtime_status_endpoint_overlays_live_reconcile_state(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    runtime_status = app.state.runtime_status
    dashboard = app.state.web.dashboard_read_model
    assert dashboard is not None

    # Simulate stale read-model data while runtime tracker has live progress.
    stale_snapshot = dashboard.snapshot()
    stale_snapshot["current_task"] = {
        "state": "idle",
        "phase": None,
        "trigger_source": None,
        "started_at": None,
        "updated_at": stale_snapshot.get("updated_at"),
        "error": None,
        "task_id": None,
    }
    stale_snapshot["updated_at"] = 1.0
    dashboard._snapshot = stale_snapshot  # noqa: SLF001

    runtime_status.mark_reconcile_started(trigger_source="manual", phase="full_reconcile")
    runtime_status.update_reconcile_phase("inventory_fetched")

    client = TestClient(app)
    response = client.get("/api/runtime/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_task"]["state"] == "running"
    assert payload["current_task"]["phase"] == "inventory_fetched"

    runtime_status.mark_reconcile_finished(success=True)
