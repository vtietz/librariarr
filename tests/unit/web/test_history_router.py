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


def test_history_includes_startup_and_reconcile_lifecycle_events(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    logger = logging.getLogger("librariarr.service")
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        logger.info("Startup reconcile mode=full")
        logger.info(
            "Reconcile started: source=%s mode=%s affected_paths=%s trigger_path=%s",
            "startup",
            "full",
            "all",
            "-",
        )
        logger.info(
            "Reconcile finished: source=%s mode=%s affected_paths=%s trigger_path=%s "
            "outcome=%s projected_files=%s matched_movies=%s matched_series=%s duration_seconds=%s",
            "startup",
            "full",
            "all",
            "-",
            "updated",
            12,
            4,
            3,
            "2.1",
        )
    finally:
        logger.setLevel(previous_level)

    payload = client.get("/api/history").json()
    titles = {item["title"] for item in payload["items"]}
    categories = {item["category"] for item in payload["items"]}

    assert "Startup reconcile mode: full" in titles
    assert "Reconcile started (full)" in titles
    assert "Reconcile finished (full, updated)" in titles
    assert "startup" in categories
    assert "reconcile" in categories


def test_history_includes_filesystem_event_trigger_and_consequence(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    logger = logging.getLogger("librariarr.service")
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        logger.info(
            "Filesystem event queued: source=%s path=%s debounce_seconds=%s",
            "filesystem:deleted",
            "/managed/Movie One/file.mkv",
            2,
        )
        logger.info(
            "Reconcile finished: source=%s mode=%s affected_paths=%s trigger_path=%s "
            "outcome=%s projected_files=%s matched_movies=%s matched_series=%s duration_seconds=%s",
            "filesystem",
            "incremental",
            1,
            "/managed/Movie One/file.mkv",
            "updated",
            0,
            1,
            0,
            "0.9",
        )
    finally:
        logger.setLevel(previous_level)

    payload = client.get("/api/history").json()
    items = payload["items"]
    filesystem_items = [item for item in items if item["category"] == "filesystem"]
    reconcile_items = [item for item in items if item["category"] == "reconcile"]

    assert filesystem_items
    assert filesystem_items[0]["title"] == "Managed file event: deleted"
    assert "A reconcile cycle was queued" in filesystem_items[0]["message"]

    assert reconcile_items
    assert any("Re-validated existing mappings" in item["message"] for item in reconcile_items)


def test_history_deduplicates_rapid_identical_auto_add_events(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    logger = logging.getLogger("librariarr.service.reconcile_autoadd")
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        logger.info("Radarr auto-add processed: added=%s total_unmatched=%s", 2, 5)
        logger.info("Radarr auto-add processed: added=%s total_unmatched=%s", 2, 5)
    finally:
        logger.setLevel(previous_level)

    payload = client.get("/api/history").json()
    auto_add_items = [
        item
        for item in payload["items"]
        if item["category"] == "auto_add" and item["title"] == "Movies auto-added to Radarr (2)"
    ]

    assert len(auto_add_items) == 1
