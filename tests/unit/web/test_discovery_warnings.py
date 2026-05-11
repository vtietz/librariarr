import time
from pathlib import Path

from fastapi.testclient import TestClient

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

    excluded_orphan = nested_root / "Movie A (2022)" / "@eaDir" / "Movie A (2022).mkv"
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
    assert str(excluded_orphan) not in orphan_paths
    assert all("/@eaDir/" not in path for path in orphan_paths)


def test_orphaned_managed_candidates_are_naming_agnostic(tmp_path: Path, monkeypatch) -> None:
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
    assert str(non_canonical_empty) in orphan_paths


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
