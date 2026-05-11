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


def test_runtime_status_health_reports_unmanaged_shadow_video_files(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    unmanaged_shadow_file = shadow_root / "Movie A (2022)" / "Movie.A.2022.1080p.mkv"
    unmanaged_shadow_file.parent.mkdir(parents=True)
    unmanaged_shadow_file.write_text("x", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    with TestClient(app) as client:
        warnings_response = client.get("/api/fs/discovery-warnings")
        assert warnings_response.status_code == 200

        response = client.get("/api/runtime/status")
        assert response.status_code == 200

        payload = response.json()
        reasons = payload.get("health", {}).get("reasons", [])
        assert any(
            "unmanaged shadow video file(s) detected" in reason
            for reason in reasons
            if isinstance(reason, str)
        )
