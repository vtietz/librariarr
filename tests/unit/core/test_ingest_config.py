from pathlib import Path

import pytest

from librariarr.config import load_config


def test_load_config_reads_ingest_replacement_delete_mode(tmp_path: Path) -> None:
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
            "  replacement_delete_mode: hard\n"
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.ingest.enabled is True
    assert config.ingest.replacement_delete_mode == "hard"


def test_load_config_defaults_ingest_replacement_delete_mode_to_soft(tmp_path: Path) -> None:
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

    assert config.ingest.replacement_delete_mode == "soft"


def test_load_config_rejects_invalid_ingest_replacement_delete_mode(tmp_path: Path) -> None:
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
            "  replacement_delete_mode: keep\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="ingest.replacement_delete_mode must be 'soft' or 'hard'"):
        load_config(config_path)
