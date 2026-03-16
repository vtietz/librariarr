from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Request

from ..clients.radarr import RadarrClient
from ..clients.sonarr import SonarrClient
from ..config import AppConfig
from ..runtime import get_runtime_status_tracker
from .discovery_cache import get_discovery_warnings_cache
from .log_buffer import LogRingBuffer, get_log_buffer
from .maintenance_ops import queue_maintenance_reconcile
from .mapped_arr_state import enrich_mapped_directories_with_radarr_state
from .mapped_cache import get_mapped_directories_cache
from .mapped_cache import shadow_roots as _shadow_roots
from .path_mapping_status import apply_path_mapping_outcomes
from .request_helpers import job_manager_or_http, load_config_or_http, read_config_path
from .routers import (
    build_arr_router,
    build_fs_router,
    build_jobs_router,
    build_logs_router,
    build_maintenance_router,
    build_runtime_router,
)

LOG = logging.getLogger(__name__)

LOGS_STREAM_REPLAY_TAIL = 100
LOGS_STREAM_WAIT_SECONDS = 0.3
LOGS_STREAM_HEARTBEAT_SECONDS = 15.0


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


def _sse_data(payload: Any) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _drain_log_entries(
    entries: list[dict[str, str]],
    *,
    last_seq: int,
    event_count: int,
    max_events: int,
) -> tuple[list[str], int, int, bool]:
    events: list[str] = []
    for entry in entries:
        events.append(_sse_data(entry))
        event_count += 1
        seq_val = int(entry["seq"])
        if seq_val > last_seq:
            last_seq = seq_val
        if max_events > 0 and event_count >= max_events:
            return events, last_seq, event_count, True
    return events, last_seq, event_count, False


async def _iter_logs_stream_events(
    *,
    request: Request,
    buf: LogRingBuffer,
    max_events: int,
):
    connected_sent_at = time.perf_counter()
    last_seq = 0
    yield _sse_data({"connected": True, "buffered": len(buf.get_entries(tail=0))})
    LOG.debug(
        "Logs SSE connected marker sent in %.3f ms",
        (time.perf_counter() - connected_sent_at) * 1000,
    )

    event_count = 1
    if max_events > 0 and event_count >= max_events:
        return

    replay_entries = buf.get_entries(tail=LOGS_STREAM_REPLAY_TAIL)
    replay_events, last_seq, event_count, replay_limit_reached = _drain_log_entries(
        replay_entries,
        last_seq=last_seq,
        event_count=event_count,
        max_events=max_events,
    )
    for event in replay_events:
        yield event
    if replay_limit_reached:
        return

    if replay_entries:
        LOG.debug("Logs SSE replayed %d buffered entries", len(replay_entries))

    last_heartbeat = time.monotonic()
    while True:
        if await request.is_disconnected():
            break

        new_entries = buf.get_entries_since(last_seq)
        if new_entries:
            events, last_seq, event_count, limit_reached = _drain_log_entries(
                new_entries,
                last_seq=last_seq,
                event_count=event_count,
                max_events=max_events,
            )
            for event in events:
                yield event
            if limit_reached:
                return
            last_heartbeat = time.monotonic()
            continue

        has_new = await asyncio.to_thread(buf.wait_for_new, LOGS_STREAM_WAIT_SECONDS)
        if not has_new and (time.monotonic() - last_heartbeat >= LOGS_STREAM_HEARTBEAT_SECONDS):
            yield ": ping\n\n"
            last_heartbeat = time.monotonic()


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


def build_operations_router() -> APIRouter:
    router = APIRouter()
    runtime_status = get_runtime_status_tracker()
    mapped_cache = get_mapped_directories_cache()
    discovery_cache = get_discovery_warnings_cache()

    router.include_router(
        build_logs_router(
            get_log_buffer_fn=get_log_buffer,
            iter_logs_stream_events=_iter_logs_stream_events,
        )
    )
    router.include_router(
        build_arr_router(
            logger=LOG,
            safe_log_url_fn=_safe_log_url,
            radarr_client_cls=RadarrClient,
            sonarr_client_cls=SonarrClient,
            load_config_or_http_fn=load_config_or_http,
            read_config_path_fn=read_config_path,
        )
    )
    router.include_router(
        build_maintenance_router(
            queue_maintenance_reconcile_fn=queue_maintenance_reconcile,
            runtime_status=runtime_status,
            mapped_cache=mapped_cache,
            discovery_cache=discovery_cache,
        )
    )
    router.include_router(build_jobs_router(job_manager_or_http_fn=job_manager_or_http))
    router.include_router(build_runtime_router(runtime_status=runtime_status))
    router.include_router(
        build_fs_router(
            load_config_or_http_fn=load_config_or_http,
            read_config_path_fn=read_config_path,
            job_manager_or_http_fn=job_manager_or_http,
            mapped_cache=mapped_cache,
            discovery_cache=discovery_cache,
            shadow_roots_fn=_shadow_roots,
            enrich_mapped_directories_with_radarr_state_fn=enrich_mapped_directories_with_radarr_state,
            apply_path_mapping_outcomes_fn=apply_path_mapping_outcomes,
        )
    )

    return router
