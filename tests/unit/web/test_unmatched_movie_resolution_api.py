from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from librariarr.projection.provenance import ProjectionStateStore
from librariarr.web import create_app
from librariarr.web.routers import unmatched_movie_router as unmatched_movie_router_module


def _write_config(path: Path, managed_root: Path, library_root: Path) -> None:
    path.write_text(
        (
            "paths:\n"
            "  movie_root_mappings:\n"
            f"    - managed_root: {managed_root}\n"
            f"      library_root: {library_root}\n"
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


class _StubRadarrClient:
    def __init__(self, _url: str, _api_key: str) -> None:
        pass

    def lookup_movies(self, term: str) -> list[dict]:
        if term == "tmdb:2721":
            return [
                {
                    "id": 1,
                    "title": "Z",
                    "year": 1969,
                    "path": "/library/Z (1969)",
                    "tmdbId": 2721,
                    "imdbId": "tt0065234",
                }
            ]
        return [
            {
                "id": 2,
                "title": "Zwei Banditen",
                "year": 1971,
                "path": "/library/Zwei Banditen (1971)",
                "tmdbId": 555,
                "imdbId": "tt0060000",
            }
        ]

    def get_movie(self, movie_id: int) -> dict | None:
        if movie_id in {1, 2}:
            return {"id": movie_id, "title": "stub"}
        return None


def test_unmatched_movie_candidates_includes_mapping_conflict(
    tmp_path: Path,
    monkeypatch,
) -> None:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"
    managed_root.mkdir()
    library_root.mkdir()

    folder = managed_root / "Z (1969) FSK16"
    folder.mkdir()
    (folder / "movie.nfo").write_text("tmdbid=2721\n", encoding="utf-8")

    state_db = tmp_path / "projection-state.sqlite"
    store = ProjectionStateStore(state_db)
    conflicting_folder = managed_root / "Different (1970)"
    conflicting_folder.mkdir()
    assert store.set_managed_folder(1, conflicting_folder) is True

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, managed_root, library_root)

    monkeypatch.setattr(unmatched_movie_router_module, "RadarrClient", _StubRadarrClient)
    monkeypatch.setattr(
        unmatched_movie_router_module,
        "_projection_state_db_path",
        lambda: state_db,
    )

    client = TestClient(create_app(config_path=config_path))
    response = client.get("/api/fs/unmatched-movie-candidates", params={"path": str(folder)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["nfo_ids"]["tmdb_id"] == "2721"
    by_id = {item["movie_id"]: item for item in payload["candidates"]}
    assert by_id[1]["mapping_conflict"] is True


def test_unmatched_movie_resolve_requires_force_for_conflict(
    tmp_path: Path,
    monkeypatch,
) -> None:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"
    managed_root.mkdir()
    library_root.mkdir()

    folder = managed_root / "Z (1969) FSK16"
    folder.mkdir()

    state_db = tmp_path / "projection-state.sqlite"
    store = ProjectionStateStore(state_db)
    assert store.set_managed_folder(2, folder) is True

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, managed_root, library_root)

    monkeypatch.setattr(unmatched_movie_router_module, "RadarrClient", _StubRadarrClient)
    monkeypatch.setattr(
        unmatched_movie_router_module,
        "_projection_state_db_path",
        lambda: state_db,
    )

    client = TestClient(create_app(config_path=config_path))

    blocked = client.post(
        "/api/fs/unmatched-movie-resolve",
        json={"path": str(folder), "movie_id": 1},
    )
    assert blocked.status_code == 409

    allowed = client.post(
        "/api/fs/unmatched-movie-resolve",
        json={"path": str(folder), "movie_id": 1, "force_takeover": True},
    )
    assert allowed.status_code == 200

    updated_store = ProjectionStateStore(state_db)
    mappings = updated_store.get_managed_folders_by_movie_ids()
    assert mappings[1] == folder
    assert 2 not in mappings
