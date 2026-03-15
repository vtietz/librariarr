from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..clients.radarr import RadarrClient
from ..clients.sonarr import SonarrClient
from ..config import AppConfig, load_config
from ..runtime import get_runtime_status_tracker
from ..service import LibrariArrService
from ..sync.discovery import discover_movie_folders
from ..sync.naming import parse_movie_ref
from .log_buffer import get_log_buffer
from .mapped_cache import get_mapped_directories_cache
from .mapped_cache import shadow_roots as _shadow_roots

LOG = logging.getLogger(__name__)


def _safe_log_url(url: str) -> str:
    """Return URL with only scheme + host for safe logging (no credentials/paths)."""
    try:
        parsed = urlparse(url)
        return (
            f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
            if parsed.port
            else f"{parsed.scheme}://{parsed.hostname}"
        )
    except Exception:
        return "<invalid-url>"


class ArrConnectionRequest(BaseModel):
    url: str = Field(min_length=1)
    api_key: str = Field(min_length=1)


def _load_config_or_http(config_path: Path) -> AppConfig:
    try:
        return load_config(config_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unable to load config: {exc}") from exc


def _read_config_path(request: Request) -> Path:
    return Path(request.app.state.web.config_path)


def _job_manager_or_http(request: Request):
    manager = getattr(request.app.state.web, "job_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Job manager is unavailable.")
    return manager


def _build_discovery_warnings_payload(config: AppConfig, limit: int = 200) -> dict[str, Any]:
    video_exts = set(config.runtime.scan_video_extensions or [".mkv", ".mp4", ".avi", ".mov"])
    exclude_paths = list(config.paths.exclude_paths)

    all_movie_paths: set[Path] = set()
    included_movie_paths: set[Path] = set()

    for mapping in config.paths.root_mappings:
        nested_root = Path(mapping.nested_root)
        all_movie_paths.update(discover_movie_folders(nested_root, video_exts, []))
        included_movie_paths.update(discover_movie_folders(nested_root, video_exts, exclude_paths))

    excluded_movie_paths = sorted(
        all_movie_paths - included_movie_paths,
        key=lambda path: str(path),
    )

    grouped: dict[tuple[str, int | None], list[Path]] = {}
    for movie_path in all_movie_paths:
        movie_ref = parse_movie_ref(movie_path.name)
        grouped.setdefault((movie_ref.title, movie_ref.year), []).append(movie_path)

    duplicate_movie_candidates: list[dict[str, Any]] = []
    for (title, year), paths in grouped.items():
        if len(paths) < 2:
            continue

        ordered = sorted(paths, key=lambda path: str(path))
        preferred = [path for path in ordered if path in included_movie_paths]
        primary_path = preferred[0] if preferred else ordered[0]
        duplicate_paths = [path for path in ordered if path != primary_path]

        duplicate_movie_candidates.append(
            {
                "movie_ref": f"{title} ({year})" if year is not None else title,
                "primary_path": str(primary_path),
                "duplicate_paths": [str(path) for path in duplicate_paths],
                "contains_excluded": any(path in excluded_movie_paths for path in ordered),
            }
        )

    duplicate_movie_candidates.sort(
        key=lambda item: (
            -len(item["duplicate_paths"]),
            str(item["movie_ref"]),
        )
    )

    return {
        "summary": {
            "exclude_patterns_count": len(exclude_paths),
            "excluded_movie_candidates": len(excluded_movie_paths),
            "duplicate_movie_candidates": len(duplicate_movie_candidates),
        },
        "exclude_paths": exclude_paths,
        "excluded_movie_candidates": [
            {
                "path": str(path),
                "reason": "matches paths.exclude_paths",
            }
            for path in excluded_movie_paths[:limit]
        ],
        "duplicate_movie_candidates": duplicate_movie_candidates[:limit],
    }


def run_radarr_diagnostics(config: AppConfig) -> dict[str, Any]:
    if not config.radarr.enabled:
        return {"status": "disabled", "issues": [], "details": {}}

    client = RadarrClient(
        config.radarr.url,
        config.radarr.api_key,
        refresh_debounce_seconds=config.radarr.refresh_debounce_seconds,
    )
    issues: list[dict[str, str]] = []
    details: dict[str, Any] = {}

    try:
        details["system_status"] = client.get_system_status()
    except Exception as exc:
        issues.append({"severity": "error", "message": f"System status failed: {exc}"})

    quality_profiles: list[dict[str, Any]] = []
    quality_definitions: list[dict[str, Any]] = []
    custom_formats: list[dict[str, Any]] = []

    try:
        quality_profiles = client.get_quality_profiles()
    except Exception as exc:
        issues.append({"severity": "warning", "message": f"Quality profiles failed: {exc}"})

    try:
        quality_definitions = client.get_quality_definitions()
    except Exception as exc:
        issues.append(
            {
                "severity": "warning",
                "message": f"Quality definitions failed: {exc}",
            }
        )

    try:
        custom_formats = client.get_custom_formats()
    except Exception as exc:
        issues.append({"severity": "warning", "message": f"Custom formats failed: {exc}"})

    try:
        details["root_folders"] = client.get_root_folders()
    except Exception as exc:
        issues.append({"severity": "warning", "message": f"Root folders failed: {exc}"})

    configured_quality_ids = {rule.target_id for rule in config.effective_radarr_quality_map()}
    available_quality_ids = {
        item.get("id")
        for item in quality_definitions
        if isinstance(item, dict) and isinstance(item.get("id"), int)
    }
    missing_quality_ids = sorted(
        quality_id
        for quality_id in configured_quality_ids
        if quality_id not in available_quality_ids
    )
    if missing_quality_ids:
        issues.append(
            {
                "severity": "warning",
                "message": "Configured Radarr quality_map target_id values "
                f"are missing: {missing_quality_ids}",
            }
        )

    configured_format_ids = {rule.format_id for rule in config.effective_radarr_custom_format_map()}
    available_format_ids = {
        item.get("id")
        for item in custom_formats
        if isinstance(item, dict) and isinstance(item.get("id"), int)
    }
    missing_format_ids = sorted(
        format_id for format_id in configured_format_ids if format_id not in available_format_ids
    )
    if missing_format_ids:
        issues.append(
            {
                "severity": "warning",
                "message": "Configured Radarr custom_format_map format_id "
                f"values are missing: {missing_format_ids}",
            }
        )

    details["quality_profiles_count"] = len(quality_profiles)
    details["quality_definitions_count"] = len(quality_definitions)
    details["custom_formats_count"] = len(custom_formats)

    return {
        "status": "ok" if not issues else "warning",
        "issues": issues,
        "details": details,
    }


def run_sonarr_diagnostics(config: AppConfig) -> dict[str, Any]:
    if not config.sonarr.enabled:
        return {"status": "disabled", "issues": [], "details": {}}

    client = SonarrClient(
        config.sonarr.url,
        config.sonarr.api_key,
        refresh_debounce_seconds=config.sonarr.refresh_debounce_seconds,
    )
    issues: list[dict[str, str]] = []
    details: dict[str, Any] = {}

    try:
        details["system_status"] = client.get_system_status()
    except Exception as exc:
        issues.append({"severity": "error", "message": f"System status failed: {exc}"})

    quality_profiles: list[dict[str, Any]] = []
    language_profiles: list[dict[str, Any]] = []

    try:
        quality_profiles = client.get_quality_profiles()
    except Exception as exc:
        issues.append({"severity": "warning", "message": f"Quality profiles failed: {exc}"})

    try:
        language_profiles = client.get_language_profiles()
    except Exception as exc:
        issues.append(
            {
                "severity": "warning",
                "message": f"Language profiles failed: {exc}",
            }
        )

    try:
        details["root_folders"] = client.get_root_folders()
    except Exception as exc:
        issues.append({"severity": "warning", "message": f"Root folders failed: {exc}"})

    available_quality_ids = {
        item.get("id") for item in quality_profiles if isinstance(item.get("id"), int)
    }
    configured_quality_ids = {
        rule.profile_id for rule in config.effective_sonarr_quality_profile_map()
    }
    missing_quality_ids = sorted(
        profile_id
        for profile_id in configured_quality_ids
        if profile_id not in available_quality_ids
    )
    if missing_quality_ids:
        issues.append(
            {
                "severity": "warning",
                "message": "Configured Sonarr quality_profile_map profile_id"
                f" values are missing: {missing_quality_ids}",
            }
        )

    available_language_ids = {
        item.get("id") for item in language_profiles if isinstance(item.get("id"), int)
    }
    configured_language_ids = {
        rule.profile_id for rule in config.effective_sonarr_language_profile_map()
    }
    missing_language_ids = sorted(
        profile_id
        for profile_id in configured_language_ids
        if profile_id not in available_language_ids
    )
    if missing_language_ids:
        issues.append(
            {
                "severity": "warning",
                "message": "Configured Sonarr language_profile_map profile_id"
                f" values are missing: {missing_language_ids}",
            }
        )

    details["quality_profiles_count"] = len(quality_profiles)
    details["language_profiles_count"] = len(language_profiles)

    return {
        "status": "ok" if not issues else "warning",
        "issues": issues,
        "details": details,
    }


def build_operations_router() -> APIRouter:  # noqa: C901
    router = APIRouter()
    runtime_status = get_runtime_status_tracker()
    mapped_cache = get_mapped_directories_cache()

    @router.get("/api/logs")
    def app_logs(
        tail: int = Query(default=250, ge=10, le=2000),
    ) -> dict[str, Any]:
        buf = get_log_buffer()
        if buf is None:
            return {"tail": tail, "items": []}
        return {"tail": tail, "items": buf.get_entries(tail=tail)}

    @router.get("/api/logs/stream")
    async def app_logs_stream(
        request: Request,
        max_events: int = Query(default=0, ge=0),
    ) -> StreamingResponse:
        buf = get_log_buffer()

        async def event_stream():
            if buf is None:
                return
            last_seq = buf.sequence
            connected_payload = json.dumps(
                {"connected": True, "buffered": len(buf.get_entries(tail=0))},
                ensure_ascii=False,
            )
            yield f"data: {connected_payload}\n\n"
            event_count = 1
            if max_events > 0 and event_count >= max_events:
                return
            while True:
                if await request.is_disconnected():
                    break
                new_entries = buf.get_entries_since(last_seq)
                if new_entries:
                    for entry in new_entries:
                        payload = json.dumps(entry, ensure_ascii=False)
                        yield f"data: {payload}\n\n"
                        event_count += 1
                        seq_val = int(entry["seq"])
                        if seq_val > last_seq:
                            last_seq = seq_val
                        if max_events > 0 and event_count >= max_events:
                            return
                else:
                    has_new = await asyncio.to_thread(buf.wait_for_new, 2.0)
                    if not has_new:
                        yield ": keepalive\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.post("/api/radarr/test")
    def test_radarr_connection(payload: ArrConnectionRequest) -> dict[str, Any]:
        safe_url = _safe_log_url(payload.url)
        LOG.info("Testing Radarr connection to %s", safe_url)
        client = RadarrClient(payload.url, payload.api_key)
        try:
            status = client.get_system_status()
            version = status.get("version") if isinstance(status, dict) else None
            suffix = f" (version={version})" if isinstance(version, str) and version else ""
            LOG.info("Radarr connection test succeeded: %s%s", safe_url, suffix)
            return {"ok": True, "message": f"Connected to Radarr{suffix}."}
        except Exception as exc:
            LOG.error("Radarr connection test failed for %s: %s", safe_url, exc)
            return {"ok": False, "message": str(exc)}

    @router.post("/api/sonarr/test")
    def test_sonarr_connection(payload: ArrConnectionRequest) -> dict[str, Any]:
        safe_url = _safe_log_url(payload.url)
        LOG.info("Testing Sonarr connection to %s", safe_url)
        client = SonarrClient(payload.url, payload.api_key)
        try:
            status = client.get_system_status()
            version = status.get("version") if isinstance(status, dict) else None
            suffix = f" (version={version})" if isinstance(version, str) and version else ""
            LOG.info("Sonarr connection test succeeded: %s%s", safe_url, suffix)
            return {"ok": True, "message": f"Connected to Sonarr{suffix}."}
        except Exception as exc:
            LOG.error("Sonarr connection test failed for %s: %s", safe_url, exc)
            return {"ok": False, "message": str(exc)}

    @router.post("/api/maintenance/reconcile")
    def run_maintenance_reconcile(request: Request) -> dict[str, Any]:
        LOG.info("Manual reconcile queued via API")
        manager = _job_manager_or_http(request)
        config_path = _read_config_path(request)

        def action() -> dict[str, Any]:
            config = _load_config_or_http(config_path)
            started = time.perf_counter()
            runtime_status.mark_reconcile_started(trigger_source="manual")
            try:
                service = LibrariArrService(config)
                ingest_pending = service.reconcile()
                duration_ms = int((time.perf_counter() - started) * 1000)
                runtime_status.mark_reconcile_finished(success=True, ingest_pending=ingest_pending)
                mapped_cache.request_refresh(config, force=True)
                LOG.info(
                    "Manual reconcile completed in %d ms (ingest_pending=%s)",
                    duration_ms,
                    ingest_pending,
                )
                return {
                    "ok": True,
                    "message": "Reconcile completed.",
                    "duration_ms": duration_ms,
                    "ingest_pending": ingest_pending,
                }
            except Exception as exc:
                runtime_status.mark_reconcile_finished(
                    success=False,
                    ingest_pending=False,
                    error=str(exc),
                )
                LOG.error("Manual reconcile failed: %s", exc)
                return {"ok": False, "message": str(exc)}

        job_id = manager.submit(kind="reconcile-manual", func=action)
        return {
            "ok": True,
            "queued": True,
            "job_id": job_id,
            "message": "Reconcile scheduled.",
        }

    @router.get("/api/jobs/summary")
    def jobs_summary(request: Request) -> dict[str, Any]:
        manager = _job_manager_or_http(request)
        return manager.summary()

    @router.get("/api/jobs")
    def jobs_list(
        request: Request,
        limit: int = Query(default=20, ge=1, le=200),
        status: str | None = Query(default=None),
    ) -> dict[str, Any]:
        manager = _job_manager_or_http(request)
        items = manager.list(limit=limit, status=status)
        return {"items": items}

    @router.get("/api/jobs/{job_id}")
    def jobs_get(job_id: str, request: Request) -> dict[str, Any]:
        manager = _job_manager_or_http(request)
        item = manager.get(job_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return item

    @router.post("/api/jobs/{job_id}/cancel")
    def jobs_cancel(job_id: str, request: Request) -> dict[str, Any]:
        manager = _job_manager_or_http(request)
        result = manager.cancel(job_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return result

    @router.get("/api/runtime/status")
    def runtime_status_endpoint(request: Request) -> dict[str, Any]:
        payload = runtime_status.snapshot()
        supervisor = getattr(request.app.state.web, "runtime_supervisor", None)
        payload["runtime_supervisor_present"] = supervisor is not None
        payload["runtime_supervisor_running"] = (
            bool(supervisor.is_running()) if supervisor is not None else False
        )
        return payload

    @router.get("/api/fs/mapped-directories")
    def mapped_directories(
        request: Request,
        search: str = Query(default=""),
        shadow_root: str | None = Query(default=None),
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> dict[str, Any]:
        config = _load_config_or_http(_read_config_path(request))
        all_roots = _shadow_roots(config)

        # Lazy fallback: only rescans when cache is uninitialised or >10 s stale.
        # In production the cache is kept fresh by reconcile-complete notifications,
        # so this almost never triggers an actual filesystem scan.
        mapped_cache.request_refresh(config)

        snapshot = mapped_cache.snapshot()
        if not snapshot["ready"] or snapshot["building"]:
            mapped_cache.wait_for_build(timeout=5.0)
            snapshot = mapped_cache.snapshot()

        if shadow_root is None:
            selected_roots = {str(root) for root in all_roots}
        else:
            selected_roots = {str(root) for root in all_roots if str(root) == shadow_root}
            if not selected_roots:
                raise HTTPException(status_code=400, detail="Unknown shadow_root filter value")

        lowered_search = search.strip().lower()
        items: list[dict[str, Any]] = []
        truncated = False

        for entry in snapshot["items"]:
            root_str = str(entry.get("shadow_root", ""))
            if root_str not in selected_roots:
                continue
            virtual_path = str(entry.get("virtual_path", ""))
            real_path = str(entry.get("real_path", ""))
            if (
                lowered_search
                and lowered_search not in virtual_path.lower()
                and lowered_search not in real_path.lower()
            ):
                continue
            items.append(entry)
            if len(items) >= limit:
                truncated = True
                break

        return {
            "items": items,
            "shadow_roots": [str(root) for root in all_roots],
            "truncated": truncated,
            "cache": {
                "ready": bool(snapshot["ready"]),
                "building": bool(snapshot["building"]),
                "updated_at_ms": snapshot["updated_at_ms"],
                "last_error": snapshot["last_error"],
                "entries_total": len(snapshot["items"]),
                "version": snapshot["version"],
            },
        }

    @router.get("/api/fs/discovery-warnings")
    def discovery_warnings(
        request: Request,
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> dict[str, Any]:
        config = _load_config_or_http(_read_config_path(request))
        return _build_discovery_warnings_payload(config=config, limit=limit)

    @router.post("/api/fs/mapped-directories/refresh")
    def refresh_mapped_directories(request: Request) -> dict[str, Any]:
        config = _load_config_or_http(_read_config_path(request))
        mapped_cache.request_refresh(config, force=True)
        mapped_cache.wait_for_build(timeout=10.0)
        snapshot = mapped_cache.snapshot()
        return {
            "ok": True,
            "cache": {
                "ready": bool(snapshot["ready"]),
                "building": bool(snapshot["building"]),
                "entries_total": len(snapshot["items"]),
                "version": snapshot["version"],
            },
        }

    @router.get("/api/fs/mapped-directories/stream")
    async def mapped_directories_stream(
        request: Request,
        interval_ms: int = Query(default=2000, ge=200, le=10000),
        max_events: int = Query(default=0, ge=0),
    ) -> StreamingResponse:
        async def event_stream():
            previous_version: int | None = None
            event_count = 0
            while True:
                if await request.is_disconnected():
                    break

                snapshot = mapped_cache.snapshot()
                current_version = int(snapshot["version"])
                changed = previous_version is not None and current_version != previous_version

                if previous_version is None or changed:
                    payload = {
                        "changed": changed,
                        "cache_ready": bool(snapshot["ready"]),
                        "cache_building": bool(snapshot["building"]),
                        "cache_entries_total": len(snapshot["items"]),
                        "timestamp_ms": int(time.time() * 1000),
                    }
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    event_count += 1
                    if max_events > 0 and event_count >= max_events:
                        break
                else:
                    yield ": keepalive\n\n"

                previous_version = current_version
                await asyncio.sleep(interval_ms / 1000)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router
