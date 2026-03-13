import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from librariarr.web import create_app
from librariarr.web.runtime_supervisor import RuntimeSupervisor


def _write_config(path: Path, nested_root: Path, shadow_root: Path) -> None:
    path.write_text(
        (
            "paths:\n"
            "  root_mappings:\n"
            f"    - nested_root: {nested_root}\n"
            f"      shadow_root: {shadow_root}\n"
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


def test_get_config_redacts_secrets_by_default(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.get("/api/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["radarr"]["api_key"] == "***redacted***"


def test_get_config_can_include_secrets(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.get("/api/config", params={"include_secrets": "true"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["radarr"]["api_key"] == "test-key"


def test_validate_sets_draft_and_diff(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.post(
        "/api/config/validate",
        json={
            "config": {
                "runtime": {
                    "debounce_seconds": 12,
                }
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True

    diff_response = client.get("/api/config/diff")
    assert diff_response.status_code == 200
    assert diff_response.json()["has_diff"] is True


def test_put_config_saves_to_disk(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.put(
        "/api/config",
        json={
            "config": {
                "runtime": {
                    "debounce_seconds": 21,
                }
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["saved"] is True
    assert "debounce_seconds: 21" in config_path.read_text(encoding="utf-8")


def test_put_config_restarts_runtime_when_supervisor_present(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    class StubRuntimeSupervisor(RuntimeSupervisor):
        def __init__(self, config_path: Path) -> None:
            super().__init__(config_path=config_path)
            self.reasons: list[str] = []

        def restart_for_config_change(self, reason: str) -> bool:
            self.reasons.append(reason)
            return True

    runtime_supervisor = StubRuntimeSupervisor(config_path)
    app = create_app(config_path=config_path, runtime_supervisor=runtime_supervisor)
    client = TestClient(app)

    response = client.put(
        "/api/config",
        json={
            "config": {
                "runtime": {
                    "debounce_seconds": 21,
                }
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["saved"] is True
    assert payload["runtime_restarted"] is True
    assert payload["runtime_restart_recommended"] is False
    assert runtime_supervisor.reasons == ["config updated via API"]


def test_fs_ls_rejects_outside_allowed_paths(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    outside = tmp_path / "outside"
    outside.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.get("/api/fs/ls", params={"path": str(outside)})

    assert response.status_code == 403


def test_diagnostics_endpoint_returns_disabled_when_sonarr_disabled(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.post("/api/diagnostics/sonarr")

    assert response.status_code == 200
    assert response.json()["status"] == "disabled"


def test_radarr_connection_test_endpoint_reports_success(
    tmp_path: Path,
    monkeypatch,
) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    class StubRadarrClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_system_status(self):
            return {"version": "5.0.0"}

    monkeypatch.setattr("librariarr.web.operations.RadarrClient", StubRadarrClient)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.post(
        "/api/radarr/test",
        json={"url": "http://radarr:7878", "api_key": "abc"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_maintenance_reconcile_endpoint_runs_service(tmp_path: Path, monkeypatch) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    class StubService:
        def __init__(self, *_args, **_kwargs):
            pass

        def reconcile(self):
            return False

    monkeypatch.setattr("librariarr.web.operations.LibrariArrService", StubService)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.post("/api/maintenance/reconcile")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["message"] == "Reconcile completed."


def test_mapped_directories_lists_virtual_to_real_paths(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    movie_dir = nested_root / "Movie One"
    movie_dir.mkdir()
    shadow_link = shadow_root / "Movie One"
    shadow_link.symlink_to(movie_dir, target_is_directory=True)

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.get("/api/fs/mapped-directories")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["virtual_path"] == str(shadow_link)
    assert payload["items"][0]["real_path"] == str(movie_dir)


def test_mapped_directories_stream_endpoint_emits_sse(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    movie_dir = nested_root / "Movie One"
    movie_dir.mkdir()
    (shadow_root / "Movie One").symlink_to(movie_dir, target_is_directory=True)

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    with client.stream("GET", "/api/fs/mapped-directories/stream", params={"max_events": 1}) as r:
        first_line = next(r.iter_lines())

    assert r.status_code == 200
    assert first_line.startswith("data: ")
    assert '"changed": false' in first_line


def test_docker_logs_endpoint_returns_newest_first(tmp_path: Path, monkeypatch) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    def _stub_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["docker", "logs"],
            returncode=0,
            stdout="2026-03-13 INFO Started\n2026-03-13 ERROR Failed\n",
            stderr="",
        )

    monkeypatch.setattr("librariarr.web.docker_logs.subprocess.run", _stub_run)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.get("/api/logs/docker", params={"container": "librariarr", "tail": 20})

    assert response.status_code == 200
    payload = response.json()
    assert payload["container"] == "librariarr"
    assert payload["items"][0]["line"].endswith("ERROR Failed")
    assert payload["items"][0]["level"] == "ERROR"
    assert payload["items"][1]["level"] == "INFO"


def test_docker_logs_endpoint_rejects_invalid_container_name(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.get("/api/logs/docker", params={"container": "bad;name", "tail": 20})

    assert response.status_code == 400


def test_docker_logs_stream_endpoint_emits_sse(tmp_path: Path, monkeypatch) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    async def _stub_stream_docker_logs(*_args, **_kwargs):
        yield {"line": "INFO started", "level": "INFO"}

    monkeypatch.setattr("librariarr.web.operations.stream_docker_logs", _stub_stream_docker_logs)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    with client.stream(
        "GET",
        "/api/logs/docker/stream",
        params={"container": "librariarr", "tail": 0},
    ) as r:
        first_line = next(r.iter_lines())

    assert r.status_code == 200
    assert first_line.startswith("data: ")
    assert "INFO started" in first_line
