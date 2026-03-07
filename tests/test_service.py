from pathlib import Path

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    PathsConfig,
    QualityRule,
    RadarrConfig,
    RuntimeConfig,
)
from librariarr.service import LibrariArrService


class FakeRadarr:
    def __init__(self, movies: list[dict] | None = None) -> None:
        self.movies = movies or []
        self.updated_paths: list[tuple[int, str]] = []
        self.updated_qualities: list[tuple[int, int]] = []
        self.refreshed: list[int] = []
        self.unmonitored: list[int] = []
        self.get_movies_calls = 0

    def get_movies(self) -> list[dict]:
        self.get_movies_calls += 1
        return self.movies

    def update_movie_path(self, movie: dict, new_path: str) -> None:
        self.updated_paths.append((int(movie["id"]), new_path))

    def try_update_moviefile_quality(self, movie: dict, quality_id: int) -> None:
        self.updated_qualities.append((int(movie["id"]), quality_id))

    def refresh_movie(self, movie_id: int) -> None:
        self.refreshed.append(movie_id)

    def unmonitor_movie(self, movie: dict) -> None:
        self.unmonitored.append(int(movie["id"]))


def make_config(nested_root: Path, shadow_root: Path, sync_enabled: bool = True) -> AppConfig:
    return AppConfig(
        paths=PathsConfig(nested_roots=[str(nested_root)]),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            shadow_root=str(shadow_root),
            sync_enabled=sync_enabled,
        ),
        quality_map=[QualityRule(match=["1080p", "x265"], target_id=7, name="Bluray-1080p")],
        cleanup=CleanupConfig(remove_orphaned_links=True, unmonitor_on_delete=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )


def test_reconcile_creates_symlink_for_movie_folder(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie = nested_root / "Dr. No (1962)"
    movie.mkdir(parents=True)
    (movie / "Dr.No.1962.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=False)
    service = LibrariArrService(config)

    service.reconcile()

    link = shadow_root / "Dr. No (1962)"
    assert link.is_symlink()
    assert link.resolve(strict=False) == movie


def test_reconcile_removes_orphaned_symlink(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)
    shadow_root.mkdir(parents=True)

    missing_target = nested_root / "Missing Movie (2000)"
    orphan = shadow_root / "Missing Movie (2000)"
    orphan.symlink_to(missing_target, target_is_directory=True)

    config = make_config(nested_root, shadow_root, sync_enabled=False)
    service = LibrariArrService(config)

    service.reconcile()

    assert not orphan.exists()


def test_reconcile_syncs_radarr_when_enabled(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Dr. No (1962)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Dr.No.1962.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    service = LibrariArrService(config)

    fake = FakeRadarr(
        movies=[
            {
                "id": 1,
                "title": "Dr. No",
                "year": 1962,
                "path": "/old/path",
                "movieFile": {"id": 11},
                "monitored": True,
            }
        ]
    )
    service.radarr = fake

    service.reconcile()

    assert fake.get_movies_calls == 1
    assert fake.updated_paths and fake.updated_paths[0][0] == 1
    assert fake.updated_qualities == [(1, 7)]
    assert fake.refreshed == [1]


def test_reconcile_skips_radarr_when_sync_disabled(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Dr. No (1962)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Dr.No.1962.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=False)
    service = LibrariArrService(config)

    fake = FakeRadarr(
        movies=[
            {
                "id": 1,
                "title": "Dr. No",
                "year": 1962,
                "path": "/old/path",
                "movieFile": {"id": 11},
                "monitored": True,
            }
        ]
    )
    service.radarr = fake

    service.reconcile()

    assert fake.get_movies_calls == 0
    assert fake.updated_paths == []
    assert fake.updated_qualities == []
    assert fake.refreshed == []
