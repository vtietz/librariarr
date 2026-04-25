from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import Request

from ..service import LibrariArrService
from ..service.constants import RECONCILE_TASK_FULL_MANUAL_KEY
from .request_helpers import job_manager_or_http, load_config_or_http, read_config_path

LOG = logging.getLogger(__name__)


def queue_full_reconcile(
    *,
    request: Request,
    runtime_status,
    mapped_cache,
    discovery_cache,
) -> dict[str, Any]:
    LOG.info("Full Reconcile queued via API")
    manager = job_manager_or_http(request)
    config_path = read_config_path(request)

    def action() -> dict[str, Any]:
        config = load_config_or_http(config_path)
        started = time.perf_counter()
        runtime_status.mark_reconcile_started(trigger_source="manual", phase="full_reconcile")
        try:
            service = LibrariArrService(config)
            had_error = service.reconcile_full()
            duration_ms = int((time.perf_counter() - started) * 1000)
            runtime_status.mark_reconcile_finished(
                success=not had_error,
                followup_pending=False,
            )
            mapped_cache.request_refresh(config, force=True)
            mapped_cache.wait_for_build(timeout=5.0)
            discovery_cache.request_refresh(config, force=True)
            LOG.info("Full Reconcile completed in %d ms (had_error=%s)", duration_ms, had_error)
            return {
                "ok": True,
                "message": "Full Reconcile completed.",
                "duration_ms": duration_ms,
                "had_error": had_error,
            }
        except Exception as exc:
            runtime_status.mark_reconcile_finished(
                success=False,
                followup_pending=False,
                error=str(exc),
            )
            LOG.error("Full Reconcile failed: %s", exc)
            return {"ok": False, "message": str(exc)}

    job_id = manager.submit(
        kind="reconcile-full",
        name="Full Reconcile",
        source="job-manager",
        detail="queued",
        func=action,
        task_key=RECONCILE_TASK_FULL_MANUAL_KEY,
    )
    return {
        "ok": True,
        "queued": True,
        "job_id": job_id,
        "message": "Full Reconcile scheduled.",
    }
