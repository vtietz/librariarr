from pathlib import Path

from librariarr.config import load_config
from librariarr.web.jobs import JobManager
from librariarr.web.mapped_cache import MappedDirectoriesCache, warmup_mapped_directories_cache
from librariarr.web.state_store import PersistentStateStore


def _write_config(path: Path, nested_root: Path, shadow_root: Path) -> None:
    path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            f"    - nested_root: {nested_root}\n"
            f"      shadow_root: {shadow_root}\n"
            "  movie_root_mappings:\n"
            f"    - managed_root: {nested_root}\n"
            f"      library_root: {shadow_root}\n"
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


def test_mapped_directories_cache_restores_persisted_snapshot(tmp_path: Path) -> None:
    state_store = PersistentStateStore(tmp_path / "state.json")
    state_store.save_cache_snapshot(
        "mapped_directories",
        {
            "items": [{"virtual_path": "/shadow/Movie One", "real_path": "/nested/Movie One"}],
            "shadow_roots": ["/shadow"],
            "updated_at_ms": 123,
            "last_error": None,
            "version": 4,
            "last_build_duration_ms": 15,
        },
    )

    cache = MappedDirectoriesCache()
    cache.attach_state(state_store=state_store, task_manager=JobManager(state_store=state_store))

    snapshot = cache.snapshot()

    assert snapshot["ready"] is True
    assert snapshot["version"] == 4
    assert snapshot["items"][0]["virtual_path"] == "/shadow/Movie One"
