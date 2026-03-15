import logging
import time
from pathlib import Path

from fastapi.testclient import TestClient

from librariarr.web import create_app
from librariarr.web.log_buffer import LogRingBuffer
from librariarr.web.runtime_supervisor import RuntimeSupervisor


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


def _write_config_with_excludes(path: Path, nested_root: Path, shadow_root: Path) -> None:
    path.write_text(
        (
            "paths:\n"
            "  root_mappings:\n"
            f"    - nested_root: {nested_root}\n"
            f"      shadow_root: {shadow_root}\n"
            "  exclude_paths:\n"
            "    - .deletedByTMM/\n"
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
    backup_path = tmp_path / "config.yaml.bak"
    assert backup_path.exists()
    backup_yaml = backup_path.read_text(encoding="utf-8")
    assert "debounce_seconds: 21" not in backup_yaml
    assert "sync_enabled: false" in backup_yaml


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
    # Config save no longer triggers an explicit restart — the
    # RuntimeSupervisor config-watcher detects the mtime change and restarts
    # automatically.  The response signals that a supervisor is present.
    assert payload["runtime_restarted"] is True
    assert payload["runtime_restart_recommended"] is False
    # No explicit restart_for_config_change call; the watcher handles it.
    assert runtime_supervisor.reasons == []


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
    queued = response.json()
    assert queued["ok"] is True
    job = _wait_for_job(client, queued["job_id"])
    assert job["status"] == "succeeded"
    assert job["result"]["status"] == "disabled"


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
    queued = response.json()
    assert queued["ok"] is True
    payload = _wait_for_job(client, queued["job_id"])["result"]
    assert payload["ok"] is True
    assert payload["message"] == "Reconcile completed."


def test_runtime_status_endpoint_reports_manual_reconcile(tmp_path: Path, monkeypatch) -> None:
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

    reconcile_response = client.post("/api/maintenance/reconcile")
    assert reconcile_response.status_code == 200
    job = _wait_for_job(client, reconcile_response.json()["job_id"])
    assert job["status"] == "succeeded"

    response = client.get("/api/runtime/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["runtime_supervisor_present"] is False
    assert payload["runtime_supervisor_running"] is False
    assert payload["last_reconcile"] is not None
    assert payload["last_reconcile"]["trigger_source"] == "manual"
    assert isinstance(payload.get("known_links_in_memory"), int)
    assert isinstance(payload.get("pending_tasks"), list)
    assert isinstance(payload.get("mapped_cache"), dict)
    assert isinstance(payload.get("discovery_cache"), dict)


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
    assert "cache" in payload
    assert payload["cache"]["version"] >= 1
    assert isinstance(payload["cache"]["ready"], bool)


def test_discovery_warnings_reports_excluded_and_duplicate_candidates(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    included_movie = (
        nested_root / "FSK12" / "Pierre Richard Collection" / ("Der Regenschirmmörder (1980)")
    )
    excluded_movie = (
        nested_root
        / "FSK12"
        / ".deletedByTMM"
        / "Pierre Richard Collection"
        / "Der Regenschirmmörder (1980)"
    )
    included_movie.mkdir(parents=True)
    excluded_movie.mkdir(parents=True)
    (included_movie / "movie.mkv").write_text("x", encoding="utf-8")
    (excluded_movie / "movie.mkv").write_text("x", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    _write_config_with_excludes(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.get("/api/fs/discovery-warnings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["excluded_movie_candidates"] >= 1
    assert payload["summary"]["duplicate_movie_candidates"] >= 1
    assert any(item["path"] == str(excluded_movie) for item in payload["excluded_movie_candidates"])
    assert any(
        item["movie_ref"] == "der regenschirmmörder (1980)" and item["contains_excluded"] is True
        for item in payload["duplicate_movie_candidates"]
    )
    assert payload["cache"]["ready"] is True


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


def test_mapped_directories_refresh_endpoint_forces_rescan(tmp_path: Path) -> None:
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

    response = client.post("/api/fs/mapped-directories/refresh")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["cache"]["ready"] is True
    assert payload["cache"]["entries_total"] >= 1


def test_app_logs_endpoint_returns_entries(tmp_path: Path, monkeypatch) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    buf = LogRingBuffer(maxlen=100)
    buf.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))
    monkeypatch.setattr("librariarr.web.operations.get_log_buffer", lambda: buf)

    logger = logging.getLogger("test.logs")
    logger.addHandler(buf)
    logger.setLevel(logging.DEBUG)
    logger.info("Started")
    logger.error("Failed")

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.get("/api/logs", params={"tail": 20})

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["level"] == "ERROR"
    assert payload["items"][1]["level"] == "INFO"
    logger.removeHandler(buf)


def test_app_logs_stream_endpoint_emits_sse(tmp_path: Path, monkeypatch) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    buf = LogRingBuffer(maxlen=100)
    buf.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))
    monkeypatch.setattr("librariarr.web.operations.get_log_buffer", lambda: buf)

    logger = logging.getLogger("test.stream")
    logger.addHandler(buf)
    logger.setLevel(logging.DEBUG)
    logger.info("stream test line")

    app = create_app(config_path=config_path)
    client = TestClient(app)

    with client.stream("GET", "/api/logs/stream", params={"max_events": 1}) as r:
        first_line = next(r.iter_lines())

    assert r.status_code == 200
    assert first_line.startswith("data: ")
    assert '"connected": true' in first_line
    logger.removeHandler(buf)


def test_app_logs_stream_endpoint_replays_buffered_entries(tmp_path: Path, monkeypatch) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    buf = LogRingBuffer(maxlen=100)
    buf.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))
    monkeypatch.setattr("librariarr.web.operations.get_log_buffer", lambda: buf)

    logger = logging.getLogger("test.stream.replay")
    logger.addHandler(buf)
    logger.setLevel(logging.DEBUG)
    logger.info("older replay line")
    logger.warning("newer replay line")

    app = create_app(config_path=config_path)
    client = TestClient(app)

    with client.stream("GET", "/api/logs/stream", params={"max_events": 3}) as response:
        data_lines = [line for line in response.iter_lines() if line.startswith("data: ")]
        first_three = data_lines[:3]

    assert response.status_code == 200
    assert len(first_three) == 3
    assert '"connected": true' in first_three[0]
    assert "newer replay line" in first_three[1]
    assert "older replay line" in first_three[2]
    logger.removeHandler(buf)
