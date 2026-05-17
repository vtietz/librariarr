from __future__ import annotations

import re
from collections.abc import Callable
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

    @router.get("/api/fs/unmatched-movie-candidates")
    def unmatched_movie_candidates(
        request: Request,
        path: str = Query(...),
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

    @router.post("/api/fs/unmatched-movie-resolve")
    def unmatched_movie_resolve(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        raw_path = payload.get("path")
        raw_movie_id = payload.get("movie_id")
        force_takeover = bool(payload.get("force_takeover", False))

        if not isinstance(raw_path, str):
            raise HTTPException(status_code=400, detail="path is required")
        if not isinstance(raw_movie_id, int) or isinstance(raw_movie_id, bool):
            raise HTTPException(status_code=400, detail="movie_id must be an integer")

        target_path = _validated_absolute_path(raw_path)
        config = load_config_or_http_fn(read_config_path_fn(request))
        _resolve_movie_managed_root_for_path(config, target_path)

        if not target_path.exists() or not target_path.is_dir():
            raise HTTPException(status_code=400, detail="path must exist and be a directory")

        radarr_client = RadarrClient(config.radarr.url, config.radarr.api_key)
        movie = radarr_client.get_movie(raw_movie_id)
        if not movie:
            raise HTTPException(status_code=404, detail=f"Radarr movie id {raw_movie_id} not found")

        state_store = ProjectionStateStore(_projection_state_db_path())
        stored = state_store.set_managed_folder(
            raw_movie_id,
            target_path,
            force_takeover=force_takeover,
        )
        if not stored:
            current_owner = state_store.get_movie_id_for_managed_folder(target_path)
            raise HTTPException(
                status_code=409,
                detail=(
                    "Managed folder is already mapped to another movie_id "
                    f"({current_owner}). Retry with force_takeover=true to reassign."
                ),
            )

        history_state_store = getattr(getattr(request.app.state, "web", None), "state_store", None)
        if history_state_store is not None:
            append_history_event(
                history_state_store,
                scenario="manual_unmatched_resolution",
                category="discovery_warning",
                title=f"Mapped unmatched folder to Radarr movie {raw_movie_id}",
                message=f"Mapped {target_path} to movie_id={raw_movie_id}.",
            )

        return {
            "ok": True,
            "path": str(target_path),
            "movie_id": raw_movie_id,
            "force_takeover": force_takeover,
        }

    return router


def _validated_absolute_path(raw_path: str) -> Path:
    value = raw_path.strip()
    if not value:
        raise HTTPException(status_code=400, detail="path must not be empty")
    path = Path(value)
    if not path.is_absolute():
        raise HTTPException(status_code=400, detail="path must be an absolute path")
    return path.resolve(strict=False)


def _resolve_movie_managed_root_for_path(config: Any, target_path: Path) -> Path:
    managed_roots = [
        Path(item.managed_root).resolve(strict=False) for item in config.paths.movie_root_mappings
    ]
    for managed_root in managed_roots:
        if target_path == managed_root or managed_root in target_path.parents:
            return managed_root
    raise HTTPException(status_code=403, detail="path is not under a configured movie managed root")


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
