from pathlib import Path

import pytest

from librariarr.config import load_config

CONFIG_CONTENT = """
paths:
  root_mappings:
    - nested_root: /data/movies/one
      shadow_root: /data/radarr_library/one
radarr:
  url: http://radarr:7878
  api_key: test-key
quality_map:
  - match: [\"1080p\", \"x265\"]
    target_id: 7
cleanup:
  remove_orphaned_links: true
  unmonitor_on_delete: true
  delete_from_radarr_on_missing: false
runtime:
  debounce_seconds: 8
  maintenance_interval_minutes: 1440
analysis:
  use_nfo: false
  use_media_probe: false
  media_probe_bin: ffprobe
""".strip()


def test_load_config_reads_yaml_values(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG_CONTENT, encoding="utf-8")

    monkeypatch.delenv("LIBRARIARR_RADARR_URL", raising=False)
    monkeypatch.delenv("LIBRARIARR_RADARR_API_KEY", raising=False)
    monkeypatch.delenv("LIBRARIARR_SHADOW_ROOT", raising=False)
    monkeypatch.delenv("LIBRARIARR_NESTED_ROOTS", raising=False)

    config = load_config(config_path)

    assert len(config.paths.root_mappings) == 1
    assert config.paths.root_mappings[0].nested_root == "/data/movies/one"
    assert config.paths.root_mappings[0].shadow_root == "/data/radarr_library/one"
    assert config.radarr.url == "http://radarr:7878"
    assert config.radarr.api_key == "test-key"
    assert config.radarr.auto_add_unmatched is False
    assert config.radarr.auto_add_quality_profile_id is None
    assert config.radarr.auto_add_search_on_add is False
    assert config.radarr.auto_add_monitored is True
    assert config.quality_map[0].target_id == 7
    assert config.analysis.use_nfo is False
    assert config.analysis.use_media_probe is False
    assert config.analysis.media_probe_bin == "ffprobe"


def test_only_radarr_url_and_api_key_env_overrides_are_applied(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG_CONTENT, encoding="utf-8")

    monkeypatch.setenv("LIBRARIARR_RADARR_URL", "http://radarr.local:7878")
    monkeypatch.setenv("LIBRARIARR_RADARR_API_KEY", "env-key")
    monkeypatch.setenv("LIBRARIARR_SHADOW_ROOT", "/data/custom_shadow")
    monkeypatch.setenv("LIBRARIARR_NESTED_ROOTS", "/a,/b")
    monkeypatch.setenv("LIBRARIARR_USE_NFO_ANALYSIS", "true")
    monkeypatch.setenv("LIBRARIARR_USE_MEDIA_PROBE", "true")
    monkeypatch.setenv("LIBRARIARR_MEDIA_PROBE_BIN", "customprobe")

    config = load_config(config_path)

    assert config.radarr.url == "http://radarr.local:7878"
    assert config.radarr.api_key == "env-key"
    assert len(config.paths.root_mappings) == 1
    assert config.analysis.use_nfo is False
    assert config.analysis.use_media_probe is False
    assert config.analysis.media_probe_bin == "ffprobe"


def test_load_config_reads_root_mappings(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  root_mappings:\n"
            "    - nested_root: /data/movies/age_06\n"
            "      shadow_root: /data/radarr_library/age_06\n"
            "    - nested_root: /data/movies/age_12\n"
            "      shadow_root: /data/radarr_library/age_12\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "quality_map: []\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("LIBRARIARR_NESTED_ROOTS", raising=False)

    config = load_config(config_path)

    assert len(config.paths.root_mappings) == 2
    assert config.paths.root_mappings[0].nested_root == "/data/movies/age_06"
    assert config.paths.root_mappings[0].shadow_root == "/data/radarr_library/age_06"


def test_load_config_rejects_missing_root_mappings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  nested_roots:\n"
            "    - /data/movies/other\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "quality_map: []\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="paths.root_mappings is required"):
        load_config(config_path)


def test_load_config_allows_disabling_maintenance_interval(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  root_mappings:\n"
            "    - nested_root: /data/movies/one\n"
            "      shadow_root: /data/radarr_library/one\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "quality_map: []\n"
            "cleanup: {}\n"
            "runtime:\n"
            "  maintenance_interval_minutes: 0\n"
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("LIBRARIARR_RADARR_URL", raising=False)
    monkeypatch.delenv("LIBRARIARR_RADARR_API_KEY", raising=False)

    config = load_config(config_path)

    assert config.runtime.maintenance_interval_minutes == 0


def test_load_config_ingest_defaults(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG_CONTENT, encoding="utf-8")

    monkeypatch.delenv("LIBRARIARR_RADARR_URL", raising=False)
    monkeypatch.delenv("LIBRARIARR_RADARR_API_KEY", raising=False)

    config = load_config(config_path)

    assert config.ingest.enabled is False
    assert config.ingest.min_age_seconds == 30
    assert config.ingest.collision_policy == "qualify"


def test_load_config_rejects_deprecated_ingest_selector(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  root_mappings:\n"
            "    - nested_root: /data/movies/one\n"
            "      shadow_root: /data/radarr_library/one\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "quality_map: []\n"
            "cleanup: {}\n"
            "runtime: {}\n"
            "ingest:\n"
            "  enabled: true\n"
            "  selector: first\n"
        ),
        encoding="utf-8",
    )

    try:
        load_config(config_path)
    except ValueError as exc:
        assert "ingest.selector is no longer supported" in str(exc)
    else:
        raise AssertionError("Expected ValueError for deprecated ingest.selector")


def test_load_config_reads_radarr_auto_add_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  root_mappings:\n"
            "    - nested_root: /data/movies/one\n"
            "      shadow_root: /data/radarr_library/one\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "  auto_add_unmatched: true\n"
            "  auto_add_quality_profile_id: 7\n"
            "  auto_add_search_on_add: true\n"
            "  auto_add_monitored: false\n"
            "quality_map: []\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.radarr.auto_add_unmatched is True
    assert config.radarr.auto_add_quality_profile_id == 7
    assert config.radarr.auto_add_search_on_add is True
    assert config.radarr.auto_add_monitored is False
