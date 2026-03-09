from pathlib import Path

from librariarr.sync.cleanup import ShadowCleanupManager


class FakeRadarr:
    def __init__(self) -> None:
        self.unmonitored: list[int] = []
        self.deleted: list[int] = []
        self.refreshed: list[int] = []

    def unmonitor_movie(self, movie: dict) -> None:
        self.unmonitored.append(int(movie["id"]))

    def delete_movie(self, movie_id: int, delete_files: bool = False) -> None:
        del delete_files
        self.deleted.append(movie_id)

    def refresh_movie(self, movie_id: int) -> None:
        self.refreshed.append(movie_id)


def test_cleanup_manager_removes_orphan_and_unmonitors_movie(tmp_path: Path) -> None:
    shadow_root = tmp_path / "radarr_library"
    nested_root = tmp_path / "nested"
    shadow_root.mkdir(parents=True)
    nested_root.mkdir(parents=True)

    missing_target = nested_root / "Tears of Steel (2012)"
    orphan_link = shadow_root / "Tears of Steel (2012)"
    orphan_link.symlink_to(missing_target, target_is_directory=True)

    radarr = FakeRadarr()
    movies = {"Tears of Steel (2012)": {"id": 77}}

    manager = ShadowCleanupManager(
        shadow_roots=[shadow_root],
        sync_enabled=True,
        unmonitor_on_delete=True,
        delete_from_radarr_on_missing=False,
        get_radarr_client=lambda: radarr,
        resolve_movie_for_link_name=lambda link_name, movie_map: movie_map.get(
            link_name.split("--", 1)[0]
        ),
    )

    removed = manager.cleanup_orphans(
        existing_folders=set(),
        movies_by_ref=movies,
        expected_links=set(),
    )

    assert removed == 1
    assert not orphan_link.exists()
    assert radarr.unmonitored == [77]
    assert radarr.deleted == []
    assert radarr.refreshed == [77]


def test_cleanup_manager_removes_orphan_and_deletes_movie_when_configured(tmp_path: Path) -> None:
    shadow_root = tmp_path / "radarr_library"
    nested_root = tmp_path / "nested"
    shadow_root.mkdir(parents=True)
    nested_root.mkdir(parents=True)

    missing_target = nested_root / "Tears of Steel (2012)"
    orphan_link = shadow_root / "Tears of Steel (2012)"
    orphan_link.symlink_to(missing_target, target_is_directory=True)

    radarr = FakeRadarr()
    movies = {"Tears of Steel (2012)": {"id": 88}}

    manager = ShadowCleanupManager(
        shadow_roots=[shadow_root],
        sync_enabled=True,
        unmonitor_on_delete=True,
        delete_from_radarr_on_missing=True,
        get_radarr_client=lambda: radarr,
        resolve_movie_for_link_name=lambda link_name, movie_map: movie_map.get(
            link_name.split("--", 1)[0]
        ),
    )

    removed = manager.cleanup_orphans(
        existing_folders=set(),
        movies_by_ref=movies,
        expected_links=set(),
    )

    assert removed == 1
    assert radarr.deleted == [88]
    assert radarr.unmonitored == []
    assert radarr.refreshed == []
