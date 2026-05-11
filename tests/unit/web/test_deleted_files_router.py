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


def test_deleted_files_list_restore_and_delete(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    trash_dir = nested_root / ".deletedByLibrariarr" / "Movie One (2024)"
    trash_dir.mkdir(parents=True)
    deleted_file = trash_dir / "Movie.One.2024.1080p.mkv.20260511T120000123456Z"
    deleted_file.write_text("deleted", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    list_response = client.get("/api/fs/deleted-files")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["path"] == str(deleted_file)
    assert item["restore_path"] == str(
        nested_root / "Movie One (2024)" / "Movie.One.2024.1080p.mkv"
    )

    restore_response = client.post(
        "/api/fs/deleted-files/restore",
        params={"path": str(deleted_file)},
    )
    assert restore_response.status_code == 200
    restored_path = nested_root / "Movie One (2024)" / "Movie.One.2024.1080p.mkv"
    assert restored_path.exists()
    assert restored_path.read_text(encoding="utf-8") == "deleted"

    restore_delete_response = client.delete(
        "/api/fs/deleted-files",
        params={"path": str(restored_path)},
    )
    assert restore_delete_response.status_code == 403

    trash_dir.mkdir(parents=True, exist_ok=True)
    deleted_again = trash_dir / "Movie.One.2024.1080p.mkv.20260511T130000123456Z"
    deleted_again.write_text("deleted-again", encoding="utf-8")
    delete_response = client.delete(
        "/api/fs/deleted-files",
        params={"path": str(deleted_again)},
    )
    assert delete_response.status_code == 200
    assert not deleted_again.exists()


def test_deleted_files_restore_conflict_returns_409(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    restore_target = nested_root / "Show (2020)" / "Season 01" / "Show.S01E01.1080p.mkv"
    restore_target.parent.mkdir(parents=True)
    restore_target.write_text("current", encoding="utf-8")

    deleted_file = (
        nested_root
        / ".deletedByLibrariarr"
        / "Show (2020)"
        / "Season 01"
        / "Show.S01E01.1080p.mkv.20260511T140000123456Z"
    )
    deleted_file.parent.mkdir(parents=True)
    deleted_file.write_text("deleted", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.post("/api/fs/deleted-files/restore", params={"path": str(deleted_file)})
    assert response.status_code == 409


def test_deleted_files_clear_all(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    trash_dir = nested_root / ".deletedByLibrariarr" / "Movie Two (2024)"
    trash_dir.mkdir(parents=True)
    (trash_dir / "Movie.Two.2024.720p.mkv.20260511T150000123456Z").write_text(
        "one",
        encoding="utf-8",
    )
    (trash_dir / "Movie.Two.2024.1080p.mkv.20260511T150100123456Z").write_text(
        "two",
        encoding="utf-8",
    )

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.post("/api/fs/deleted-files/clear")
    assert response.status_code == 200
    payload = response.json()
    assert payload["removed_files"] == 2
    assert not (nested_root / ".deletedByLibrariarr").exists()
