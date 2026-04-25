from pathlib import Path

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    MovieRootMapping,
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
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"
    managed_root.mkdir(parents=True)

    config = AppConfig(
        paths=PathsConfig(
            series_root_mappings=[
                RootMapping(
                    nested_root=str(managed_root),
                    shadow_root=str(library_root),
                )
            ],
            movie_root_mappings=[
                MovieRootMapping(managed_root=str(managed_root), library_root=str(library_root))
            ],
        ),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            sync_enabled=False,
            mapping=RadarrMappingConfig(
                quality_map=[QualityRule(match=["1080p", "x265"], target_id=7)]
            ),
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=0),
    )

    service = LibrariArrService(config)

    assert service._maintenance_interval is None


def test_reconcile_does_not_ingest_shadow_folder_when_projection_only(tmp_path: Path) -> None:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"
    incoming = library_root / "Incoming Movie (2024)"
    incoming.mkdir(parents=True)
    (incoming / "Incoming.Movie.2024.1080p.mkv").write_text("x", encoding="utf-8")

    config = make_config(managed_root, library_root, sync_enabled=False, radarr_enabled=False)
    service = LibrariArrService(config)

    service.reconcile()

    assert incoming.exists()
    assert incoming.is_dir()
    assert not incoming.is_symlink()
    assert not (managed_root / "Incoming Movie (2024)").exists()


def test_service_no_longer_fails_on_ambiguous_ingest_root_mappings(tmp_path: Path) -> None:
    library_root = tmp_path / "library"
    managed_a = tmp_path / "managed_a"
    managed_b = tmp_path / "managed_b"

    config = AppConfig(
        paths=PathsConfig(
            series_root_mappings=[
                RootMapping(nested_root=str(managed_a), shadow_root=str(library_root)),
                RootMapping(nested_root=str(managed_b), shadow_root=str(library_root)),
            ],
            movie_root_mappings=[
                MovieRootMapping(managed_root=str(managed_a), library_root=str(library_root)),
                MovieRootMapping(managed_root=str(managed_b), library_root=str(library_root)),
            ],
        ),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            sync_enabled=False,
            mapping=RadarrMappingConfig(
                quality_map=[QualityRule(match=["1080p", "x265"], target_id=7)]
            ),
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )

    service = LibrariArrService(config)
    assert service is not None
