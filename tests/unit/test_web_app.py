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


class StubLoop:
    def __init__(self):
        self.consistency_calls = []
        self.full_calls = []
        self.targeted_calls = []

    def trigger_consistency(self, reason=""):
        self.consistency_calls.append(reason)

    def trigger_full(self, reason=""):
        self.full_calls.append(reason)

    def trigger_targeted(self, reason="", *, movie_ids=(), series_ids=()):
        self.targeted_calls.append((reason, list(movie_ids), list(series_ids)))


@pytest.fixture
def loop_stub(client):
    stub = StubLoop()
    client.app.state.web.runtime_loop = stub
    try:
        yield stub
    finally:
        client.app.state.web.runtime_loop = None


def test_hook_without_item_id_triggers_consistency_on_the_loop(client, loop_stub):
    response = client.post("/api/hooks/radarr", json={"eventType": "Download"})
    assert response.status_code == 200
    assert response.json()["queued"] is True
    assert response.json()["scope"] == "consistency"
    assert loop_stub.consistency_calls == ["webhook:Download"]

    response = client.post("/api/reconcile", json={"scope": "full"})
    assert response.json()["queued"] is True
    assert loop_stub.full_calls == ["api"]


def test_radarr_hook_with_a_movie_id_targets_just_that_movie(client, loop_stub):
    """The payload is a hint: only the id is taken from it, and it decides the
    scope of the pass — that is what keeps an import off the whole library."""
    response = client.post(
        "/api/hooks/radarr",
        json={"eventType": "Download", "movie": {"id": 4473, "title": "Virtual Weapon"}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"] == "targeted"
    assert payload["item_id"] == 4473
    assert loop_stub.targeted_calls == [("webhook:Download", [4473], [])]
    assert loop_stub.consistency_calls == []


def test_sonarr_hook_with_a_series_id_targets_just_that_series(client, loop_stub):
    response = client.post(
        "/api/hooks/sonarr",
        json={"eventType": "Download", "series": {"id": 12, "title": "Show"}},
    )
    assert response.json()["scope"] == "targeted"
    assert loop_stub.targeted_calls == [("webhook:Download", [], [12])]


def test_test_event_keeps_the_global_consistency_pass(client, loop_stub):
    """Radarr's test payload carries a dummy movie id; it describes no library
    change, so it must not be mistaken for real work."""
    response = client.post(
        "/api/hooks/radarr", json={"eventType": "Test", "movie": {"id": 1, "title": "Test Title"}}
    )
    assert response.json()["scope"] == "consistency"
    assert loop_stub.targeted_calls == []
    assert loop_stub.consistency_calls == ["webhook:Test"]


def test_hook_with_unusable_item_id_falls_back_to_consistency(client, loop_stub):
    for payload in (
        {"eventType": "Download", "movie": {"title": "no id"}},
        {"eventType": "Download", "movie": {"id": 0}},
        {"eventType": "Download", "movie": "not-an-object"},
        {"eventType": "Rename"},
    ):
        client.post("/api/hooks/radarr", json=payload)
    assert loop_stub.targeted_calls == []
    assert len(loop_stub.consistency_calls) == 4


def test_reconcile_targeted_queues_the_given_ids(client, loop_stub):
    response = client.post(
        "/api/reconcile",
        json={"scope": "targeted", "radarr_movie_ids": [5, 5, 7], "sonarr_series_ids": [2]},
    )
    assert response.status_code == 200
    assert response.json()["queued"] is True
    assert loop_stub.targeted_calls == [("api", [5, 7], [2])]


def test_reconcile_targeted_requires_ids(client):
    response = client.post("/api/reconcile", json={"scope": "targeted"})
    assert response.status_code == 400
    assert "targeted" in response.json()["detail"]


def test_reconcile_targeted_rejects_unusable_ids(client):
    response = client.post(
        "/api/reconcile", json={"scope": "targeted", "radarr_movie_ids": [0, -3]}
    )
    assert response.status_code == 400


def test_reconcile_targeted_rejects_oversized_id_lists(client):
    response = client.post(
        "/api/reconcile",
        json={"scope": "targeted", "radarr_movie_ids": list(range(1, 500))},
    )
    assert response.status_code == 400
    assert "full" in response.json()["detail"]


def test_reconcile_targeted_dry_run_returns_a_report(client):
    response = client.post(
        "/api/reconcile", json={"scope": "targeted", "radarr_movie_ids": [1], "dry_run": True}
    )
    assert response.status_code == 200
    report = response.json()["report"]
    assert report["scope"] == "targeted"
    assert report["dry_run"] is True


def test_bucket_drift_endpoint_shape(client):
    payload = client.get("/api/bucket-drift").json()
    assert payload == {"drift": []}


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
    assert "as_of" in payload


def test_manual_add_endpoint_reports_reason(client):
    response = client.post("/api/unmatched/add", json={"path": "/nowhere/at/all"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["reason"] in {"not_found", "outside_roots"}


def test_logs_endpoint_shape(client):
    payload = client.get("/api/logs").json()
    assert "entries" in payload


def test_path_differences_endpoint_shape(client):
    payload = client.get("/api/path-differences").json()
    assert payload == {"differences": []}
