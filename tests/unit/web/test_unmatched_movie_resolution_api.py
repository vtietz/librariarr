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
        if movie_id in {1, 2, 3}:
            return {"id": movie_id, "title": "stub"}
        return None


def _build_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, Path]:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"
    managed_root.mkdir()
    library_root.mkdir()

    state_db = tmp_path / "projection-state.sqlite"
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, managed_root, library_root)

    monkeypatch.setattr(unmatched_movie_router_module, "RadarrClient", _StubRadarrClient)
    monkeypatch.setattr(
        unmatched_movie_router_module,
        "_projection_state_db_path",
        lambda: state_db,
    )
    return TestClient(create_app(config_path=config_path)), state_db


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
    client, state_db = _build_client(tmp_path, monkeypatch)
    managed_root = tmp_path / "managed"

    folder = managed_root / "Z (1969) FSK16"
    folder.mkdir()

    store = ProjectionStateStore(state_db)
    assert store.set_managed_folder(2, folder) is True

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


def test_unmatched_movie_resolve_legacy_payload_defaults_to_incoming(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, state_db = _build_client(tmp_path, monkeypatch)
    managed_root = tmp_path / "managed"
    folder = managed_root / "Arrival (2016)"
    folder.mkdir()

    response = client.post(
        "/api/fs/unmatched-movie-resolve",
        json={"path": str(folder), "movie_id": 1},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == str(folder)
    assert payload["winner_strategy"] == "incoming"
    assert payload["winner_path"] == str(folder)
    assert payload["loser_path"] is None
    assert payload["loser_quarantined"] is False

    updated_store = ProjectionStateStore(state_db)
    mappings = updated_store.get_managed_folders_by_movie_ids()
    assert mappings[1] == folder


def test_unmatched_movie_resolve_allows_stale_owner_without_force(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, state_db = _build_client(tmp_path, monkeypatch)
    managed_root = tmp_path / "managed"
    contested_folder = managed_root / "Contested (2012)"
    contested_folder.mkdir()

    store = ProjectionStateStore(state_db)
    assert store.set_managed_folder(99, contested_folder) is True

    allowed = client.post(
        "/api/fs/unmatched-movie-resolve",
        json={"path": str(contested_folder), "movie_id": 1},
    )
    assert allowed.status_code == 200
    payload = allowed.json()
    assert payload["conflict_owner_was_stale"] is True

    updated_store = ProjectionStateStore(state_db)
    mappings = updated_store.get_managed_folders_by_movie_ids()
    assert mappings[1] == contested_folder
    assert 99 not in mappings


def test_unmatched_movie_resolve_winner_existing_keeps_current_mapping(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, state_db = _build_client(tmp_path, monkeypatch)
    managed_root = tmp_path / "managed"
    mapped_folder = managed_root / "Canonical (2000)"
    incoming_folder = managed_root / "Canonical (2000) FSK16"
    mapped_folder.mkdir()
    incoming_folder.mkdir()

    store = ProjectionStateStore(state_db)
    assert store.set_managed_folder(1, mapped_folder) is True

    response = client.post(
        "/api/fs/unmatched-movie-resolve",
        json={
            "path": str(incoming_folder),
            "movie_id": 1,
            "winner_strategy": "existing",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["winner_path"] == str(mapped_folder)
    assert payload["loser_path"] == str(incoming_folder)
    assert payload["loser_quarantined"] is False

    updated_store = ProjectionStateStore(state_db)
    mappings = updated_store.get_managed_folders_by_movie_ids()
    assert mappings[1] == mapped_folder
    assert incoming_folder.exists()


def test_unmatched_movie_resolve_quarantines_loser_when_requested(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, state_db = _build_client(tmp_path, monkeypatch)
    managed_root = tmp_path / "managed"
    mapped_folder = managed_root / "Preferred (2004)"
    incoming_folder = managed_root / "Preferred (2004) FSK16"
    mapped_folder.mkdir()
    incoming_folder.mkdir()
    (incoming_folder / "movie.mkv").write_text("stub", encoding="utf-8")

    store = ProjectionStateStore(state_db)
    assert store.set_managed_folder(1, mapped_folder) is True

    response = client.post(
        "/api/fs/unmatched-movie-resolve",
        json={
            "path": str(incoming_folder),
            "movie_id": 1,
            "winner_strategy": "existing",
            "quarantine_loser": True,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["loser_quarantined"] is True
    quarantine_path = Path(payload["loser_quarantine_path"])
    assert quarantine_path.parent == managed_root / ".deletedByLibrariarr"
    assert quarantine_path.exists()
    assert not incoming_folder.exists()


def test_unmatched_movie_resolve_quarantine_skips_loser_outside_managed_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, state_db = _build_client(tmp_path, monkeypatch)
    managed_root = tmp_path / "managed"
    incoming_folder = managed_root / "Winner (2001)"
    incoming_folder.mkdir()

    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    outside_folder = outside_root / "Legacy (2001)"
    outside_folder.mkdir()

    store = ProjectionStateStore(state_db)
    assert store.set_managed_folder(1, outside_folder) is True

    response = client.post(
        "/api/fs/unmatched-movie-resolve",
        json={
            "path": str(incoming_folder),
            "movie_id": 1,
            "winner_strategy": "incoming",
            "quarantine_loser": True,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["loser_path"] == str(outside_folder)
    assert payload["loser_quarantined"] is False
    assert payload["loser_quarantine_path"] is None
    assert outside_folder.exists()


def test_unmatched_movie_resolve_quarantine_loser_mapped_to_active_owner_blocks_without_force(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, state_db = _build_client(tmp_path, monkeypatch)
    managed_root = tmp_path / "managed"
    mapped_folder = managed_root / "Canonical (2000)"
    incoming_folder = managed_root / "Canonical (2000) FSK16"
    mapped_folder.mkdir()
    incoming_folder.mkdir()

    store = ProjectionStateStore(state_db)
    assert store.set_managed_folder(1, mapped_folder) is True
    assert store.set_managed_folder(2, incoming_folder) is True

    response = client.post(
        "/api/fs/unmatched-movie-resolve",
        json={
            "path": str(incoming_folder),
            "movie_id": 1,
            "winner_strategy": "existing",
            "quarantine_loser": True,
            "force_takeover": False,
        },
    )

    assert response.status_code == 409
    assert incoming_folder.exists()

    updated_store = ProjectionStateStore(state_db)
    mappings = updated_store.get_managed_folders_by_movie_ids()
    assert mappings[2] == incoming_folder


def test_unmatched_movie_resolve_quarantine_loser_mapped_to_stale_owner_removes_mapping(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, state_db = _build_client(tmp_path, monkeypatch)
    managed_root = tmp_path / "managed"
    mapped_folder = managed_root / "Canonical (2000)"
    incoming_folder = managed_root / "Canonical (2000) FSK16"
    mapped_folder.mkdir()
    incoming_folder.mkdir()

    store = ProjectionStateStore(state_db)
    assert store.set_managed_folder(1, mapped_folder) is True
    assert store.set_managed_folder(99, incoming_folder) is True

    response = client.post(
        "/api/fs/unmatched-movie-resolve",
        json={
            "path": str(incoming_folder),
            "movie_id": 1,
            "winner_strategy": "existing",
            "quarantine_loser": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["loser_quarantined"] is True
    assert not incoming_folder.exists()

    updated_store = ProjectionStateStore(state_db)
    mappings = updated_store.get_managed_folders_by_movie_ids()
    assert 99 not in mappings


def test_unmatched_movie_resolve_quarantine_loser_mapped_to_active_owner_allows_with_force(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, state_db = _build_client(tmp_path, monkeypatch)
    managed_root = tmp_path / "managed"
    mapped_folder = managed_root / "Canonical (2000)"
    incoming_folder = managed_root / "Canonical (2000) FSK16"
    mapped_folder.mkdir()
    incoming_folder.mkdir()
    (incoming_folder / "movie.mkv").write_text("stub", encoding="utf-8")

    store = ProjectionStateStore(state_db)
    assert store.set_managed_folder(1, mapped_folder) is True
    assert store.set_managed_folder(2, incoming_folder) is True

    response = client.post(
        "/api/fs/unmatched-movie-resolve",
        json={
            "path": str(incoming_folder),
            "movie_id": 1,
            "winner_strategy": "existing",
            "quarantine_loser": True,
            "force_takeover": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["loser_quarantined"] is True
    assert not incoming_folder.exists()

    updated_store = ProjectionStateStore(state_db)
    mappings = updated_store.get_managed_folders_by_movie_ids()
    assert mappings[1] == mapped_folder
    assert 2 not in mappings


def test_unmatched_movie_resolve_rejects_invalid_winner_strategy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, _state_db = _build_client(tmp_path, monkeypatch)
    managed_root = tmp_path / "managed"
    folder = managed_root / "Arrival (2016)"
    folder.mkdir()

    response = client.post(
        "/api/fs/unmatched-movie-resolve",
        json={
            "path": str(folder),
            "movie_id": 1,
            "winner_strategy": "invalid",
        },
    )

    assert response.status_code == 400


def test_unmatched_movie_resolve_winner_existing_requires_existing_mapping(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, _state_db = _build_client(tmp_path, monkeypatch)
    managed_root = tmp_path / "managed"
    incoming_folder = managed_root / "Arrival (2016) FSK16"
    incoming_folder.mkdir()

    response = client.post(
        "/api/fs/unmatched-movie-resolve",
        json={
            "path": str(incoming_folder),
            "movie_id": 1,
            "winner_strategy": "existing",
        },
    )

    assert response.status_code == 400


def test_unmatched_movie_resolve_winner_existing_rejects_missing_winner_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, state_db = _build_client(tmp_path, monkeypatch)
    managed_root = tmp_path / "managed"
    mapped_folder = managed_root / "Canonical (2000)"
    incoming_folder = managed_root / "Canonical (2000) FSK16"
    mapped_folder.mkdir()
    incoming_folder.mkdir()

    store = ProjectionStateStore(state_db)
    assert store.set_managed_folder(1, mapped_folder) is True
    mapped_folder.rmdir()

    response = client.post(
        "/api/fs/unmatched-movie-resolve",
        json={
            "path": str(incoming_folder),
            "movie_id": 1,
            "winner_strategy": "existing",
        },
    )

    assert response.status_code == 400


def test_unmatched_movie_resolve_winner_existing_rejects_non_directory_winner_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, state_db = _build_client(tmp_path, monkeypatch)
    managed_root = tmp_path / "managed"
    mapped_file = managed_root / "Canonical (2000).txt"
    incoming_folder = managed_root / "Canonical (2000) FSK16"
    mapped_file.write_text("stub", encoding="utf-8")
    incoming_folder.mkdir()

    store = ProjectionStateStore(state_db)
    assert store.set_managed_folder(1, mapped_file) is True

    response = client.post(
        "/api/fs/unmatched-movie-resolve",
        json={
            "path": str(incoming_folder),
            "movie_id": 1,
            "winner_strategy": "existing",
        },
    )

    assert response.status_code == 400
