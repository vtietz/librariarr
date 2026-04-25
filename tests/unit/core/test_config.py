from pathlib import Path

import pytest

from librariarr.config import DEFAULT_SCAN_VIDEO_EXTENSIONS, load_config

CONFIG_CONTENT = (
    "paths:\n"
    "  series_root_mappings:\n"
    "    - nested_root: /data/movies/one\n"
    "      shadow_root: /data/radarr_library/one\n"
    "  movie_root_mappings:\n"
    "    - managed_root: /data/movies/one\n"
    "      library_root: /data/radarr_library/one\n"
    "radarr:\n"
    "  url: http://radarr:7878\n"
    "  api_key: test-key\n"
    "  mapping:\n"
    "    quality_map:\n"
    '      - match: ["1080p", "x265"]\n'
    "        target_id: 7\n"
    "cleanup:\n"
    "  remove_orphaned_links: true\n"
    "runtime:\n"
    "  debounce_seconds: 8\n"
    "  maintenance_interval_minutes: 1440\n"
    "analysis:\n"
    "  use_nfo: false\n"
    "  use_media_probe: false\n"
    "  media_probe_bin: ffprobe\n"
).strip()


def test_load_config_reads_yaml_values(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG_CONTENT, encoding="utf-8")

    monkeypatch.delenv("LIBRARIARR_RADARR_URL", raising=False)
    monkeypatch.delenv("LIBRARIARR_RADARR_API_KEY", raising=False)
    monkeypatch.delenv("LIBRARIARR_SONARR_URL", raising=False)
    monkeypatch.delenv("LIBRARIARR_SONARR_API_KEY", raising=False)
    monkeypatch.delenv("LIBRARIARR_SHADOW_ROOT", raising=False)
    monkeypatch.delenv("LIBRARIARR_NESTED_ROOTS", raising=False)

    config = load_config(config_path)

    assert len(config.paths.series_root_mappings) == 1
    assert config.paths.series_root_mappings[0].nested_root == "/data/movies/one"
    assert config.paths.series_root_mappings[0].shadow_root == "/data/radarr_library/one"
    assert config.radarr.enabled is True
    assert config.radarr.url == "http://radarr:7878"
    assert config.radarr.api_key == "test-key"
    assert config.radarr.auto_add_unmatched is False
    assert config.radarr.refresh_debounce_seconds == 15
    assert config.radarr.auto_add_quality_profile_id is None
    assert config.radarr.auto_add_search_on_add is False
    assert config.radarr.auto_add_monitored is True
    assert config.sonarr.enabled is False
    assert config.sonarr.sync_enabled is False
    assert config.sonarr.url == ""
    assert config.sonarr.api_key == ""
    assert config.radarr.mapping.quality_map[0].target_id == 7
    assert config.cleanup.sonarr_action_on_missing == "unmonitor"
    assert config.cleanup.missing_grace_seconds == 3600
    assert config.runtime.arr_root_poll_interval_minutes == 1
    assert config.analysis.use_nfo is False
    assert config.analysis.use_media_probe is False
    assert config.analysis.media_probe_bin == "ffprobe"


def test_only_radarr_url_and_api_key_env_overrides_are_applied(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG_CONTENT, encoding="utf-8")

    monkeypatch.setenv("LIBRARIARR_RADARR_URL", "http://radarr.local:7878")
    monkeypatch.setenv("LIBRARIARR_RADARR_API_KEY", "env-key")
    monkeypatch.setenv("LIBRARIARR_SONARR_URL", "http://sonarr.local:8989")
    monkeypatch.setenv("LIBRARIARR_SONARR_API_KEY", "sonarr-env-key")
    monkeypatch.setenv("LIBRARIARR_SHADOW_ROOT", "/data/custom_shadow")
    monkeypatch.setenv("LIBRARIARR_NESTED_ROOTS", "/a,/b")
    monkeypatch.setenv("LIBRARIARR_USE_NFO_ANALYSIS", "true")
    monkeypatch.setenv("LIBRARIARR_USE_MEDIA_PROBE", "true")
    monkeypatch.setenv("LIBRARIARR_MEDIA_PROBE_BIN", "customprobe")

    config = load_config(config_path)

    assert config.radarr.url == "http://radarr.local:7878"
    assert config.radarr.api_key == "env-key"
    assert config.sonarr.url == "http://sonarr.local:8989"
    assert config.sonarr.api_key == "sonarr-env-key"
    assert len(config.paths.series_root_mappings) == 1
    assert config.analysis.use_nfo is False
    assert config.analysis.use_media_probe is False
    assert config.analysis.media_probe_bin == "ffprobe"


def test_load_config_reads_multiple_series_root_mappings(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            "    - nested_root: /data/movies/age_06\n"
            "      shadow_root: /data/radarr_library/age_06\n"
            "    - nested_root: /data/movies/age_12\n"
            "      shadow_root: /data/radarr_library/age_12\n"
            "  movie_root_mappings:\n"
            "    - managed_root: /data/movies/age_06\n"
            "      library_root: /data/radarr_library/age_06\n"
            "    - managed_root: /data/movies/age_12\n"
            "      library_root: /data/radarr_library/age_12\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("LIBRARIARR_NESTED_ROOTS", raising=False)

    config = load_config(config_path)

    assert len(config.paths.series_root_mappings) == 2
    assert config.paths.series_root_mappings[0].nested_root == "/data/movies/age_06"
    assert config.paths.series_root_mappings[0].shadow_root == "/data/radarr_library/age_06"


def test_load_config_reads_paths_exclude_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            "    - nested_root: /data/movies/age_12\n"
            "      shadow_root: /data/radarr_library/age_12\n"
            "  movie_root_mappings:\n"
            "    - managed_root: /data/movies/age_12\n"
            "      library_root: /data/radarr_library/age_12\n"
            "  exclude_paths:\n"
            "    - .deletedByTMM/\n"
            "    - '.librariarr/**'\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.paths.exclude_paths == [".deletedByTMM/", ".librariarr/**"]


def test_load_config_rejects_missing_series_root_mappings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  nested_roots:\n"
            "    - /data/movies/other\n"
            "radarr:\n"
            "  enabled: false\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "sonarr:\n"
            "  enabled: true\n"
            "  url: http://sonarr:8989\n"
            "  api_key: sonarr-key\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="paths.series_root_mappings is required"):
        load_config(config_path)


def test_load_config_reads_series_root_mappings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            "    - nested_root: /data/series/age_12\n"
            "      shadow_root: /data/sonarr_library/age_12\n"
            "sonarr:\n"
            "  enabled: true\n"
            "  url: http://sonarr:8989\n"
            "  api_key: sonarr-key\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert len(config.paths.series_root_mappings) == 1
    assert config.paths.series_root_mappings[0].nested_root == "/data/series/age_12"


def test_load_config_allows_disabling_maintenance_interval(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            "    - nested_root: /data/movies/one\n"
            "      shadow_root: /data/radarr_library/one\n"
            "  movie_root_mappings:\n"
            "    - managed_root: /data/movies/one\n"
            "      library_root: /data/radarr_library/one\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
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


def test_load_config_reads_arr_root_poll_interval(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            "    - nested_root: /data/movies/one\n"
            "      shadow_root: /data/radarr_library/one\n"
            "  movie_root_mappings:\n"
            "    - managed_root: /data/movies/one\n"
            "      library_root: /data/radarr_library/one\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "cleanup: {}\n"
            "runtime:\n"
            "  arr_root_poll_interval_minutes: 3\n"
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.runtime.arr_root_poll_interval_minutes == 3


def test_load_config_normalizes_dotless_scan_video_extensions(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            "    - nested_root: /data/movies/one\n"
            "      shadow_root: /data/radarr_library/one\n"
            "  movie_root_mappings:\n"
            "    - managed_root: /data/movies/one\n"
            "      library_root: /data/radarr_library/one\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "cleanup: {}\n"
            "runtime:\n"
            "  scan_video_extensions: [mkv, .mp4, avi]\n"
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.runtime.scan_video_extensions == [".mkv", ".mp4", ".avi"]


def test_load_config_uses_default_scan_video_extensions_when_not_set(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            "    - nested_root: /data/movies/one\n"
            "      shadow_root: /data/radarr_library/one\n"
            "  movie_root_mappings:\n"
            "    - managed_root: /data/movies/one\n"
            "      library_root: /data/radarr_library/one\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.runtime.scan_video_extensions == DEFAULT_SCAN_VIDEO_EXTENSIONS


def test_load_config_rejects_non_list_scan_video_extensions(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            "    - nested_root: /data/movies/one\n"
            "      shadow_root: /data/radarr_library/one\n"
            "  movie_root_mappings:\n"
            "    - managed_root: /data/movies/one\n"
            "      library_root: /data/radarr_library/one\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "cleanup: {}\n"
            "runtime:\n"
            "  scan_video_extensions: .mkv\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="runtime.scan_video_extensions must be a list"):
        load_config(config_path)


def test_load_config_reads_ingest_section(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            "    - nested_root: /data/movies/one\n"
            "      shadow_root: /data/radarr_library/one\n"
            "  movie_root_mappings:\n"
            "    - managed_root: /data/movies/one\n"
            "      library_root: /data/radarr_library/one\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "cleanup: {}\n"
            "runtime: {}\n"
            "ingest:\n"
            "  enabled: true\n"
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.ingest.enabled is True
    assert config.ingest.collision_strategy == "qualify"


def test_load_config_rejects_invalid_ingest_collision_strategy(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            "    - nested_root: /data/movies/one\n"
            "      shadow_root: /data/radarr_library/one\n"
            "  movie_root_mappings:\n"
            "    - managed_root: /data/movies/one\n"
            "      library_root: /data/radarr_library/one\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "cleanup: {}\n"
            "runtime: {}\n"
            "ingest:\n"
            "  collision_strategy: invalid\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="ingest.collision_strategy must be one of"):
        load_config(config_path)


def test_load_config_reads_radarr_auto_add_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            "    - nested_root: /data/movies/one\n"
            "      shadow_root: /data/radarr_library/one\n"
            "  movie_root_mappings:\n"
            "    - managed_root: /data/movies/one\n"
            "      library_root: /data/radarr_library/one\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "  auto_add_unmatched: true\n"
            "  refresh_debounce_seconds: 5\n"
            "  auto_add_quality_profile_id: 7\n"
            "  auto_add_search_on_add: true\n"
            "  auto_add_monitored: false\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.radarr.auto_add_unmatched is True
    assert config.radarr.refresh_debounce_seconds == 5
    assert config.radarr.auto_add_quality_profile_id == 7
    assert config.radarr.auto_add_search_on_add is True
    assert config.radarr.auto_add_monitored is False


def test_load_config_disables_radarr_when_enabled_false(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            "    - nested_root: /data/movies/one\n"
            "      shadow_root: /data/radarr_library/one\n"
            "radarr:\n"
            "  enabled: false\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "  sync_enabled: true\n"
            "  auto_add_unmatched: true\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.radarr.enabled is False
    assert config.radarr.sync_enabled is False
    assert config.radarr.auto_add_unmatched is False


def test_load_config_reads_custom_format_map(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            "    - nested_root: /data/movies/one\n"
            "      shadow_root: /data/radarr_library/one\n"
            "  movie_root_mappings:\n"
            "    - managed_root: /data/movies/one\n"
            "      library_root: /data/radarr_library/one\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "  mapping:\n"
            "    custom_format_map:\n"
            "      - match: [german, x265]\n"
            "        format_id: 42\n"
            "        name: German HEVC\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert len(config.radarr.mapping.custom_format_map) == 1
    assert config.radarr.mapping.custom_format_map[0].match == ["german", "x265"]
    assert config.radarr.mapping.custom_format_map[0].format_id == 42


def test_load_config_reads_cleanup_grace(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            "    - nested_root: /data/movies/one\n"
            "      shadow_root: /data/radarr_library/one\n"
            "  movie_root_mappings:\n"
            "    - managed_root: /data/movies/one\n"
            "      library_root: /data/radarr_library/one\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "cleanup:\n"
            "  missing_grace_seconds: 7200\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.cleanup.missing_grace_seconds == 7200


def test_load_config_reads_sonarr_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            "    - nested_root: /data/series/one\n"
            "      shadow_root: /data/sonarr_library/one\n"
            "  movie_root_mappings:\n"
            "    - managed_root: /data/series/one\n"
            "      library_root: /data/sonarr_library/one\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "sonarr:\n"
            "  enabled: true\n"
            "  url: http://sonarr:8989\n"
            "  api_key: sonarr-key\n"
            "  sync_enabled: true\n"
            "  auto_add_unmatched: true\n"
            "  auto_add_quality_profile_id: 6\n"
            "  auto_add_language_profile_id: 1\n"
            "  auto_add_search_on_add: true\n"
            "  auto_add_monitored: false\n"
            "  auto_add_season_folder: false\n"
            "  refresh_debounce_seconds: 9\n"
            "cleanup:\n"
            "  sonarr_action_on_missing: delete\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.sonarr.enabled is True
    assert config.sonarr.url == "http://sonarr:8989"
    assert config.sonarr.api_key == "sonarr-key"
    assert config.sonarr.sync_enabled is True
    assert config.sonarr.auto_add_unmatched is True
    assert config.sonarr.auto_add_quality_profile_id == 6
    assert config.sonarr.auto_add_language_profile_id == 1
    assert config.sonarr.auto_add_search_on_add is True
    assert config.sonarr.auto_add_monitored is False
    assert config.sonarr.auto_add_season_folder is False
    assert config.sonarr.refresh_debounce_seconds == 9
    assert config.cleanup.sonarr_action_on_missing == "delete"


def test_load_config_rejects_invalid_sonarr_cleanup_action(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            "    - nested_root: /data/movies/one\n"
            "      shadow_root: /data/radarr_library/one\n"
            "  movie_root_mappings:\n"
            "    - managed_root: /data/movies/one\n"
            "      library_root: /data/radarr_library/one\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "cleanup:\n"
            "  sonarr_action_on_missing: pause\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="cleanup.sonarr_action_on_missing"):
        load_config(config_path)


def test_load_config_reads_namespaced_radarr_mapping(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            "    - nested_root: /data/movies/one\n"
            "      shadow_root: /data/radarr_library/one\n"
            "  movie_root_mappings:\n"
            "    - managed_root: /data/movies/one\n"
            "      library_root: /data/radarr_library/one\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "  mapping:\n"
            "    quality_map:\n"
            "      - match: [1080p]\n"
            "        target_id: 9\n"
            "    custom_format_map:\n"
            "      - match: [german]\n"
            "        format_id: 42\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.radarr.mapping.quality_map[0].target_id == 9
    assert config.radarr.mapping.custom_format_map[0].format_id == 42
    assert config.effective_radarr_quality_map()[0].target_id == 9
    assert config.effective_radarr_custom_format_map()[0].format_id == 42
