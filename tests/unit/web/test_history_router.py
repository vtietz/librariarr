import logging
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


def test_history_collects_scenario_friendly_events_and_can_delete(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    logger = logging.getLogger("librariarr.service.reconcile_helpers")
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        logger.info(
            "Stale shadow cleanup removed %s orphaned managed file(s)",
            3,
        )
    finally:
        logger.setLevel(previous_level)

    response = client.get("/api/history")
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"]

    first = payload["items"][0]
    assert first["scenario"] == "8"
    assert first["category"] == "cleanup"
    assert "Removed stale links" in first["title"]

    delete_response = client.delete(f"/api/history/{first['id']}")
    assert delete_response.status_code == 200


def test_history_clear_endpoint(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    logger = logging.getLogger("librariarr.service.reconcile_ingest")
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        logger.info(
            "File-level fs operations for movie_id=%s: moved=%s failed=%s",
            10,
            2,
            0,
        )
    finally:
        logger.setLevel(previous_level)

    before = client.get("/api/history").json()
    assert len(before["items"]) >= 1

    clear_response = client.post("/api/history/clear")
    assert clear_response.status_code == 200
    assert clear_response.json()["ok"] is True

    after = client.get("/api/history").json()
    assert after["items"] == []
