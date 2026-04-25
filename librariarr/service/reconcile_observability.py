from __future__ import annotations

from pathlib import Path

from .common import LOG


def first_path(paths: set[Path] | None) -> str:
    if not paths:
        return "-"
    return sorted(str(path) for path in paths)[0]


def _sample_ids(ids: set[int]) -> str:
    if not ids:
        return "-"
    return "|".join(str(value) for value in sorted(ids)[:10])


def log_scope_resolved(
    *,
    trigger_source: str,
    reconcile_mode: str,
    affected_paths_count: int | str,
    trigger_path: str,
    movie_scope_kind: str,
    movie_full_scope_reason: str,
    scoped_movie_ids: set[int] | None,
    queued_movie_ids: set[int],
    ingested_movie_ids: set[int],
    auto_added_movie_ids: set[int],
    series_scope_kind: str,
    series_full_scope_reason: str,
    scoped_series_ids: set[int] | None,
    queued_series_ids: set[int],
    auto_added_series_ids: set[int],
) -> None:
    LOG.info(
        "Reconcile scope resolved: source=%s mode=%s affected_paths=%s trigger_path=%s "
        "movie_scope=%s movie_count=%s series_scope=%s series_count=%s",
        trigger_source,
        reconcile_mode,
        affected_paths_count,
        trigger_path,
        movie_scope_kind,
        len(scoped_movie_ids or set()),
        series_scope_kind,
        len(scoped_series_ids or set()),
    )
    LOG.debug(
        "Reconcile scope details: source=%s mode=%s movie_full_scope_reason=%s "
        "movie_scoped_ids_sample=%s movie_ids_webhook_count=%s movie_ids_webhook_sample=%s "
        "movie_ids_ingest_count=%s movie_ids_ingest_sample=%s movie_ids_auto_add_count=%s "
        "movie_ids_auto_add_sample=%s series_full_scope_reason=%s "
        "series_scoped_ids_sample=%s series_ids_webhook_count=%s "
        "series_ids_webhook_sample=%s series_ids_auto_add_count=%s "
        "series_ids_auto_add_sample=%s",
        trigger_source,
        reconcile_mode,
        movie_full_scope_reason,
        _sample_ids(scoped_movie_ids or set()),
        len(queued_movie_ids),
        _sample_ids(queued_movie_ids),
        len(ingested_movie_ids),
        _sample_ids(ingested_movie_ids),
        len(auto_added_movie_ids),
        _sample_ids(auto_added_movie_ids),
        series_full_scope_reason,
        _sample_ids(scoped_series_ids or set()),
        len(queued_series_ids),
        _sample_ids(queued_series_ids),
        len(auto_added_series_ids),
        _sample_ids(auto_added_series_ids),
    )


def log_projection_dispatch(
    *,
    arr: str,
    trigger_source: str,
    reconcile_mode: str,
    scope_kind: str,
    full_scope_reason: str,
    scoped_ids: set[int] | None,
) -> None:
    scope_explanation = "-"
    if scope_kind == "scoped_immediate":
        scope_explanation = (
            "single-item immediate projection triggered by path reconciliation/auto-add"
        )

    LOG.info(
        "Projection dispatch: arr=%s source=%s mode=%s scope_kind=%s scoped_ids_count=%s",
        arr,
        trigger_source,
        reconcile_mode,
        scope_kind,
        len(scoped_ids or set()),
    )
    LOG.debug(
        "Projection dispatch details: arr=%s full_scope_reason=%s scoped_ids_sample=%s "
        "scope_explanation=%s",
        arr,
        full_scope_reason,
        _sample_ids(scoped_ids or set()),
        scope_explanation,
    )
