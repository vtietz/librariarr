from pathlib import Path

from librariarr.config import load_config


def test_load_config_uses_default_arr_request_settings(tmp_path: Path) -> None:
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

    assert config.radarr.request_timeout_seconds == 30
    assert config.radarr.request_retry_attempts == 2
    assert config.radarr.request_retry_backoff_seconds == 0.5
    assert config.sonarr.request_timeout_seconds == 30
    assert config.sonarr.request_retry_attempts == 2
    assert config.sonarr.request_retry_backoff_seconds == 0.5


def test_load_config_reads_radarr_request_settings(tmp_path: Path) -> None:
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
            "  request_timeout_seconds: 45\n"
            "  request_retry_attempts: 4\n"
            "  request_retry_backoff_seconds: 1.25\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.radarr.request_timeout_seconds == 45
    assert config.radarr.request_retry_attempts == 4
    assert config.radarr.request_retry_backoff_seconds == 1.25


def test_load_config_reads_sonarr_request_settings(tmp_path: Path) -> None:
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
            "sonarr:\n"
            "  enabled: true\n"
            "  url: http://sonarr:8989\n"
            "  api_key: sonarr-key\n"
            "  request_timeout_seconds: 50\n"
            "  request_retry_attempts: 5\n"
            "  request_retry_backoff_seconds: 1.5\n"
            "cleanup: {}\n"
            "runtime: {}\n"
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.sonarr.request_timeout_seconds == 50
    assert config.sonarr.request_retry_attempts == 5
    assert config.sonarr.request_retry_backoff_seconds == 1.5
