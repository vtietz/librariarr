import os
import shutil
from pathlib import Path

import pytest

from librariarr.config import AppConfig, CleanupConfig, PathsConfig, RadarrConfig, RuntimeConfig
from librariarr.service import LibrariArrService


def _make_roots(tmp_path: Path, case_name: str) -> tuple[Path, Path]:
    persist_root = os.getenv("LIBRARIARR_E2E_PERSIST_ROOT")
    if not persist_root:
        return tmp_path / "movies", tmp_path / "radarr_library"

    case_root = Path(persist_root) / case_name
    if case_root.exists():
        shutil.rmtree(case_root)
    movies_root = case_root / "movies"
    shadow_root = case_root / "radarr_library"
    movies_root.mkdir(parents=True, exist_ok=True)
    shadow_root.mkdir(parents=True, exist_ok=True)
    return movies_root, shadow_root


def _relativize_links_for_host_view(shadow_root: Path) -> None:
    persist_root = os.getenv("LIBRARIARR_E2E_PERSIST_ROOT")
    if not persist_root:
        return

    for link in shadow_root.iterdir():
        if not link.is_symlink():
            continue
        target = link.resolve(strict=False)
        relative_target = os.path.relpath(str(target), start=str(link.parent))
        link.unlink(missing_ok=True)
        link.symlink_to(relative_target, target_is_directory=True)


@pytest.mark.fs_e2e
def test_e2e_reconcile_creates_expected_symlink_layout(tmp_path: Path) -> None:
    nested_root, shadow_root = _make_roots(tmp_path, "creates_symlink_layout")

    movie_a = nested_root / "age_12" / "Blender" / "Big Buck Bunny (2008)"
    movie_b = nested_root / "age_16" / "OpenFilms" / "Sintel (2010)"
    movie_a.mkdir(parents=True)
    movie_b.mkdir(parents=True)

    # Small stub files are enough to trigger movie discovery.
    (movie_a / "Big.Buck.Bunny.2008.1080p.x265.mkv").write_text("stub", encoding="utf-8")
    (movie_b / "Sintel.2010.2160p.REMUX.mkv").write_text("stub", encoding="utf-8")

    config = AppConfig(
        paths=PathsConfig(nested_roots=[str(nested_root)]),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            shadow_root=str(shadow_root),
            sync_enabled=False,
        ),
        quality_map=[],
        cleanup=CleanupConfig(remove_orphaned_links=True, unmonitor_on_delete=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )

    service = LibrariArrService(config)
    service.reconcile()
    _relativize_links_for_host_view(shadow_root)

    link_a = shadow_root / "Big Buck Bunny (2008)"
    link_b = shadow_root / "Sintel (2010)"

    assert link_a.is_symlink()
    assert link_a.resolve(strict=False) == movie_a
    assert link_b.is_symlink()
    assert link_b.resolve(strict=False) == movie_b


@pytest.mark.fs_e2e
def test_e2e_reconcile_handles_collisions_and_orphans(tmp_path: Path) -> None:
    root_base, shadow_root = _make_roots(tmp_path, "collision_and_orphan_cleanup")
    root_one = root_base / "source_a"
    root_two = root_base / "source_b"

    movie_one = root_one / "age_12" / "Blender" / "Sintel (2010)"
    movie_two = root_two / "age_16" / "OpenFilms" / "Sintel (2010)"
    movie_one.mkdir(parents=True)
    movie_two.mkdir(parents=True)
    (movie_one / "Sintel.2010.1080p.x265.mkv").write_text("stub", encoding="utf-8")
    (movie_two / "Sintel.2010.1080p.x265.mkv").write_text("stub", encoding="utf-8")

    config = AppConfig(
        paths=PathsConfig(nested_roots=[str(root_one), str(root_two)]),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            shadow_root=str(shadow_root),
            sync_enabled=False,
        ),
        quality_map=[],
        cleanup=CleanupConfig(remove_orphaned_links=True, unmonitor_on_delete=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )

    service = LibrariArrService(config)
    service.reconcile()
    _relativize_links_for_host_view(shadow_root)

    plain_link = shadow_root / "Sintel (2010)"
    qualified_link = shadow_root / "Sintel (2010)--source_b-age_16-OpenFilms"
    assert plain_link.is_symlink()
    assert qualified_link.is_symlink()

    # Remove one source and reconcile to verify orphan cleanup end-to-end.
    for child in movie_two.iterdir():
        child.unlink()
    movie_two.rmdir()

    service.reconcile()
    _relativize_links_for_host_view(shadow_root)

    assert plain_link.is_symlink()
    assert not qualified_link.exists()
