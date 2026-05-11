from pathlib import Path
from unittest.mock import patch

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


def test_recycle_orphaned_managed_folder_success(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    orphan_folder = nested_root / "Movie Three (2024)"
    orphan_folder.mkdir(parents=True)
    (orphan_folder / "notes.txt").write_text("metadata", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.post(
        "/api/fs/orphaned-managed-folders/recycle",
        params={"path": str(orphan_folder)},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == str(orphan_folder)
    assert payload["recycled_path"].startswith(str(nested_root / ".deletedByLibrariarr"))
    assert not orphan_folder.exists()
    assert Path(payload["recycled_path"]).exists()


def test_recycle_orphaned_managed_folder_rejects_video_folder(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    non_orphan_folder = nested_root / "Movie Four (2023)"
    non_orphan_folder.mkdir(parents=True)
    (non_orphan_folder / "Movie.Four.2023.1080p.mkv").write_text("video", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.post(
        "/api/fs/orphaned-managed-folders/recycle",
        params={"path": str(non_orphan_folder)},
    )
    assert response.status_code == 409


def test_recycle_orphaned_managed_folder_rejects_missing_path(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    missing_folder = nested_root / "Movie Missing (2023)"

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.post(
        "/api/fs/orphaned-managed-folders/recycle",
        params={"path": str(missing_folder)},
    )
    assert response.status_code == 404


def test_recycle_orphaned_managed_folder_rejects_file_target(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    file_target = nested_root / "Movie Target (2023)"
    file_target.write_text("not a directory", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.post(
        "/api/fs/orphaned-managed-folders/recycle",
        params={"path": str(file_target)},
    )
    assert response.status_code == 400


def test_recycle_orphaned_managed_folder_rejects_non_parseable_name(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    non_parseable = nested_root / "Not A Movie Folder"
    non_parseable.mkdir(parents=True)

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.post(
        "/api/fs/orphaned-managed-folders/recycle",
        params={"path": str(non_parseable)},
    )
    assert response.status_code == 409


def test_recycle_orphaned_managed_folder_rejects_outside_managed_root(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    outside_folder = tmp_path / "outside" / "Movie Five (2022)"
    outside_folder.mkdir(parents=True)
    (outside_folder / "note.txt").write_text("orphan", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.post(
        "/api/fs/orphaned-managed-folders/recycle",
        params={"path": str(outside_folder)},
    )
    assert response.status_code == 403


def test_recycle_orphaned_managed_folder_rejects_managed_root(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.post(
        "/api/fs/orphaned-managed-folders/recycle",
        params={"path": str(nested_root)},
    )
    assert response.status_code == 400


def test_recycle_orphaned_managed_folder_rejects_path_inside_trash(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    trashed = (
        nested_root / ".deletedByLibrariarr" / "Movie Seven (2021).orphan.20260511T180000123456Z"
    )
    trashed.mkdir(parents=True)

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.post(
        "/api/fs/orphaned-managed-folders/recycle",
        params={"path": str(trashed)},
    )
    assert response.status_code == 400


def test_recycle_orphaned_managed_folder_collision_uses_incremented_suffix(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    orphan_folder = nested_root / "Movie Eight (2020)"
    orphan_folder.mkdir(parents=True)
    (orphan_folder / "notes.txt").write_text("metadata", encoding="utf-8")

    timestamp = "20260511T190000123456Z"
    collision_target = (
        nested_root / ".deletedByLibrariarr" / f"Movie Eight (2020).orphan.{timestamp}"
    )
    collision_target.mkdir(parents=True)

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    class _FixedDatetime:
        @staticmethod
        def now(_tz=None):
            from datetime import UTC, datetime

            return datetime(2026, 5, 11, 19, 0, 0, 123456, tzinfo=UTC)

    with patch("librariarr.web.routers.fs_router.datetime", _FixedDatetime):
        response = client.post(
            "/api/fs/orphaned-managed-folders/recycle",
            params={"path": str(orphan_folder)},
        )

    assert response.status_code == 200
    recycled_path = Path(response.json()["recycled_path"])
    assert recycled_path.name == f"Movie Eight (2020).orphan.{timestamp}.1"


def test_deleted_files_restore_path_normalizes_directory_soft_delete_suffix(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    deleted_dir = (
        nested_root / ".deletedByLibrariarr" / "Movie Six (2024).orphan.20260511T180000123456Z"
    )
    deleted_dir.mkdir(parents=True)
    deleted_file = deleted_dir / "Movie.Six.2024.1080p.mkv"
    deleted_file.write_text("deleted", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    list_response = client.get("/api/fs/deleted-files")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["restore_path"] == str(
        nested_root / "Movie Six (2024)" / "Movie.Six.2024.1080p.mkv"
    )

    restore_response = client.post(
        "/api/fs/deleted-files/restore",
        params={"path": str(deleted_file)},
    )
    assert restore_response.status_code == 200
    restored_path = nested_root / "Movie Six (2024)" / "Movie.Six.2024.1080p.mkv"
    assert restored_path.exists()
