from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from librariarr.web.app import create_app

CONFIG_YAML = """
paths:
  movie_root_mappings:
    - managed_root: /data/movies
      library_root: /data/radarr_library
radarr:
  enabled: false
  url: http://radarr:7878
  api_key: k
"""


@pytest.fixture
def client(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG_YAML, encoding="utf-8")
    app = create_app(
        config_path=config_path,
        ui_dist_path=tmp_path / "no-dist",
        run_runtime_loop=False,
    )
    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_status_shape(client):
    payload = client.get("/api/status").json()
    assert "running" in payload
    assert "last_report" in payload
    assert payload["runtime_loop_active"] is False


def test_config_roundtrip(client):
    original = client.get("/api/config").json()["yaml"]
    assert "radarr" in original

    updated = original + "\n# comment\n"
    response = client.put("/api/config", json={"yaml": updated})
    assert response.status_code == 200
    assert client.get("/api/config").json()["yaml"] == updated


def test_config_put_rejects_invalid_yaml(client):
    response = client.put("/api/config", json={"yaml": "paths: {}\n"})
    assert response.status_code == 422


def test_config_validate_endpoint(client):
    good = client.post("/api/config/validate", json={"yaml": CONFIG_YAML})
    assert good.json()["valid"] is True
    bad = client.post("/api/config/validate", json={"yaml": "nope: {}\n"})
    assert bad.json()["valid"] is False


def test_reconcile_dry_run_with_disabled_arrs_is_noop(client):
    response = client.post("/api/reconcile", json={"scope": "full", "dry_run": True})
    assert response.status_code == 200
    report = response.json()["report"]
    assert report["dry_run"] is True
    assert report["items_seen"] == 0


def test_reconcile_rejects_unknown_scope(client):
    response = client.post("/api/reconcile", json={"scope": "everything"})
    assert response.status_code == 400


def test_hooks_accept_payload_without_runtime_loop(client):
    response = client.post("/api/hooks/radarr", json={"eventType": "Download"})
    assert response.status_code == 200
    assert response.json()["queued"] is False


def test_hooks_reject_bad_secret(client, monkeypatch):
    monkeypatch.setenv("LIBRARIARR_WEBHOOK_SECRET", "sekrit")
    response = client.post("/api/hooks/radarr", json={"eventType": "Download"})
    assert response.status_code == 401
    ok = client.post(
        "/api/hooks/radarr",
        json={"eventType": "Download"},
        headers={"X-Librariarr-Webhook-Secret": "sekrit"},
    )
    assert ok.status_code == 200


def test_unmatched_endpoint_shape(client):
    payload = client.get("/api/unmatched").json()
    assert "unmatched" in payload


def test_logs_endpoint_shape(client):
    payload = client.get("/api/logs").json()
    assert "entries" in payload
