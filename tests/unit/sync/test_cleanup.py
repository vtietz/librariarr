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
        on_missing_action="unmonitor",
        missing_grace_seconds=0,
        get_arr_client=lambda: radarr,
        resolve_item_for_link_name=lambda link_name, movie_map: movie_map.get(
            link_name.split("--", 1)[0]
        ),
        unmonitor_item=lambda client, item: client.unmonitor_movie(item),
        delete_item=lambda client, item_id: client.delete_movie(item_id, delete_files=False),
        refresh_item=lambda client, item_id: client.refresh_movie(item_id),
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
        on_missing_action="delete",
        missing_grace_seconds=0,
        get_arr_client=lambda: radarr,
        resolve_item_for_link_name=lambda link_name, movie_map: movie_map.get(
            link_name.split("--", 1)[0]
        ),
        unmonitor_item=lambda client, item: client.unmonitor_movie(item),
        delete_item=lambda client, item_id: client.delete_movie(item_id, delete_files=False),
        refresh_item=lambda client, item_id: client.refresh_movie(item_id),
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


def test_cleanup_manager_defers_missing_action_until_grace_expires(
    tmp_path: Path,
    monkeypatch,
) -> None:
    shadow_root = tmp_path / "radarr_library"
    nested_root = tmp_path / "nested"
    shadow_root.mkdir(parents=True)
    nested_root.mkdir(parents=True)

    missing_target = nested_root / "Tears of Steel (2012)"
    orphan_link = shadow_root / "Tears of Steel (2012)"
    orphan_link.symlink_to(missing_target, target_is_directory=True)

    radarr = FakeRadarr()
    movies = {"Tears of Steel (2012)": {"id": 99}}

    manager = ShadowCleanupManager(
        shadow_roots=[shadow_root],
        sync_enabled=True,
        on_missing_action="unmonitor",
        missing_grace_seconds=60,
        get_arr_client=lambda: radarr,
        resolve_item_for_link_name=lambda link_name, movie_map: movie_map.get(
            link_name.split("--", 1)[0]
        ),
        unmonitor_item=lambda client, item: client.unmonitor_movie(item),
        delete_item=lambda client, item_id: client.delete_movie(item_id, delete_files=False),
        refresh_item=lambda client, item_id: client.refresh_movie(item_id),
    )

    current_time = 1000.0

    def fake_time() -> float:
        return current_time

    monkeypatch.setattr("librariarr.sync.cleanup.time.time", fake_time)

    manager.cleanup_orphans(
        existing_folders=set(),
        movies_by_ref=movies,
        expected_links=set(),
    )
    assert radarr.unmonitored == []
    assert radarr.deleted == []

    current_time = 1059.0
    manager.cleanup_orphans(
        existing_folders=set(),
        movies_by_ref=movies,
        expected_links=set(),
    )
    assert radarr.unmonitored == []
    assert radarr.deleted == []

    current_time = 1061.0
    manager.cleanup_orphans(
        existing_folders=set(),
        movies_by_ref=movies,
        expected_links=set(),
    )
    assert radarr.unmonitored == [99]
    assert radarr.deleted == []
    assert radarr.refreshed == [99]


def test_cleanup_manager_clears_pending_missing_when_movie_rematches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    shadow_root = tmp_path / "radarr_library"
    nested_root = tmp_path / "nested"
    shadow_root.mkdir(parents=True)
    nested_root.mkdir(parents=True)

    missing_target = nested_root / "Tears of Steel (2012)"
    orphan_link = shadow_root / "Tears of Steel (2012)"
    orphan_link.symlink_to(missing_target, target_is_directory=True)

    radarr = FakeRadarr()
    movies = {"Tears of Steel (2012)": {"id": 101}}

    manager = ShadowCleanupManager(
        shadow_roots=[shadow_root],
        sync_enabled=True,
        on_missing_action="unmonitor",
        missing_grace_seconds=60,
        get_arr_client=lambda: radarr,
        resolve_item_for_link_name=lambda link_name, movie_map: movie_map.get(
            link_name.split("--", 1)[0]
        ),
        unmonitor_item=lambda client, item: client.unmonitor_movie(item),
        delete_item=lambda client, item_id: client.delete_movie(item_id, delete_files=False),
        refresh_item=lambda client, item_id: client.refresh_movie(item_id),
    )

    current_time = 2000.0

    def fake_time() -> float:
        return current_time

    monkeypatch.setattr("librariarr.sync.cleanup.time.time", fake_time)

    manager.cleanup_orphans(
        existing_folders=set(),
        movies_by_ref=movies,
        expected_links=set(),
    )

    current_time = 2100.0
    manager.cleanup_orphans(
        existing_folders=set(),
        movies_by_ref=movies,
        expected_links=set(),
        matched_movie_ids={101},
    )

    current_time = 2200.0
    manager.cleanup_orphans(
        existing_folders=set(),
        movies_by_ref=movies,
        expected_links=set(),
    )

    assert radarr.unmonitored == []
    assert radarr.deleted == []
    assert radarr.refreshed == []


def test_cleanup_manager_applies_missing_actions_in_incremental_target_cleanup(
    tmp_path: Path,
) -> None:
    shadow_root = tmp_path / "radarr_library"
    nested_root = tmp_path / "nested"
    shadow_root.mkdir(parents=True)
    nested_root.mkdir(parents=True)

    missing_target = nested_root / "Tears of Steel (2012)"
    orphan_link = shadow_root / "Tears of Steel (2012)"
    orphan_link.symlink_to(missing_target, target_is_directory=True)

    radarr = FakeRadarr()
    movies = {"Tears of Steel (2012)": {"id": 123}}

    manager = ShadowCleanupManager(
        shadow_roots=[shadow_root],
        sync_enabled=True,
        on_missing_action="unmonitor",
        missing_grace_seconds=0,
        get_arr_client=lambda: radarr,
        resolve_item_for_link_name=lambda link_name, movie_map: movie_map.get(
            link_name.split("--", 1)[0]
        ),
        unmonitor_item=lambda client, item: client.unmonitor_movie(item),
        delete_item=lambda client, item_id: client.delete_movie(item_id, delete_files=False),
        refresh_item=lambda client, item_id: client.refresh_movie(item_id),
    )

    removed = manager.cleanup_orphans_for_targets(
        existing_folders=set(),
        movies_by_ref=movies,
        expected_links=set(),
        affected_targets={missing_target},
    )

    assert removed == 1
    assert not orphan_link.exists()
    assert radarr.unmonitored == [123]
    assert radarr.deleted == []
    assert radarr.refreshed == [123]
