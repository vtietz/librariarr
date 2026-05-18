from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from ...clients.radarr import RadarrClient
from ...projection.orchestrator import _projection_state_db_path
from ...projection.provenance import ProjectionStateStore
from ...service.external_id_parsing import extract_external_ids_from_nfo
from ...sync.naming import parse_movie_ref
from ..history_events import append_history_event


def build_unmatched_movie_router(
    *,
    load_config_or_http_fn: Callable[[Path], Any],
    read_config_path_fn: Callable[[Request], Path],
) -> APIRouter:
    router = APIRouter()

    def unmatched_movie_candidates(
        request: Request,
        path: str = Query(...),
    ) -> dict[str, Any]:
        return _handle_unmatched_movie_candidates(
            request=request,
            path=path,
            load_config_or_http_fn=load_config_or_http_fn,
            read_config_path_fn=read_config_path_fn,
        )

    def unmatched_movie_resolve(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        return _handle_unmatched_movie_resolve(
            request=request,
            payload=payload,
            load_config_or_http_fn=load_config_or_http_fn,
            read_config_path_fn=read_config_path_fn,
        )

    router.add_api_route(
        "/api/fs/unmatched-movie-candidates",
        unmatched_movie_candidates,
        methods=["GET"],
    )
    router.add_api_route(
        "/api/fs/unmatched-movie-resolve",
        unmatched_movie_resolve,
        methods=["POST"],
    )

    return router


def _handle_unmatched_movie_candidates(
    *,
    request: Request,
    path: str,
    load_config_or_http_fn: Callable[[Path], Any],
    read_config_path_fn: Callable[[Request], Path],
) -> dict[str, Any]:
    target_path = _validated_absolute_path(path)
    config = load_config_or_http_fn(read_config_path_fn(request))
    managed_root = _resolve_movie_managed_root_for_path(config, target_path)
    folder_ref = parse_movie_ref(target_path.name)
    nfo_ids = _extract_nfo_ids_from_folder(target_path)

    radarr_client = RadarrClient(config.radarr.url, config.radarr.api_key)
    candidates = _lookup_unmatched_movie_candidates(
        radarr_client=radarr_client,
        folder_ref=folder_ref,
        nfo_ids=nfo_ids,
    )

    state_store = ProjectionStateStore(_projection_state_db_path())
    enriched_candidates = _enrich_candidates_with_mapping_state(
        state_store=state_store,
        target_path=target_path,
        candidates=candidates,
    )

    return {
        "path": str(target_path),
        "managed_root": str(managed_root),
        "folder": {
            "title": folder_ref.title,
            "year": folder_ref.year,
        },
        "nfo_ids": nfo_ids,
        "candidates": enriched_candidates,
    }


def _handle_unmatched_movie_resolve(
    *,
    request: Request,
    payload: dict[str, Any],
    load_config_or_http_fn: Callable[[Path], Any],
    read_config_path_fn: Callable[[Request], Path],
) -> dict[str, Any]:
    raw_path, raw_movie_id, force_takeover, winner_strategy, quarantine_loser = (
        _parse_unmatched_movie_resolve_payload(payload)
    )
    (
        config,
        target_path,
        radarr_client,
        state_store,
        managed_roots,
    ) = _prepare_unmatched_movie_resolve_context(
        request=request,
        raw_path=raw_path,
        raw_movie_id=raw_movie_id,
        load_config_or_http_fn=load_config_or_http_fn,
        read_config_path_fn=read_config_path_fn,
    )

    managed_by_movie_id = state_store.get_managed_folders_by_movie_ids()
    existing_path = managed_by_movie_id.get(raw_movie_id)
    incoming_path = target_path.resolve(strict=False)
    winner_path, loser_path = _resolve_winner_and_loser_paths(
        config=config,
        winner_strategy=winner_strategy,
        existing_path=existing_path,
        incoming_path=incoming_path,
    )

    effective_force_takeover, conflict_owner_was_stale = _resolve_winner_conflict_policy(
        winner_path=winner_path,
        movie_id=raw_movie_id,
        force_takeover=force_takeover,
        state_store=state_store,
        radarr_client=radarr_client,
        managed_roots=managed_roots,
    )
    _store_winner_mapping_or_raise_conflict(
        state_store=state_store,
        movie_id=raw_movie_id,
        winner_path=winner_path,
        force_takeover=effective_force_takeover,
    )

    loser_quarantined, loser_quarantine_path = _quarantine_loser_if_requested(
        quarantine_loser=quarantine_loser,
        loser_path=loser_path,
        winner_path=winner_path,
        movie_id=raw_movie_id,
        force_takeover=force_takeover,
        state_store=state_store,
        radarr_client=radarr_client,
        managed_roots=managed_roots,
    )

    _append_unmatched_movie_resolution_history_event(
        request=request,
        movie_id=raw_movie_id,
        winner_path=winner_path,
    )

    return _build_unmatched_movie_resolve_response(
        target_path=target_path,
        movie_id=raw_movie_id,
        force_takeover=force_takeover,
        winner_strategy=winner_strategy,
        winner_path=winner_path,
        loser_path=loser_path,
        loser_quarantined=loser_quarantined,
        loser_quarantine_path=loser_quarantine_path,
        conflict_owner_was_stale=conflict_owner_was_stale,
    )


def _parse_unmatched_movie_resolve_payload(
    payload: dict[str, Any],
) -> tuple[str, int, bool, str, bool]:
    raw_path = payload.get("path")
    raw_movie_id = payload.get("movie_id")
    force_takeover = bool(payload.get("force_takeover", False))
    winner_strategy = payload.get("winner_strategy", "incoming")
    quarantine_loser = bool(payload.get("quarantine_loser", False))

    if not isinstance(raw_path, str):
        raise HTTPException(status_code=400, detail="path is required")
    if not isinstance(raw_movie_id, int) or isinstance(raw_movie_id, bool):
        raise HTTPException(status_code=400, detail="movie_id must be an integer")
    if not isinstance(winner_strategy, str) or winner_strategy not in {"incoming", "existing"}:
        raise HTTPException(
            status_code=400,
            detail="winner_strategy must be one of: incoming, existing",
        )

    return raw_path, raw_movie_id, force_takeover, winner_strategy, quarantine_loser


def _prepare_unmatched_movie_resolve_context(
    *,
    request: Request,
    raw_path: str,
    raw_movie_id: int,
    load_config_or_http_fn: Callable[[Path], Any],
    read_config_path_fn: Callable[[Request], Path],
) -> tuple[Any, Path, RadarrClient, ProjectionStateStore, list[Path]]:
    target_path = _validated_absolute_path(raw_path)
    config = load_config_or_http_fn(read_config_path_fn(request))
    _resolve_movie_managed_root_for_path(config, target_path)
    if not target_path.exists() or not target_path.is_dir():
        raise HTTPException(status_code=400, detail="path must exist and be a directory")

    radarr_client = RadarrClient(config.radarr.url, config.radarr.api_key)
    if not radarr_client.get_movie(raw_movie_id):
        raise HTTPException(status_code=404, detail=f"Radarr movie id {raw_movie_id} not found")

    state_store = ProjectionStateStore(_projection_state_db_path())
    managed_roots = _configured_movie_managed_roots(config)
    return config, target_path, radarr_client, state_store, managed_roots


def _resolve_winner_and_loser_paths(
    *,
    config: Any,
    winner_strategy: str,
    existing_path: Path | None,
    incoming_path: Path,
) -> tuple[Path, Path | None]:
    winner_path = _resolve_winner_path(
        winner_strategy=winner_strategy,
        existing_path=existing_path,
        incoming_path=incoming_path,
    )
    if not winner_path.exists() or not winner_path.is_dir():
        raise HTTPException(status_code=400, detail="winner_path must exist and be a directory")
    _resolve_movie_managed_root_for_path(config, winner_path)
    loser_path = _resolve_loser_path(
        winner_path=winner_path,
        existing_path=existing_path,
        incoming_path=incoming_path,
    )
    return winner_path, loser_path


def _resolve_winner_path(
    *,
    winner_strategy: str,
    existing_path: Path | None,
    incoming_path: Path,
) -> Path:
    if winner_strategy == "existing":
        if existing_path is None:
            raise HTTPException(
                status_code=400,
                detail="winner_strategy=existing requires an existing mapped folder",
            )
        return existing_path.resolve(strict=False)
    return incoming_path


def _resolve_loser_path(
    *,
    winner_path: Path,
    existing_path: Path | None,
    incoming_path: Path,
) -> Path | None:
    if winner_path == incoming_path:
        if existing_path is None:
            return None
        resolved_existing_path = existing_path.resolve(strict=False)
        if resolved_existing_path == winner_path:
            return None
        return resolved_existing_path
    if incoming_path != winner_path:
        return incoming_path
    return None


def _resolve_winner_conflict_policy(
    *,
    winner_path: Path,
    movie_id: int,
    force_takeover: bool,
    state_store: ProjectionStateStore,
    radarr_client: RadarrClient,
    managed_roots: list[Path],
) -> tuple[bool, bool]:
    current_owner = state_store.get_movie_id_for_managed_folder(winner_path)
    if current_owner is None or current_owner == movie_id:
        return force_takeover, False

    owner_is_active = _is_active_valid_owner(
        owner_movie_id=current_owner,
        state_store=state_store,
        radarr_client=radarr_client,
        managed_roots=managed_roots,
    )
    if owner_is_active and not force_takeover:
        _raise_winner_conflict(current_owner)
    if owner_is_active:
        return force_takeover, False
    return True, True


def _store_winner_mapping_or_raise_conflict(
    *,
    state_store: ProjectionStateStore,
    movie_id: int,
    winner_path: Path,
    force_takeover: bool,
) -> None:
    stored = state_store.set_managed_folder(
        movie_id,
        winner_path,
        force_takeover=force_takeover,
    )
    if stored:
        return
    current_owner = state_store.get_movie_id_for_managed_folder(winner_path)
    _raise_winner_conflict(current_owner)


def _raise_winner_conflict(owner_movie_id: int | None) -> None:
    raise HTTPException(
        status_code=409,
        detail=(
            "Managed folder is already mapped to another movie_id "
            f"({owner_movie_id}). Retry with force_takeover=true to reassign."
        ),
    )


def _quarantine_loser_if_requested(
    *,
    quarantine_loser: bool,
    loser_path: Path | None,
    winner_path: Path,
    movie_id: int,
    force_takeover: bool,
    state_store: ProjectionStateStore,
    radarr_client: RadarrClient,
    managed_roots: list[Path],
) -> tuple[bool, str | None]:
    if (
        not quarantine_loser
        or loser_path is None
        or loser_path == winner_path
        or not loser_path.exists()
    ):
        return False, None

    loser_owner_to_remove = _resolve_loser_owner_to_remove(
        loser_path=loser_path,
        movie_id=movie_id,
        force_takeover=force_takeover,
        state_store=state_store,
        radarr_client=radarr_client,
        managed_roots=managed_roots,
    )
    loser_managed_root = _resolve_movie_managed_root_if_any(
        target_path=loser_path,
        managed_roots=managed_roots,
    )
    if loser_managed_root is None:
        return False, None

    quarantine_target = _build_quarantine_target(
        source_path=loser_path,
        managed_root=loser_managed_root,
    )
    quarantine_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(loser_path), str(quarantine_target))
    if loser_owner_to_remove is not None:
        state_store.remove_managed_folder(loser_owner_to_remove)
    return True, str(quarantine_target)


def _resolve_loser_owner_to_remove(
    *,
    loser_path: Path,
    movie_id: int,
    force_takeover: bool,
    state_store: ProjectionStateStore,
    radarr_client: RadarrClient,
    managed_roots: list[Path],
) -> int | None:
    loser_owner = state_store.get_movie_id_for_managed_folder(loser_path.resolve(strict=False))
    if loser_owner is None or loser_owner == movie_id:
        return None

    loser_owner_is_active = _is_active_valid_owner(
        owner_movie_id=loser_owner,
        state_store=state_store,
        radarr_client=radarr_client,
        managed_roots=managed_roots,
    )
    if loser_owner_is_active and not force_takeover:
        raise HTTPException(
            status_code=409,
            detail=(
                "Loser folder is already mapped to another movie_id "
                f"({loser_owner}). Retry with force_takeover=true to quarantine."
            ),
        )
    return loser_owner


def _append_unmatched_movie_resolution_history_event(
    *,
    request: Request,
    movie_id: int,
    winner_path: Path,
) -> None:
    history_state_store = getattr(getattr(request.app.state, "web", None), "state_store", None)
    if history_state_store is None:
        return
    append_history_event(
        history_state_store,
        scenario="manual_unmatched_resolution",
        category="discovery_warning",
        title=f"Mapped unmatched folder to Radarr movie {movie_id}",
        message=f"Mapped {winner_path} to movie_id={movie_id}.",
    )


def _build_unmatched_movie_resolve_response(
    *,
    target_path: Path,
    movie_id: int,
    force_takeover: bool,
    winner_strategy: str,
    winner_path: Path,
    loser_path: Path | None,
    loser_quarantined: bool,
    loser_quarantine_path: str | None,
    conflict_owner_was_stale: bool,
) -> dict[str, Any]:
    return {
        "ok": True,
        "path": str(target_path),
        "movie_id": movie_id,
        "force_takeover": force_takeover,
        "winner_strategy": winner_strategy,
        "winner_path": str(winner_path),
        "loser_path": str(loser_path) if loser_path is not None else None,
        "loser_quarantined": loser_quarantined,
        "loser_quarantine_path": loser_quarantine_path,
        "conflict_owner_was_stale": conflict_owner_was_stale,
    }


def _validated_absolute_path(raw_path: str) -> Path:
    value = raw_path.strip()
    if not value:
        raise HTTPException(status_code=400, detail="path must not be empty")
    path = Path(value)
    if not path.is_absolute():
        raise HTTPException(status_code=400, detail="path must be an absolute path")
    return path.resolve(strict=False)


def _resolve_movie_managed_root_for_path(config: Any, target_path: Path) -> Path:
    managed_roots = _configured_movie_managed_roots(config)
    for managed_root in managed_roots:
        if target_path == managed_root or managed_root in target_path.parents:
            return managed_root
    raise HTTPException(status_code=403, detail="path is not under a configured movie managed root")


def _configured_movie_managed_roots(config: Any) -> list[Path]:
    return [
        Path(item.managed_root).resolve(strict=False) for item in config.paths.movie_root_mappings
    ]


def _resolve_movie_managed_root_if_any(
    *,
    target_path: Path,
    managed_roots: list[Path],
) -> Path | None:
    for managed_root in managed_roots:
        if target_path == managed_root or managed_root in target_path.parents:
            return managed_root
    return None


def _is_active_valid_owner(
    *,
    owner_movie_id: int,
    state_store: ProjectionStateStore,
    radarr_client: RadarrClient,
    managed_roots: list[Path],
) -> bool:
    owner_movie = radarr_client.get_movie(owner_movie_id)
    if not owner_movie:
        return False

    owner_folder = state_store.get_managed_folders_by_movie_ids().get(owner_movie_id)
    if owner_folder is None:
        return False
    owner_folder = owner_folder.resolve(strict=False)
    if not owner_folder.exists() or not owner_folder.is_dir():
        return False

    owner_managed_root = _resolve_movie_managed_root_if_any(
        target_path=owner_folder,
        managed_roots=managed_roots,
    )
    return owner_managed_root is not None


def _build_quarantine_target(*, source_path: Path, managed_root: Path) -> Path:
    trash_root = managed_root / ".deletedByLibrariarr"
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    candidate = trash_root / f"{source_path.name}.{timestamp}"
    suffix = 1
    while candidate.exists():
        candidate = trash_root / f"{source_path.name}.{timestamp}.{suffix}"
        suffix += 1
    return candidate


def _extract_nfo_ids_from_folder(target_path: Path) -> dict[str, str]:
    ids: dict[str, str] = {}
    for candidate in sorted(target_path.glob("*.nfo")):
        tmdb_id, imdb_id, _tvdb_id = extract_external_ids_from_nfo(candidate)
        if tmdb_id is not None and "tmdb_id" not in ids:
            ids["tmdb_id"] = str(tmdb_id)
        if imdb_id is not None and "imdb_id" not in ids:
            ids["imdb_id"] = imdb_id
        if ids.get("tmdb_id") and ids.get("imdb_id"):
            break
    return ids


def _lookup_unmatched_movie_candidates(
    *,
    radarr_client: RadarrClient,
    folder_ref: Any,
    nfo_ids: dict[str, str],
) -> list[dict[str, Any]]:
    candidate_by_id: dict[int, dict[str, Any]] = {}
    _collect_lookup_candidates(
        radarr_client=radarr_client,
        nfo_ids=nfo_ids,
        folder_ref=folder_ref,
        candidate_by_id=candidate_by_id,
    )

    title = str(getattr(folder_ref, "title", "") or "")
    year = getattr(folder_ref, "year", None)
    _score_title_and_year_matches(candidate_by_id=candidate_by_id, title=title, year=year)

    return sorted(
        candidate_by_id.values(),
        key=lambda item: (int(item.get("score", 0)), -int(item.get("movie_id", 0))),
        reverse=True,
    )


def _collect_lookup_candidates(
    *,
    radarr_client: RadarrClient,
    nfo_ids: dict[str, str],
    folder_ref: Any,
    candidate_by_id: dict[int, dict[str, Any]],
) -> None:
    def _record(movie: dict[str, Any], reason: str, score_delta: int) -> None:
        _record_candidate(
            candidate_by_id=candidate_by_id,
            movie=movie,
            reason=reason,
            score_delta=score_delta,
        )

    tmdb_id = nfo_ids.get("tmdb_id")
    if tmdb_id:
        for movie in radarr_client.lookup_movies(f"tmdb:{tmdb_id}"):
            _record(movie, "NFO TMDB match", 100)

    imdb_id = nfo_ids.get("imdb_id")
    if imdb_id:
        for movie in radarr_client.lookup_movies(f"imdb:{imdb_id}"):
            _record(movie, "NFO IMDb match", 95)

    title = str(getattr(folder_ref, "title", "") or "")
    year = getattr(folder_ref, "year", None)
    term = f"{title} {year}".strip()
    if term:
        for movie in radarr_client.lookup_movies(term):
            _record(movie, "Title lookup", 30)


def _record_candidate(
    *,
    candidate_by_id: dict[int, dict[str, Any]],
    movie: dict[str, Any],
    reason: str,
    score_delta: int,
) -> None:
    movie_id = movie.get("id")
    if not isinstance(movie_id, int):
        return
    entry = candidate_by_id.setdefault(
        movie_id,
        {
            "movie_id": movie_id,
            "title": str(movie.get("title", "")),
            "year": movie.get("year") if isinstance(movie.get("year"), int) else None,
            "path": str(movie.get("path", "")),
            "tmdb_id": _coerce_int_or_none(movie.get("tmdbId")),
            "imdb_id": str(movie.get("imdbId", "") or "") or None,
            "score": 0,
            "reasons": [],
        },
    )
    entry["score"] = int(entry["score"]) + score_delta
    reasons = entry["reasons"]
    if isinstance(reasons, list) and reason not in reasons:
        reasons.append(reason)


def _score_title_and_year_matches(
    *,
    candidate_by_id: dict[int, dict[str, Any]],
    title: str,
    year: Any,
) -> None:
    normalized_title = _normalize_title(title)
    for entry in candidate_by_id.values():
        candidate_title = _normalize_title(str(entry.get("title", "")))
        if normalized_title and candidate_title == normalized_title:
            entry["score"] = int(entry["score"]) + 25
            if "Exact normalized title match" not in entry["reasons"]:
                entry["reasons"].append("Exact normalized title match")
        candidate_year = entry.get("year")
        if isinstance(year, int) and isinstance(candidate_year, int) and candidate_year == year:
            entry["score"] = int(entry["score"]) + 20
            if "Year match" not in entry["reasons"]:
                entry["reasons"].append("Year match")
        entry["confidence"] = _confidence_for_score(int(entry["score"]))


def _enrich_candidates_with_mapping_state(
    *,
    state_store: ProjectionStateStore,
    target_path: Path,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    owner_by_movie = state_store.get_managed_folders_by_movie_ids()
    for item in candidates:
        movie_id = item.get("movie_id")
        if not isinstance(movie_id, int):
            item["mapped_folder"] = None
            item["mapping_conflict"] = False
            continue
        mapped_folder = owner_by_movie.get(movie_id)
        mapped_folder_str = str(mapped_folder) if mapped_folder is not None else None
        item["mapped_folder"] = mapped_folder_str
        item["mapping_conflict"] = mapped_folder_str is not None and Path(
            mapped_folder_str
        ).resolve(strict=False) != target_path.resolve(strict=False)
    return candidates


def _coerce_int_or_none(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _normalize_title(value: str) -> str:
    lowered = value.lower().strip()
    compact = re.sub(r"[^a-z0-9]+", "", lowered)
    return compact


def _confidence_for_score(score: int) -> str:
    if score >= 100:
        return "high"
    if score >= 50:
        return "medium"
    return "low"
