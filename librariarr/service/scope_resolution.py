from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectionScope:
    scoped_movie_ids: set[int] | None
    queued_movie_ids: set[int]
    movie_scope_kind: str
    movie_full_scope_reason: str
    scoped_series_ids: set[int] | None
    queued_series_ids: set[int]
    series_scope_kind: str
    series_full_scope_reason: str

    def as_dict(self) -> dict:
        return {
            "scoped_movie_ids": self.scoped_movie_ids,
            "queued_movie_ids": self.queued_movie_ids,
            "movie_scope_kind": self.movie_scope_kind,
            "movie_full_scope_reason": self.movie_full_scope_reason,
            "scoped_series_ids": self.scoped_series_ids,
            "queued_series_ids": self.queued_series_ids,
            "series_scope_kind": self.series_scope_kind,
            "series_full_scope_reason": self.series_full_scope_reason,
        }


def resolve_projection_scope(
    *,
    force_full_scope: bool,
    incremental_mode: bool,
    radarr_enabled: bool,
    sonarr_enabled: bool,
    sonarr_sync_enabled: bool,
    queued_movie_ids: set[int],
    queued_series_ids: set[int],
    ingested_movie_ids: set[int],
    auto_added_movie_ids: set[int],
    auto_added_series_ids: set[int],
    affected_path_movie_ids: set[int],
    affected_path_series_ids: set[int],
) -> ProjectionScope:
    scoped_movie_ids = _resolve_movie_scope_ids(
        force_full_scope=force_full_scope,
        incremental_mode=incremental_mode,
        radarr_enabled=radarr_enabled,
        queued_movie_ids=queued_movie_ids,
        ingested_movie_ids=ingested_movie_ids,
        auto_added_movie_ids=auto_added_movie_ids,
        affected_path_movie_ids=affected_path_movie_ids,
    )
    scoped_series_ids = _resolve_series_scope_ids(
        force_full_scope=force_full_scope,
        incremental_mode=incremental_mode,
        sonarr_enabled=sonarr_enabled,
        sonarr_sync_enabled=sonarr_sync_enabled,
        queued_series_ids=queued_series_ids,
        auto_added_series_ids=auto_added_series_ids,
        affected_path_series_ids=affected_path_series_ids,
    )

    movie_scope_kind = "scoped" if scoped_movie_ids is not None else "full"
    series_scope_kind = "scoped" if scoped_series_ids is not None else "full"

    return ProjectionScope(
        scoped_movie_ids=scoped_movie_ids,
        queued_movie_ids=queued_movie_ids,
        movie_scope_kind=movie_scope_kind,
        movie_full_scope_reason=_full_scope_reason(
            scope_kind=movie_scope_kind,
            force_full_scope=force_full_scope,
            arr_enabled=radarr_enabled,
            incremental_mode=incremental_mode,
        ),
        scoped_series_ids=scoped_series_ids,
        queued_series_ids=queued_series_ids,
        series_scope_kind=series_scope_kind,
        series_full_scope_reason=_full_scope_reason(
            scope_kind=series_scope_kind,
            force_full_scope=force_full_scope,
            arr_enabled=(sonarr_enabled and sonarr_sync_enabled),
            incremental_mode=incremental_mode,
        ),
    )


def _resolve_movie_scope_ids(
    *,
    force_full_scope: bool,
    incremental_mode: bool,
    radarr_enabled: bool,
    queued_movie_ids: set[int],
    ingested_movie_ids: set[int],
    auto_added_movie_ids: set[int],
    affected_path_movie_ids: set[int],
) -> set[int] | None:
    scoped_movie_ids: set[int] | None = None
    if radarr_enabled and not force_full_scope and queued_movie_ids:
        scoped_movie_ids = set(queued_movie_ids)

    if not force_full_scope:
        scoped_movie_ids = _merge_source_ids(
            scoped_movie_ids,
            ingested_movie_ids,
            incremental_mode,
        )
        scoped_movie_ids = _merge_source_ids(
            scoped_movie_ids,
            auto_added_movie_ids,
            incremental_mode,
        )
        scoped_movie_ids = _merge_source_ids(
            scoped_movie_ids,
            affected_path_movie_ids,
            incremental_mode,
        )

    return scoped_movie_ids


def _resolve_series_scope_ids(
    *,
    force_full_scope: bool,
    incremental_mode: bool,
    sonarr_enabled: bool,
    sonarr_sync_enabled: bool,
    queued_series_ids: set[int],
    auto_added_series_ids: set[int],
    affected_path_series_ids: set[int],
) -> set[int] | None:
    scoped_series_ids: set[int] | None = None
    if sonarr_enabled and sonarr_sync_enabled and not force_full_scope and queued_series_ids:
        scoped_series_ids = set(queued_series_ids)

    if not force_full_scope:
        scoped_series_ids = _merge_source_ids(
            scoped_series_ids,
            auto_added_series_ids,
            incremental_mode,
        )
        scoped_series_ids = _merge_source_ids(
            scoped_series_ids,
            affected_path_series_ids,
            incremental_mode,
        )

    return scoped_series_ids


def _merge_source_ids(
    current: set[int] | None,
    incoming: set[int],
    incremental_mode: bool,
) -> set[int] | None:
    if not incoming:
        return current
    if not (incremental_mode or current is not None):
        return current
    if current is None:
        return set(incoming)
    current.update(incoming)
    return current


def _full_scope_reason(
    *,
    scope_kind: str,
    force_full_scope: bool,
    arr_enabled: bool,
    incremental_mode: bool,
) -> str:
    if scope_kind == "scoped":
        return "-"
    if force_full_scope:
        return "force_full_scope"
    if not arr_enabled:
        return "arr_disabled_or_sync_disabled"
    if not incremental_mode:
        return "full_mode_requested"
    return "incremental_no_ids_from_sources"
