from pathlib import Path

from librariarr.core import build_cleanup_tasks


def test_build_cleanup_tasks_returns_empty_when_cleanup_disabled() -> None:
    tasks = build_cleanup_tasks(
        remove_orphaned_links=False,
        radarr_enabled=True,
        sonarr_enabled=True,
        movie_incremental_mode=False,
        series_incremental_mode=False,
        movie_affected_targets={Path("/shadow/movies/A")},
        series_affected_targets={Path("/shadow/series/B")},
        matched_movie_ids={1},
        matched_series_ids={2},
    )

    assert tasks == []


def test_build_cleanup_tasks_includes_enabled_kinds() -> None:
    movie_target = Path("/shadow/movies/A")
    series_target = Path("/shadow/series/B")

    tasks = build_cleanup_tasks(
        remove_orphaned_links=True,
        radarr_enabled=True,
        sonarr_enabled=True,
        movie_incremental_mode=True,
        series_incremental_mode=False,
        movie_affected_targets={movie_target},
        series_affected_targets={series_target},
        matched_movie_ids={11},
        matched_series_ids={22},
    )

    assert [task.kind for task in tasks] == ["radarr", "sonarr"]

    radarr_task, sonarr_task = tasks
    assert radarr_task.incremental_mode is True
    assert radarr_task.affected_targets == {movie_target}
    assert radarr_task.matched_item_ids == {11}

    assert sonarr_task.incremental_mode is False
    assert sonarr_task.affected_targets == {series_target}
    assert sonarr_task.matched_item_ids == {22}


def test_build_cleanup_tasks_skips_disabled_service() -> None:
    tasks = build_cleanup_tasks(
        remove_orphaned_links=True,
        radarr_enabled=False,
        sonarr_enabled=True,
        movie_incremental_mode=False,
        series_incremental_mode=True,
        movie_affected_targets=set(),
        series_affected_targets={Path("/shadow/series/C")},
        matched_movie_ids=set(),
        matched_series_ids={3},
    )

    assert len(tasks) == 1
    assert tasks[0].kind == "sonarr"
