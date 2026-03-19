from pathlib import Path

import pytest

from librariarr.config import load_config


def test_load_config_rejects_legacy_top_level_quality_map(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            "    - nested_root: /data/movies/one\n"
            "      shadow_root: /data/radarr_library/one\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "  mapping:\n"
            "    quality_map:\n"
            "      - match: [2160p]\n"
            "        target_id: 19\n"
            "quality_map:\n"
            "  - match: [1080p]\n"
            "    target_id: 9\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Top-level quality_map/custom_format_map"):
        load_config(config_path)


def test_load_config_reads_namespaced_sonarr_mapping(tmp_path: Path) -> None:
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
            "  mapping:\n"
            "    quality_profile_map:\n"
            "      - match: [1080p]\n"
            "        profile_id: 8\n"
            "    language_profile_map:\n"
            "      - match: [lang-de]\n"
            "        profile_id: 4\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.sonarr.mapping.quality_profile_map[0].profile_id == 8
    assert config.sonarr.mapping.language_profile_map[0].profile_id == 4


def test_load_config_rejects_legacy_radarr_quality_map_id_key(tmp_path: Path) -> None:
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
            "        id: 9\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="quality_map entries must define target_id"):
        load_config(config_path)


def test_load_config_rejects_legacy_radarr_custom_format_format_key(tmp_path: Path) -> None:
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
            "      - match: [german]\n"
            "        format: 42\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="custom_format_map entries must define format_id"):
        load_config(config_path)


def test_load_config_rejects_legacy_sonarr_profile_id_alias(tmp_path: Path) -> None:
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
            "  mapping:\n"
            "    quality_profile_map:\n"
            "      - match: [1080p]\n"
            "        id: 8\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="quality_profile_map entries must define profile_id"):
        load_config(config_path)
