from __future__ import annotations

from .index_builder import should_fetch_arr_index
from .plan import MediaScope, ReconcilePlan


def create_reconcile_plan(
    *,
    mode: str,
    affected_paths_count: int | str,
    movie_scope: MediaScope,
    series_scope: MediaScope,
    movie_sync_enabled: bool,
    series_sync_enabled: bool,
) -> ReconcilePlan:
    return ReconcilePlan(
        mode=mode,
        affected_paths_count=affected_paths_count,
        movie_scope=movie_scope,
        series_scope=series_scope,
        fetch_movie_index=should_fetch_arr_index(movie_sync_enabled, movie_scope),
        fetch_series_index=should_fetch_arr_index(series_sync_enabled, series_scope),
    )
