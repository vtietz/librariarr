from pathlib import Path

from librariarr.core import (
    MediaScope,
    create_reconcile_plan,
    resolve_reconcile_mode,
    should_fetch_arr_index,
)


def _scope(
    *,
    folders: dict[Path, Path] | None = None,
    affected_targets: set[Path] | None = None,
    incremental_mode: bool,
) -> MediaScope:
    return MediaScope(
        folders=folders or {},
        all_folders={},
        affected_targets=affected_targets or set(),
        incremental_mode=incremental_mode,
    )


def test_resolve_reconcile_mode_for_full_cycle() -> None:
    mode, affected_count = resolve_reconcile_mode(None)

    assert mode == "full"
    assert affected_count == "all"


def test_resolve_reconcile_mode_for_incremental_cycle() -> None:
    mode, affected_count = resolve_reconcile_mode({Path("/tmp/a"), Path("/tmp/b")})

    assert mode == "incremental"
    assert affected_count == 2


def test_should_fetch_arr_index_for_full_scope() -> None:
    scope = _scope(incremental_mode=False)

    assert should_fetch_arr_index(True, scope) is True


def test_should_fetch_arr_index_for_incremental_scope_with_changed_folders() -> None:
    scope = _scope(
        folders={Path("/media/movies/test"): Path("/shadow/movies")},
        incremental_mode=True,
    )

    assert should_fetch_arr_index(True, scope) is True


def test_should_fetch_arr_index_for_incremental_scope_with_affected_targets_only() -> None:
    scope = _scope(affected_targets={Path("/shadow/movies/Test (2020)")}, incremental_mode=True)

    assert should_fetch_arr_index(True, scope) is True


def test_should_not_fetch_arr_index_when_incremental_scope_is_empty() -> None:
    scope = _scope(incremental_mode=True)

    assert should_fetch_arr_index(True, scope) is False


def test_should_not_fetch_arr_index_when_sync_is_disabled() -> None:
    scope = _scope(
        folders={Path("/media/movies/test"): Path("/shadow/movies")},
        incremental_mode=False,
    )

    assert should_fetch_arr_index(False, scope) is False


def test_create_reconcile_plan_uses_scope_and_sync_flags() -> None:
    movie_scope = _scope(
        folders={Path("/media/movies/test"): Path("/shadow/movies")},
        incremental_mode=True,
    )
    series_scope = _scope(incremental_mode=True)

    plan = create_reconcile_plan(
        mode="incremental",
        affected_paths_count=1,
        movie_scope=movie_scope,
        series_scope=series_scope,
        movie_sync_enabled=True,
        series_sync_enabled=True,
    )

    assert plan.mode == "incremental"
    assert plan.affected_paths_count == 1
    assert plan.movie_scope == movie_scope
    assert plan.series_scope == series_scope
    assert plan.fetch_movie_index is True
    assert plan.fetch_series_index is False
