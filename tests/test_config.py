from pathlib import Path

from librariarr.config import load_config

CONFIG_CONTENT = """
paths:
  nested_roots:
    - /data/movies/one
radarr:
  url: http://radarr:7878
  api_key: test-key
  shadow_root: /data/radarr_library
quality_map:
  - match: [\"1080p\", \"x265\"]
    target_id: 7
cleanup:
  remove_orphaned_links: true
  unmonitor_on_delete: true
runtime:
  debounce_seconds: 8
  maintenance_interval_minutes: 1440
""".strip()


def test_load_config_reads_yaml_values(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG_CONTENT, encoding="utf-8")

    monkeypatch.delenv("LIBRARIARR_RADARR_URL", raising=False)
    monkeypatch.delenv("LIBRARIARR_RADARR_API_KEY", raising=False)
    monkeypatch.delenv("LIBRARIARR_SHADOW_ROOT", raising=False)
    monkeypatch.delenv("LIBRARIARR_NESTED_ROOTS", raising=False)

    config = load_config(config_path)

    assert config.paths.nested_roots == ["/data/movies/one"]
    assert config.radarr.url == "http://radarr:7878"
    assert config.radarr.api_key == "test-key"
    assert config.radarr.shadow_root == "/data/radarr_library"
    assert config.quality_map[0].target_id == 7


def test_env_overrides_are_applied(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG_CONTENT, encoding="utf-8")

    monkeypatch.setenv("LIBRARIARR_RADARR_URL", "http://radarr.local:7878")
    monkeypatch.setenv("LIBRARIARR_RADARR_API_KEY", "env-key")
    monkeypatch.setenv("LIBRARIARR_SHADOW_ROOT", "/data/custom_shadow")
    monkeypatch.setenv("LIBRARIARR_NESTED_ROOTS", "/a,/b")

    config = load_config(config_path)

    assert config.radarr.url == "http://radarr.local:7878"
    assert config.radarr.api_key == "env-key"
    assert config.radarr.shadow_root == "/data/custom_shadow"
    assert config.paths.nested_roots == ["/a", "/b"]
