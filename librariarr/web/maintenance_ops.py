from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from ..service import LibrariArrService
from ..service.constants import RECONCILE_TASK_FULL_KEY, RECONCILE_TASK_INCREMENTAL_KEY
from .path_mapping_status import build_path_mapping_outcome, record_path_mapping_outcome
from .request_helpers import job_manager_or_http, load_config_or_http, read_config_path

LOG = logging.getLogger(__name__)


def queue_maintenance_reconcile(
    *,
    request: Request,
    path: str | None,
    runtime_status,
    mapped_cache,
    discovery_cache,
) -> dict[str, Any]:
    LOG.info("Manual reconcile queued via API")
    manager = job_manager_or_http(request)
    config_path = read_config_path(request)
    state_store = getattr(request.app.state.web, "state_store", None)
    path_value = path.strip() if isinstance(path, str) else ""
    affected_paths: set[Path] | None = None
    if path_value:
        candidate_path = Path(path_value)
        if not candidate_path.is_absolute():
            raise HTTPException(status_code=400, detail="path must be an absolute path")
        affected_paths = {candidate_path}

    def action() -> dict[str, Any]:
        config = load_config_or_http(config_path)
        started = time.perf_counter()
        runtime_status.mark_reconcile_started(trigger_source="manual")
        try:
            service = LibrariArrService(config)
            followup_pending = service.reconcile(
                affected_paths=affected_paths,
                refresh_arr_root_availability=affected_paths is None,
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            runtime_status.mark_reconcile_finished(
                success=True,
                followup_pending=followup_pending,
            )
            if affected_paths is None:
                mapped_cache.request_refresh(config, force=True)
                mapped_cache.wait_for_build(timeout=5.0)
                discovery_cache.request_refresh(config, force=True)
            else:
                mapped_cache.request_refresh(config, force=False)
                discovery_cache.request_refresh(config, force=False)
            path_outcome = None
            if path_value:
                path_outcome = build_path_mapping_outcome(
                    real_path=path_value,
                    config=config,
                    mapped_cache=mapped_cache,
                )
                record_path_mapping_outcome(
                    state_store=state_store,
                    real_path=path_value,
                    outcome=path_outcome,
                )
            LOG.info(
                "Manual reconcile completed in %d ms (followup_pending=%s, scoped=%s)",
                duration_ms,
                followup_pending,
                bool(affected_paths),
            )
            return {
                "ok": True,
                "message": "Reconcile completed.",
                "duration_ms": duration_ms,
                "followup_pending": followup_pending,
                "scoped": bool(affected_paths),
                "path_outcome": path_outcome,
            }
        except Exception as exc:
            runtime_status.mark_reconcile_finished(
                success=False,
                followup_pending=False,
                error=str(exc),
            )
            if path_value:
                record_path_mapping_outcome(
                    state_store=state_store,
                    real_path=path_value,
                    outcome={
                        "status": "reconcile_failed",
                        "arr": "none",
                        "message": str(exc),
                        "movie_id": None,
                        "series_id": None,
                    },
                )
            LOG.error("Manual reconcile failed: %s", exc)
            return {"ok": False, "message": str(exc)}

    task_key = RECONCILE_TASK_INCREMENTAL_KEY if affected_paths else RECONCILE_TASK_FULL_KEY
    job_id = manager.submit(
        kind="reconcile-manual-scoped" if affected_paths else "reconcile-manual",
        name="Manual Reconcile (Scoped)" if affected_paths else "Manual Reconcile",
        source="job-manager",
        detail="queued",
        func=action,
        payload={"path": path_value} if path_value else None,
        task_key=task_key,
    )
    return {
        "ok": True,
        "queued": True,
        "job_id": job_id,
        "message": "Reconcile scheduled.",
    }
