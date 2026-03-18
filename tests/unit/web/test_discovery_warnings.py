from pathlib import Path

from fastapi.testclient import TestClient

from librariarr.web import create_app


def _write_config_with_trailer_excludes(path: Path, nested_root: Path, shadow_root: Path) -> None:
    path.write_text(
        (
            "paths:\n"
            "  root_mappings:\n"
            f"    - nested_root: {nested_root}\n"
            f"      shadow_root: {shadow_root}\n"
            "  movie_root_mappings:\n"
            f"    - managed_root: {nested_root}\n"
            f"      library_root: {shadow_root}\n"
            "  exclude_paths:\n"
            "    - '*-trailer.*'\n"
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


def test_discovery_warnings_does_not_exclude_folder_with_valid_m4v_and_trailer(
    tmp_path: Path,
) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    movie_dir = nested_root / "Movies" / "Example Movie (2010)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Example Movie (2010).m4v").write_text("x", encoding="utf-8")
    (movie_dir / "Example Movie (2010)-trailer.mp4").write_text("x", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    _write_config_with_trailer_excludes(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.get("/api/fs/discovery-warnings")

    assert response.status_code == 200
    payload = response.json()
    assert all(item["path"] != str(movie_dir) for item in payload["excluded_movie_candidates"])
