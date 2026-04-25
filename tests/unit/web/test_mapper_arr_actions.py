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


def _wait_for_job(client: TestClient, job_id: str, retries: int = 40) -> dict:
    for _ in range(retries):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload.get("status") in {"succeeded", "failed", "canceled"}:
            return payload
    raise AssertionError(f"Job {job_id} did not finish in time")


def test_mapped_directories_include_arr_state_and_missing_virtual_path(
    tmp_path: Path, monkeypatch
) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    movie_dir = nested_root / "Movie One"
    movie_dir.mkdir()
    (shadow_root / "Movie One").symlink_to(movie_dir, target_is_directory=True)

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    class StubRadarrClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_movies(self):
            return [
                {
                    "id": 1,
                    "title": "Movie One",
                    "path": str(shadow_root / "Movie One"),
                    "monitored": True,
                },
                {
                    "id": 2,
                    "title": "Ghost Movie",
                    "path": str(shadow_root / "Ghost Movie"),
                    "monitored": False,
                },
            ]

        def get_root_folders(self):
            return [{"path": str(shadow_root)}]

    monkeypatch.setattr("librariarr.web.mapped_arr_state.RadarrClient", StubRadarrClient)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    refresh_response = client.post("/api/fs/mapped-directories/refresh")
    assert refresh_response.status_code == 200
    refresh_job = _wait_for_job(client, refresh_response.json()["job_id"])
    assert refresh_job["status"] == "succeeded"

    response = client.get("/api/fs/mapped-directories", params={"include_arr_state": "true"})

    assert response.status_code == 200
    payload = response.json()

    movie_one = next(
        item for item in payload["items"] if item["virtual_path"] == str(shadow_root / "Movie One")
    )
    assert movie_one["arr_state"] == "ok"
    assert movie_one["arr_movie_id"] == 1

    ghost_movie = next(
        item
        for item in payload["items"]
        if item["virtual_path"] == str(shadow_root / "Ghost Movie")
    )
    assert ghost_movie["arr_state"] == "missing_virtual_path"
    assert ghost_movie["arr_movie_id"] == 2
    assert ghost_movie["real_path"] == ""
    assert ghost_movie["target_exists"] is False


def test_refresh_radarr_movie_endpoint_forces_refresh(tmp_path: Path, monkeypatch) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    calls: list[tuple[int, bool]] = []

    class StubRadarrClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def refresh_movie(self, movie_id: int, force: bool = False):
            calls.append((movie_id, force))
            return True

    monkeypatch.setattr("librariarr.web.operations.RadarrClient", StubRadarrClient)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.post("/api/radarr/movies/42/refresh")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["movie_id"] == 42
    assert payload["started"] is True
    assert calls == [(42, True)]


def test_maintenance_reconcile_scoped_path_forwards_affected_path(
    tmp_path: Path, monkeypatch
) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    selected_path = nested_root / "Scoped Movie"

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    captured: list[tuple[set[Path] | None, bool]] = []

    class StubService:
        def __init__(self, *_args, **_kwargs):
            pass

        def reconcile(
            self,
            affected_paths: set[Path] | None = None,
            *,
            refresh_arr_root_availability: bool = True,
        ):
            captured.append((affected_paths, refresh_arr_root_availability))
            return False

    monkeypatch.setattr("librariarr.web.maintenance_ops.LibrariArrService", StubService)
    monkeypatch.setattr(
        "librariarr.web.maintenance_ops.build_path_mapping_outcome",
        lambda **_kwargs: {
            "status": "not_found_in_arr",
            "arr": "radarr",
            "message": "No Arr entry",
            "movie_id": None,
            "series_id": None,
        },
    )

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.post("/api/maintenance/reconcile", params={"path": str(selected_path)})

    assert response.status_code == 200
    job = _wait_for_job(client, response.json()["job_id"])
    assert job["status"] == "succeeded"
    assert captured == [({selected_path}, False)]


def test_scoped_reconcile_status_is_exposed_in_mapped_directories(
    tmp_path: Path, monkeypatch
) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    movie_dir = nested_root / "Movie One"
    movie_dir.mkdir()
    (shadow_root / "Movie One").symlink_to(movie_dir, target_is_directory=True)

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)

    class StubService:
        def __init__(self, *_args, **_kwargs):
            pass

        def reconcile(
            self,
            affected_paths: set[Path] | None = None,
            *,
            refresh_arr_root_availability: bool = True,
        ):
            return False

    monkeypatch.setattr("librariarr.web.maintenance_ops.LibrariArrService", StubService)
    monkeypatch.setattr(
        "librariarr.web.maintenance_ops.build_path_mapping_outcome",
        lambda **_kwargs: {
            "status": "success",
            "arr": "radarr",
            "message": "Movie One",
            "movie_id": 101,
            "series_id": None,
        },
    )

    app = create_app(config_path=config_path)
    client = TestClient(app)

    reconcile_response = client.post(
        "/api/maintenance/reconcile",
        params={"path": str(movie_dir)},
    )
    assert reconcile_response.status_code == 200
    reconcile_job = _wait_for_job(client, reconcile_response.json()["job_id"])
    assert reconcile_job["status"] == "succeeded"

    mapped_response = client.get("/api/fs/mapped-directories")
    assert mapped_response.status_code == 200
    payload = mapped_response.json()

    item = next(entry for entry in payload["items"] if entry["real_path"] == str(movie_dir))
    assert item["last_reconcile_status"] == "success"
    assert item["last_reconcile_arr"] == "radarr"
    assert item["last_reconcile_movie_id"] == 101
    assert isinstance(item["last_reconcile_updated_at_ms"], int)
