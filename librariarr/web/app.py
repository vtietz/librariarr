"""Slim FastAPI app: status, reconcile trigger, unmatched report, config, logs, hooks.

The Arr UIs are the primary interaction surface; this API exposes just enough
for the dashboard: what is the runtime doing, what could not be matched, and
the raw YAML config with validation.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import load_config
from ..core.engine import SCOPE_CONSISTENCY, SCOPE_FULL, SCOPE_TARGETED, SCOPES
from ..core.status import get_status_tracker
from ..runtime.loop import RuntimeLoop
from ..service import LibrariArrService
from .log_buffer import get_log_buffer, install_log_buffer

LOG = logging.getLogger(__name__)


@dataclass
class WebState:
    config_path: Path
    service: LibrariArrService | None = None
    runtime_loop: RuntimeLoop | None = None
    runtime_thread: threading.Thread | None = None
    stop_event: threading.Event | None = None


class ConfigPayload(BaseModel):
    yaml: str


class ReconcileRequest(BaseModel):
    scope: str = SCOPE_FULL
    dry_run: bool = False
    # Only meaningful for scope="targeted": the Arr items to reconcile. No
    # paths, files or inodes are accepted from clients — everything else is read
    # fresh from the Arr APIs and the filesystem.
    radarr_movie_ids: list[int] = []
    sonarr_series_ids: list[int] = []


class ManualAddRequest(BaseModel):
    path: str


# Webhook events that describe no library change, so they keep triggering the
# global consistency pass instead of a targeted one (a Radarr test payload
# carries a dummy movie id, which must not be mistaken for real work).
_NON_ITEM_EVENT_TYPES = frozenset({"test", "health", "healthissue", "healthrestored"})

_MAX_TARGETED_IDS = 200


def _clean_item_ids(raw: list[int]) -> list[int]:
    return sorted({int(item_id) for item_id in raw if isinstance(item_id, int) and item_id > 0})


def _webhook_item_id(payload: dict | None, key: str) -> int | None:
    """The Arr item id a webhook payload names, if any.

    The payload is treated as a hint only: the id is all that is taken from it,
    and the item is then read fresh from the Arr API.
    """
    event_type = str((payload or {}).get("eventType", "")).strip().lower()
    if event_type in _NON_ITEM_EVENT_TYPES:
        return None
    item = (payload or {}).get(key)
    if not isinstance(item, dict):
        return None
    raw = item.get("id")
    if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
        return None
    return int(raw)


def _validate_yaml_text(yaml_text: str) -> str | None:
    temp_path: Path | None = None
    try:
        with NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as handle:
            handle.write(yaml_text)
            temp_path = Path(handle.name)
        load_config(temp_path)
        return None
    except Exception as exc:  # noqa: BLE001 - any parse/validation error is user-facing
        return str(exc)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _validate_webhook_secret(header_value: str | None) -> None:
    expected = str(os.getenv("LIBRARIARR_WEBHOOK_SECRET", "")).strip()
    if expected and header_value != expected:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


def _start_runtime(state: WebState) -> None:
    config = load_config(state.config_path)
    service = LibrariArrService(config, config_path=state.config_path)
    state.service = service
    state.runtime_loop = RuntimeLoop(
        service, config.runtime, schedule_state_path=service.schedule_state_path
    )
    state.stop_event = threading.Event()
    state.runtime_thread = threading.Thread(
        target=state.runtime_loop.run,
        args=(state.stop_event,),
        daemon=True,
        name="librariarr-runtime",
    )
    state.runtime_thread.start()
    LOG.info("Runtime loop started")


def _service_or_http(state: WebState) -> LibrariArrService:
    if state.service is None:
        try:
            config = load_config(state.config_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Unable to load config: {exc}") from exc
        state.service = LibrariArrService(config, config_path=state.config_path)
    return state.service


def create_app(
    *,
    config_path: str | Path | None = None,
    ui_dist_path: str | Path | None = None,
    run_runtime_loop: bool = True,
) -> FastAPI:
    if config_path is None:
        config_path = os.getenv("LIBRARIARR_CONFIG_PATH", "/config/config.yaml")
    state = WebState(config_path=Path(config_path))
    install_log_buffer()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if run_runtime_loop:
            try:
                _start_runtime(state)
            except Exception:
                LOG.exception("Failed to start runtime loop; API stays available")
        try:
            yield
        finally:
            if state.stop_event is not None:
                state.stop_event.set()
            if state.runtime_thread is not None and state.runtime_thread.is_alive():
                state.runtime_thread.join(timeout=30)

    app = FastAPI(title="LibrariArr Web API", version="2.0.0", lifespan=lifespan)
    app.state.web = state
    _add_status_routes(app, state)
    _add_reconcile_routes(app, state)
    _add_config_routes(app, state)
    _add_ui_routes(app, ui_dist_path)
    return app


def _add_status_routes(app: FastAPI, state: WebState) -> None:
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok"}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        snapshot = get_status_tracker().snapshot()
        snapshot["runtime_loop_active"] = (
            state.runtime_thread is not None and state.runtime_thread.is_alive()
        )
        return snapshot

    @app.get("/api/unmatched")
    def unmatched() -> dict[str, Any]:
        # Discovery only runs during full passes; a consistency pass must not
        # make previously-found unmatched folders disappear from the UI.
        snapshot = get_status_tracker().snapshot()
        full_report = snapshot.get("last_full_report") or {}
        return {
            "unmatched": full_report.get("unmatched", []),
            "as_of": snapshot.get("last_full_finished_at"),
        }

    @app.post("/api/unmatched/add")
    def unmatched_add(payload: ManualAddRequest) -> dict[str, Any]:
        service = _service_or_http(state)
        return service.manual_add(payload.path)

    @app.get("/api/path-differences")
    def path_differences() -> dict[str, Any]:
        # Arr never rewrites its own path on a managed-tree rename (by
        # design); this surfaces the expected mismatch instead of leaving it
        # to look like a bug.
        service = _service_or_http(state)
        return {"differences": service.list_path_differences()}

    @app.get("/api/logs")
    def logs(limit: int = 200) -> dict[str, Any]:
        buffer = get_log_buffer()
        if buffer is None:
            return {"entries": []}
        return {"entries": buffer.get_entries(tail=max(1, min(limit, 2000)))}


def _validated_reconcile_ids(request: ReconcileRequest) -> tuple[list[int], list[int]]:
    """Item ids for a reconcile request; only scope 'targeted' requires any."""
    movie_ids = _clean_item_ids(request.radarr_movie_ids)
    series_ids = _clean_item_ids(request.sonarr_series_ids)
    if request.scope != SCOPE_TARGETED:
        return movie_ids, series_ids
    if not movie_ids and not series_ids:
        raise HTTPException(
            status_code=400,
            detail="scope 'targeted' needs radarr_movie_ids and/or sonarr_series_ids "
            "(positive integers)",
        )
    if len(movie_ids) + len(series_ids) > _MAX_TARGETED_IDS:
        raise HTTPException(
            status_code=400,
            detail=f"at most {_MAX_TARGETED_IDS} ids per targeted reconcile; "
            "use scope 'full' for library-wide work",
        )
    return movie_ids, series_ids


def _queue_on_loop(loop, scope: str, movie_ids: list[int], series_ids: list[int]) -> None:
    if scope == SCOPE_FULL:
        loop.trigger_full("api")
    elif scope == SCOPE_TARGETED:
        loop.trigger_targeted("api", movie_ids=movie_ids, series_ids=series_ids)
    else:
        loop.trigger_consistency("api")


def _add_reconcile_routes(app: FastAPI, state: WebState) -> None:
    @app.post("/api/reconcile")
    def reconcile(request: ReconcileRequest) -> dict[str, Any]:
        if request.scope not in SCOPES:
            raise HTTPException(
                status_code=400, detail=f"scope must be one of: {', '.join(SCOPES)}"
            )
        movie_ids, series_ids = _validated_reconcile_ids(request)
        service = _service_or_http(state)
        if request.dry_run:
            report = service.reconcile(
                scope=request.scope,
                dry_run=True,
                radarr_movie_ids=movie_ids,
                sonarr_series_ids=series_ids,
            )
            return {"ok": True, "report": report.to_dict()}
        if state.runtime_loop is not None:
            _queue_on_loop(state.runtime_loop, request.scope, movie_ids, series_ids)
            return {"ok": True, "queued": True}
        report = service.reconcile(
            scope=request.scope,
            radarr_movie_ids=movie_ids,
            sonarr_series_ids=series_ids,
        )
        return {"ok": True, "report": report.to_dict()}

    @app.get("/api/bucket-drift")
    def bucket_drift() -> dict[str, Any]:
        # Read-only. An Arr root-folder reassignment reaches us through no
        # webhook (see ReconcileEngine.list_bucket_drift), so the UI polls this
        # and can hand the ids straight to a targeted reconcile.
        service = _service_or_http(state)
        return {"drift": service.list_bucket_drift()}

    @app.post("/api/hooks/radarr")
    def radarr_hook(
        payload: dict | None = None,
        x_librariarr_webhook_secret: str | None = Header(default=None),
    ) -> dict[str, Any]:
        return _handle_arr_hook(state, payload, x_librariarr_webhook_secret, "movie")

    @app.post("/api/hooks/sonarr")
    def sonarr_hook(
        payload: dict | None = None,
        x_librariarr_webhook_secret: str | None = Header(default=None),
    ) -> dict[str, Any]:
        return _handle_arr_hook(state, payload, x_librariarr_webhook_secret, "series")


def _handle_arr_hook(
    state: WebState, payload: dict | None, secret: str | None, item_key: str
) -> dict[str, Any]:
    """Queue work for one webhook.

    When the payload names an item, only that item is reconciled — that is what
    keeps an import from costing a pass over the whole library. Anything without
    a usable id falls back to the global consistency pass, exactly as before.
    """
    _validate_webhook_secret(secret)
    event_type = str((payload or {}).get("eventType", "")).strip()
    if state.runtime_loop is None:
        return {"ok": True, "queued": False, "reason": "runtime loop not active"}
    item_id = _webhook_item_id(payload, item_key)
    reason = f"webhook:{event_type or 'unknown'}"
    if item_id is None:
        state.runtime_loop.trigger_consistency(reason)
        return {
            "ok": True,
            "queued": True,
            "scope": SCOPE_CONSISTENCY,
            "event_type": event_type or None,
        }
    if item_key == "movie":
        state.runtime_loop.trigger_targeted(reason, movie_ids=[item_id])
    else:
        state.runtime_loop.trigger_targeted(reason, series_ids=[item_id])
    return {
        "ok": True,
        "queued": True,
        "scope": SCOPE_TARGETED,
        "event_type": event_type or None,
        "item_id": item_id,
    }


def _add_config_routes(app: FastAPI, state: WebState) -> None:
    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        try:
            return {"yaml": state.config_path.read_text(encoding="utf-8")}
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.put("/api/config")
    def put_config(payload: ConfigPayload) -> dict[str, Any]:
        error = _validate_yaml_text(payload.yaml)
        if error is not None:
            raise HTTPException(status_code=422, detail=error)
        backup = state.config_path.with_name(f"{state.config_path.name}.bak")
        try:
            if state.config_path.exists():
                backup.write_text(state.config_path.read_text(encoding="utf-8"), encoding="utf-8")
            state.config_path.write_text(payload.yaml, encoding="utf-8")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        # A changed config takes effect for ad-hoc runs immediately; the
        # background loop picks it up on restart.
        state.service = None
        return {"ok": True, "note": "Restart the container to apply changes to the runtime loop."}

    @app.post("/api/config/validate")
    def validate_config(payload: ConfigPayload) -> dict[str, Any]:
        error = _validate_yaml_text(payload.yaml)
        return {"valid": error is None, "error": error}


def _add_ui_routes(app: FastAPI, ui_dist_path: str | Path | None) -> None:
    if ui_dist_path is None:
        ui_dist_path = os.getenv("LIBRARIARR_UI_DIST", "/app/ui/dist")
    dist_dir = Path(ui_dist_path)
    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        index_path = dist_dir / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        ui_dev_url = str(os.getenv("LIBRARIARR_UI_DEV_URL", "")).strip()
        if ui_dev_url:
            base = ui_dev_url.rstrip("/")
            return RedirectResponse(
                url=base if not full_path else f"{base}/{full_path}", status_code=307
            )
        return JSONResponse(
            status_code=503,
            content={"message": "Frontend assets are not built yet."},
        )


def run_web_app(
    *,
    config_path: str,
    host: str,
    port: int,
    log_level: str,
    run_runtime_loop: bool = True,
) -> None:
    app = create_app(config_path=config_path, run_runtime_loop=run_runtime_loop)
    uvicorn.run(app, host=host, port=port, log_level=log_level.lower())
