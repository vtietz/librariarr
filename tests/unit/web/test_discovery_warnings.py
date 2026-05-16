import time
from pathlib import Path

from fastapi.testclient import TestClient

from librariarr.projection.models import ProjectedFileState
from librariarr.projection.provenance import ProjectionStateStore
from librariarr.web import create_app


def _write_config_with_trailer_excludes(path: Path, nested_root: Path, shadow_root: Path) -> None:
    path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
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


def _write_config_with_excludes(
    path: Path,
    nested_root: Path,
    shadow_root: Path,
    *,
    exclude_paths: list[str],
) -> None:
    rendered_excludes = "".join(f"    - '{pattern}'\n" for pattern in exclude_paths)
    path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            f"    - nested_root: {nested_root}\n"
            f"      shadow_root: {shadow_root}\n"
            "  movie_root_mappings:\n"
            f"    - managed_root: {nested_root}\n"
            f"      library_root: {shadow_root}\n"
            "  exclude_paths:\n"
            f"{rendered_excludes}"
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
    monkeypatch,
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
    monkeypatch.setenv("LIBRARIARR_PROJECTION_STATE_PATH", str(tmp_path / "movie-state.db"))
    monkeypatch.setenv("LIBRARIARR_SONARR_PROJECTION_STATE_PATH", str(tmp_path / "series-state.db"))

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.get("/api/fs/discovery-warnings")

    assert response.status_code == 200
    payload = response.json()
    assert all(item["path"] != str(movie_dir) for item in payload["excluded_movie_candidates"])


def test_discovery_warnings_reports_unmanaged_shadow_video_files(
    tmp_path: Path, monkeypatch
) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    unmanaged_shadow_file = shadow_root / "Movie A (2022)" / "Movie.A.2022.1080p.mkv"
    unmanaged_shadow_file.parent.mkdir(parents=True)
    unmanaged_shadow_file.write_text("x", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    _write_config_with_trailer_excludes(config_path, nested_root, shadow_root)
    monkeypatch.setenv("LIBRARIARR_PROJECTION_STATE_PATH", str(tmp_path / "movie-state.db"))
    monkeypatch.setenv("LIBRARIARR_SONARR_PROJECTION_STATE_PATH", str(tmp_path / "series-state.db"))

    app = create_app(config_path=config_path)
    client = TestClient(app)

    payload = None
    for _ in range(5):
        response = client.get("/api/fs/discovery-warnings")
        assert response.status_code == 200
        payload = response.json()
        if payload["summary"]["unmanaged_shadow_video_files"] == 1:
            break
        time.sleep(0.05)

    assert payload is not None
    assert payload["summary"]["unmanaged_shadow_video_files"] == 1
    assert payload["unmanaged_shadow_video_files"][0]["path"] == str(unmanaged_shadow_file)


def test_orphaned_managed_candidates_respect_exclude_paths(tmp_path: Path, monkeypatch) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    managed_container = nested_root / "Movie A (2022)"
    excluded_orphan = managed_container / "@eaDir" / "Movie A (2022).mkv"
    excluded_orphan.mkdir(parents=True)

    config_path = tmp_path / "config.yaml"
    _write_config_with_excludes(
        config_path,
        nested_root,
        shadow_root,
        exclude_paths=["@eaDir/", "*-trailer.*"],
    )
    monkeypatch.setenv("LIBRARIARR_PROJECTION_STATE_PATH", str(tmp_path / "movie-state.db"))
    monkeypatch.setenv("LIBRARIARR_SONARR_PROJECTION_STATE_PATH", str(tmp_path / "series-state.db"))

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.get("/api/fs/discovery-warnings")

    assert response.status_code == 200
    payload = response.json()
    orphan_paths = {item["path"] for item in payload["orphaned_managed_movie_candidates"]}
    assert str(managed_container) not in orphan_paths
    assert str(excluded_orphan) not in orphan_paths
    assert all("/@eaDir/" not in path for path in orphan_paths)


def test_orphaned_managed_candidates_require_movie_like_folder_name(
    tmp_path: Path, monkeypatch
) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    non_canonical_empty = nested_root / "Kids" / "Movie Without Year"
    non_canonical_empty.mkdir(parents=True)
    (non_canonical_empty / "poster.jpg").write_text("x", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    _write_config_with_trailer_excludes(config_path, nested_root, shadow_root)
    monkeypatch.setenv("LIBRARIARR_PROJECTION_STATE_PATH", str(tmp_path / "movie-state.db"))
    monkeypatch.setenv("LIBRARIARR_SONARR_PROJECTION_STATE_PATH", str(tmp_path / "series-state.db"))

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.get("/api/fs/discovery-warnings")

    assert response.status_code == 200
    payload = response.json()
    orphan_paths = {item["path"] for item in payload["orphaned_managed_movie_candidates"]}
    assert str(non_canonical_empty) not in orphan_paths


def test_unmatched_managed_candidates_include_video_folders_without_mapping(
    tmp_path: Path, monkeypatch
) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    unmatched_movie = nested_root / "Movie Unmatched"
    unmatched_movie.mkdir(parents=True)
    (unmatched_movie / "Movie.Unmatched.2020.1080p.mkv").write_text("x", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    _write_config_with_trailer_excludes(config_path, nested_root, shadow_root)
    monkeypatch.setenv("LIBRARIARR_PROJECTION_STATE_PATH", str(tmp_path / "movie-state.db"))
    monkeypatch.setenv("LIBRARIARR_SONARR_PROJECTION_STATE_PATH", str(tmp_path / "series-state.db"))

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.get("/api/fs/discovery-warnings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["unmatched_managed_movie_candidates"] >= 1
    unmatched_paths = {item["path"] for item in payload["unmatched_managed_movie_candidates"]}
    assert str(unmatched_movie) in unmatched_paths


def test_discovery_warnings_reports_mapping_collisions(tmp_path: Path, monkeypatch) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    shared_folder = nested_root / "Shared Movie Folder"
    shared_folder.mkdir(parents=True)
    shared_source = shared_folder / "shared-file.mkv"
    shared_source.write_text("x", encoding="utf-8")

    state_db = tmp_path / "movie-state.db"
    store = ProjectionStateStore(state_db)
    store.set_managed_folders_bulk([(1001, shared_folder), (1002, shared_folder)])
    store.upsert_projected_files(
        [
            ProjectedFileState(
                movie_id=1001,
                dest_path=str(shadow_root / "A" / "shared-file.mkv"),
                source_path=str(shared_source),
                kind="video",
                managed=True,
                source_dev=None,
                source_inode=None,
                size=1,
                mtime=1.0,
                file_hash=None,
            ),
            ProjectedFileState(
                movie_id=1002,
                dest_path=str(shadow_root / "B" / "shared-file.mkv"),
                source_path=str(shared_source),
                kind="video",
                managed=True,
                source_dev=None,
                source_inode=None,
                size=1,
                mtime=1.0,
                file_hash=None,
            ),
        ]
    )

    config_path = tmp_path / "config.yaml"
    _write_config_with_trailer_excludes(config_path, nested_root, shadow_root)
    monkeypatch.setenv("LIBRARIARR_PROJECTION_STATE_PATH", str(state_db))
    monkeypatch.setenv("LIBRARIARR_SONARR_PROJECTION_STATE_PATH", str(tmp_path / "series.db"))

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.get("/api/fs/discovery-warnings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["mapping_collision_candidates"] >= 2
    collision_types = {item["type"] for item in payload["mapping_collision_candidates"]}
    assert "shared_managed_folder" in collision_types
    assert "shared_source_file" in collision_types

def test_discovery_warnings_include_all_returns_all_duplicate_groups(
    tmp_path: Path,
    monkeypatch,
) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    for index in range(3):
        group_root = nested_root / f"group-{index}"
        first = group_root / f"Example Movie {index} (2020)"
        second = group_root / ".deletedByTMM" / f"Example Movie {index} (2020)"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        (first / "movie.mkv").write_text("x", encoding="utf-8")
        (second / "movie.mkv").write_text("x", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    _write_config_with_trailer_excludes(config_path, nested_root, shadow_root)
    monkeypatch.setenv("LIBRARIARR_PROJECTION_STATE_PATH", str(tmp_path / "movie-state.db"))
    monkeypatch.setenv("LIBRARIARR_SONARR_PROJECTION_STATE_PATH", str(tmp_path / "series-state.db"))

    app = create_app(config_path=config_path)
    client = TestClient(app)

    limited = client.get("/api/fs/discovery-warnings", params={"limit": 1})
    assert limited.status_code == 200
    limited_payload = limited.json()
    assert len(limited_payload["duplicate_movie_candidates"]) == 1
    assert limited_payload["truncated"]["duplicate_movie_candidates"] is True

    include_all = client.get(
        "/api/fs/discovery-warnings",
        params={"limit": 1, "include_all": "true"},
    )
    assert include_all.status_code == 200
    include_all_payload = include_all.json()
    assert include_all_payload["summary"]["duplicate_movie_candidates"] == 3
    assert len(include_all_payload["duplicate_movie_candidates"]) == 3
    assert include_all_payload["truncated"]["duplicate_movie_candidates"] is False


def test_discovery_warnings_ignores_non_movie_proof_leaf_folders(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    movie_folder = nested_root / "FSK12" / "Movie With Proof (2015)"
    movie_folder.mkdir(parents=True)
    (movie_folder / "movie.mkv").write_text("x", encoding="utf-8")
    proof_leaf = nested_root / "FSK12" / "Collection Parent" / "Proof"
    proof_leaf.mkdir(parents=True)

    config_path = tmp_path / "config.yaml"
    _write_config_with_trailer_excludes(config_path, nested_root, shadow_root)

    app = create_app(config_path=config_path)
    client = TestClient(app)

    response = client.get("/api/fs/discovery-warnings")

    assert response.status_code == 200
    payload = response.json()
    orphaned_paths = {item["path"] for item in payload["orphaned_managed_movie_candidates"]}
    assert str(proof_leaf) not in orphaned_paths
