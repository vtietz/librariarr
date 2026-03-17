from pathlib import Path

import pytest

from librariarr.config import load_config


def test_load_config_reads_radarr_path_update_match_policy(tmp_path: Path) -> None:
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
            "  path_update_match_policy: external_ids_only\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.radarr.path_update_match_policy == "external_ids_only"


def test_load_config_rejects_invalid_radarr_path_update_match_policy(tmp_path: Path) -> None:
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
            "  path_update_match_policy: strictest\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="radarr.path_update_match_policy"):
        load_config(config_path)
