from __future__ import annotations

from pathlib import Path

import pytest

from librariarr.config import load_config

BASE_YAML = """
paths:
  movie_root_mappings:
    - managed_root: /data/movies/one
      library_root: /data/radarr_library/one
  series_root_mappings:
    - nested_root: /data/series/one
      shadow_root: /data/sonarr_library/one
radarr:
  url: http://radarr:7878
  api_key: test-key
"""


def write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_minimal_config_loads_with_defaults(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, BASE_YAML))
    assert config.radarr.enabled
    assert config.radarr.url == "http://radarr:7878"
    assert not config.sonarr.enabled
    assert config.runtime.consistency_interval_seconds == 300
    assert config.runtime.full_interval_minutes == 60
    assert config.runtime.startup_scope == "full"
    assert config.ingest.enabled
    assert config.ingest.replacement_delete_mode == "soft"
    assert ".mkv" in config.radarr.projection.managed_video_extensions
    assert ".deletedByLibrariarr/" in config.paths.exclude_paths


def test_env_overrides_arr_url_and_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LIBRARIARR_RADARR_URL", "http://elsewhere:1234")
    monkeypatch.setenv("LIBRARIARR_RADARR_API_KEY", "env-key")
    config = load_config(write(tmp_path, BASE_YAML))
    assert config.radarr.url == "http://elsewhere:1234"
    assert config.radarr.api_key == "env-key"


def test_missing_both_arr_sections_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="radarr or sonarr"):
        load_config(write(tmp_path, "paths: {movie_root_mappings: []}\n"))


def test_overlapping_movie_roots_are_rejected(tmp_path: Path) -> None:
    bad = BASE_YAML.replace("/data/radarr_library/one", "/data/movies/one/nested")
    with pytest.raises(ValueError, match="must not overlap"):
        load_config(write(tmp_path, bad))


def test_radarr_enabled_requires_movie_mappings(tmp_path: Path) -> None:
    yaml_text = """
paths: {}
radarr:
  url: http://radarr:7878
  api_key: k
"""
    with pytest.raises(ValueError, match="movie_root_mappings is required"):
        load_config(write(tmp_path, yaml_text))


def test_sonarr_enabled_requires_series_mappings(tmp_path: Path) -> None:
    yaml_text = """
paths:
  movie_root_mappings:
    - managed_root: /data/movies/one
      library_root: /data/radarr_library/one
radarr:
  url: http://radarr:7878
  api_key: k
sonarr:
  enabled: true
  url: http://sonarr:8989
  api_key: k
"""
    with pytest.raises(ValueError, match="series_root_mappings is required"):
        load_config(write(tmp_path, yaml_text))


def test_ingest_replacement_delete_mode_validation(tmp_path: Path) -> None:
    good = BASE_YAML + "ingest:\n  replacement_delete_mode: hard\n"
    assert load_config(write(tmp_path, good)).ingest.replacement_delete_mode == "hard"
    bad = BASE_YAML + "ingest:\n  replacement_delete_mode: nuke\n"
    with pytest.raises(ValueError, match="'soft' or 'hard'"):
        load_config(write(tmp_path, bad))


def test_runtime_startup_scope_validation(tmp_path: Path) -> None:
    good = BASE_YAML + 'runtime:\n  startup_scope: "off"\n'
    assert load_config(write(tmp_path, good)).runtime.startup_scope == "off"
    bad = BASE_YAML + "runtime:\n  startup_scope: sometimes\n"
    with pytest.raises(ValueError, match="startup_scope"):
        load_config(write(tmp_path, bad))


def test_unknown_legacy_keys_are_ignored(tmp_path: Path) -> None:
    legacy = BASE_YAML + (
        "cleanup:\n  sonarr_action_on_missing: unmonitor\n"
        "analysis:\n  use_nfo: true\n"
        "runtime:\n  maintenance_interval_minutes: 1440\n"
    )
    config = load_config(write(tmp_path, legacy))
    assert config.runtime.full_interval_minutes == 60


def test_video_extensions_are_normalized(tmp_path: Path) -> None:
    yaml_text = BASE_YAML + ("  projection:\n    managed_video_extensions: [MKV, '.Mp4']\n")
    config = load_config(write(tmp_path, yaml_text))
    assert config.radarr.projection.managed_video_extensions == [".mkv", ".mp4"]
