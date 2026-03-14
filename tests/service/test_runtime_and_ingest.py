from pathlib import Path

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    IngestConfig,
    PathsConfig,
    QualityRule,
    RadarrConfig,
    RadarrMappingConfig,
    RootMapping,
    RuntimeConfig,
)
from librariarr.service import LibrariArrService
from tests.service.helpers import make_config


def test_service_disables_periodic_maintenance_when_configured(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = AppConfig(
        paths=PathsConfig(
            root_mappings=[RootMapping(nested_root=str(nested_root), shadow_root=str(shadow_root))]
        ),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            sync_enabled=False,
            mapping=RadarrMappingConfig(
                quality_map=[QualityRule(match=["1080p", "x265"], target_id=7, name="Bluray-1080p")]
            ),
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=0),
    )

    service = LibrariArrService(config)

    assert service._maintenance_interval is None


def test_ingest_moves_real_shadow_folder_to_nested_and_replaces_symlink(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    incoming = shadow_root / "Incoming Movie (2024)"
    incoming.mkdir(parents=True)
    (incoming / "Incoming.Movie.2024.1080p.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=False)
    config.ingest = IngestConfig(enabled=True, min_age_seconds=0)
    service = LibrariArrService(config)

    service.reconcile()

    destination = nested_root / "Incoming Movie (2024)"
    shadow_link = shadow_root / "Incoming Movie (2024)"
    assert destination.exists()
    assert shadow_link.is_symlink()
    assert shadow_link.resolve(strict=False) == destination

    service.reconcile()
    assert shadow_link.is_symlink()
    assert shadow_link.resolve(strict=False) == destination


def test_ingest_collision_skip_policy_leaves_source_untouched(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"

    existing = nested_root / "Collision Movie (2024)"
    existing.mkdir(parents=True)
    (existing / "Collision.Movie.2024.1080p.mkv").write_text("x", encoding="utf-8")

    incoming = shadow_root / "Collision Movie (2024)"
    incoming.mkdir(parents=True)
    (incoming / "Collision.Movie.2024.2160p.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=False)
    config.ingest = IngestConfig(enabled=True, min_age_seconds=0, collision_policy="skip")
    service = LibrariArrService(config)

    service.reconcile()

    assert incoming.exists()
    assert incoming.is_dir()
    assert not incoming.is_symlink()


def test_ingest_collision_qualify_policy_uses_suffix(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"

    existing = nested_root / "Collision Movie (2024)"
    existing.mkdir(parents=True)
    (existing / "existing.mkv").write_text("x", encoding="utf-8")

    incoming = shadow_root / "Collision Movie (2024)"
    incoming.mkdir(parents=True)
    (incoming / "incoming.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=False)
    config.ingest = IngestConfig(enabled=True, min_age_seconds=0, collision_policy="qualify")
    service = LibrariArrService(config)

    service.reconcile()

    qualified_destination = nested_root / "Collision Movie (2024) [ingest-2]"
    shadow_link = shadow_root / "Collision Movie (2024)"
    assert qualified_destination.exists()
    assert shadow_link.is_symlink()
    assert shadow_link.resolve(strict=False) == qualified_destination


def test_ingest_requires_one_to_one_shadow_root_mappings(tmp_path: Path) -> None:
    shadow_root = tmp_path / "radarr_library"
    nested_a = tmp_path / "nested_a"
    nested_b = tmp_path / "nested_b"

    config = AppConfig(
        paths=PathsConfig(
            root_mappings=[
                RootMapping(nested_root=str(nested_a), shadow_root=str(shadow_root)),
                RootMapping(nested_root=str(nested_b), shadow_root=str(shadow_root)),
            ]
        ),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            sync_enabled=False,
            mapping=RadarrMappingConfig(
                quality_map=[QualityRule(match=["1080p", "x265"], target_id=7, name="Bluray-1080p")]
            ),
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
        ingest=IngestConfig(enabled=True, min_age_seconds=0),
    )

    try:
        LibrariArrService(config)
    except ValueError as exc:
        assert "Ingest requires a 1:1 mapping" in str(exc)
    else:
        raise AssertionError("Expected ValueError for ambiguous ingest root mappings")
