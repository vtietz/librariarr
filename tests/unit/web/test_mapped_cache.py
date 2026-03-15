from pathlib import Path

from librariarr.config import load_config
from librariarr.web.mapped_cache import MappedDirectoriesCache, warmup_mapped_directories_cache


def _write_config(path: Path, nested_root: Path, shadow_root: Path) -> None:
    path.write_text(
        (
            "paths:\n"
            "  root_mappings:\n"
            f"    - nested_root: {nested_root}\n"
            f"      shadow_root: {shadow_root}\n"
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


def test_mapped_directories_cache_builds_snapshot(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    movie_dir = nested_root / "Movie One"
    movie_dir.mkdir()
    shadow_link = shadow_root / "Movie One"
    shadow_link.symlink_to(movie_dir, target_is_directory=True)

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)
    config = load_config(config_path)

    cache = MappedDirectoriesCache()
    started = cache.request_refresh(config, force=True)
    assert started is True
    assert cache.wait_for_build(timeout=2.0) is True

    snapshot = cache.snapshot()
    assert snapshot["ready"] is True
    assert snapshot["building"] is False
    assert snapshot["last_error"] is None
    assert snapshot["version"] >= 1
    assert len(snapshot["items"]) == 1
    assert snapshot["items"][0]["virtual_path"] == str(shadow_link)
    assert snapshot["items"][0]["real_path"] == str(movie_dir)


def test_mapped_directories_cache_skips_recent_non_forced_refresh(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir()
    shadow_root.mkdir()

    (nested_root / "Movie One").mkdir()
    (shadow_root / "Movie One").symlink_to(nested_root / "Movie One", target_is_directory=True)

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, nested_root, shadow_root)
    config = load_config(config_path)

    cache = MappedDirectoriesCache()
    assert cache.request_refresh(config, force=True) is True
    assert cache.wait_for_build(timeout=2.0) is True
    assert cache.request_refresh(config, force=False) is False


def test_warmup_mapped_directories_cache_handles_missing_config() -> None:
    warmup_mapped_directories_cache(Path("/definitely/missing/config.yaml"))
