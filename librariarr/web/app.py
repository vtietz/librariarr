from __future__ import annotations

import fcntl
import hashlib
import io
import logging
import os
import threading
from collections.abc import Mapping, MutableMapping
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from ..clients.radarr import RadarrClient
from ..clients.sonarr import SonarrClient
from ..config import AppConfig, load_config
from ..quality import VIDEO_EXTENSIONS
from ..runtime import get_runtime_status_tracker
from ..service import LibrariArrService
from ..sync.discovery import discover_movie_folders, discover_series_folders
from .dashboard_read_model import DashboardReadModel
from .discovery_cache import get_discovery_warnings_cache, warmup_discovery_warnings_cache
from .jobs import JobManager
from .log_buffer import install_log_buffer
from .mapped_cache import get_mapped_directories_cache, warmup_mapped_directories_cache
from .operations import build_operations_router, run_radarr_diagnostics, run_sonarr_diagnostics
from .routers import (
    build_basic_fs_router,
    build_config_router,
    build_diagnostics_router,
    build_dry_run_router,
    build_hooks_router,
    build_metadata_router,
)
from .runtime_supervisor import RuntimeSupervisor
from .runtime_task_wiring import configure_runtime_task_callbacks
from .state_store import PersistentStateStore

LOG = logging.getLogger(__name__)


@dataclass
class WebState:
    config_path: Path
    lock: threading.RLock = field(default_factory=threading.RLock)
    draft_yaml: str | None = None
    runtime_supervisor: RuntimeSupervisor | None = None
    job_manager: JobManager | None = None
    state_store: PersistentStateStore | None = None
    dashboard_read_model: DashboardReadModel | None = None


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_disk_yaml(config_path: Path) -> str:
    return config_path.read_text(encoding="utf-8")


def _config_backup_path(config_path: Path) -> Path:
    return config_path.with_name(f"{config_path.name}.bak")


def _atomic_write(target: Path, content: str) -> None:
    fd = None
    tmp_path = None
    try:
        fd = NamedTemporaryFile(
            "w",
            dir=str(target.parent),
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        )
        tmp_path = Path(fd.name)
        fd.write(content)
        fd.flush()
        os.fsync(fd.fileno())
        fd.close()
        fd = None
        os.replace(str(tmp_path), str(target))
        tmp_path = None
    finally:
        if fd is not None:
            fd.close()
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def _write_config_with_backup(config_path: Path, previous_yaml: str, next_yaml: str) -> None:
    backup_path = _config_backup_path(config_path)
    _atomic_write(backup_path, previous_yaml)
    _atomic_write(config_path, next_yaml)


def _is_permission_error(exc: OSError) -> bool:
    return isinstance(exc, PermissionError)


def _redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, nested in value.items():
            if "api_key" in key.lower():
                out[key] = "***redacted***"
                continue
            out[key] = _redact_secrets(nested)
        return out
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


def _serialize_config(config: AppConfig, include_secrets: bool) -> dict[str, Any]:
    payload = asdict(config)
    if include_secrets:
        return payload
    return _redact_secrets(payload)


def _validate_yaml_text(yaml_text: str) -> tuple[AppConfig | None, str | None]:
    temp_path: Path | None = None
    try:
        with NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as handle:
            handle.write(yaml_text)
            temp_path = Path(handle.name)
        config = load_config(temp_path)
        return config, None
    except Exception as exc:
        return None, str(exc)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _merge_mapping(base: MutableMapping[str, Any], update: Mapping[str, Any]) -> None:
    for key, value in update.items():
        current = base.get(key)
        if isinstance(current, MutableMapping) and isinstance(value, Mapping):
            _merge_mapping(current, value)
            continue
        base[key] = value


def _quote_string_scalars(node: Any) -> Any:
    if isinstance(node, str):
        return DoubleQuotedScalarString(node)
    if isinstance(node, MutableMapping):
        for key, value in list(node.items()):
            node[key] = _quote_string_scalars(value)
        return node
    if isinstance(node, list):
        for index, value in enumerate(node):
            node[index] = _quote_string_scalars(value)
        return node
    return node


def _to_yaml_text(payload: Any, base_yaml_text: str) -> str:
    if payload.yaml is not None:
        return payload.yaml
    if payload.config is None:
        raise ValueError("Request must include either 'yaml' or 'config'.")

    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    yaml_rt.indent(mapping=2, sequence=4, offset=2)
    document = yaml_rt.load(base_yaml_text)
    if document is None:
        document = CommentedMap()
    if not isinstance(document, MutableMapping):
        raise ValueError("Existing config document must be a YAML mapping.")

    _merge_mapping(document, payload.config)
    _quote_string_scalars(document)
    out = io.StringIO()
    yaml_rt.dump(document, out)
    return out.getvalue()


def _allowed_roots(config: AppConfig) -> list[Path]:
    roots: set[Path] = set()
    for mapping in config.paths.series_root_mappings:
        roots.add(Path(mapping.nested_root))
        roots.add(Path(mapping.shadow_root))
    for mapping in config.paths.movie_root_mappings:
        roots.add(Path(mapping.managed_root))
        roots.add(Path(mapping.library_root))
    return sorted(roots)


def _is_allowed_path(candidate: Path, allowed_roots: list[Path]) -> bool:
    resolved_candidate = candidate.resolve(strict=False)
    for root in allowed_roots:
        resolved_root = root.resolve(strict=False)
        if resolved_candidate == resolved_root:
            return True
        if resolved_candidate.is_relative_to(resolved_root):
            return True
    return False


def _safe_load_disk_config(config_path: Path) -> AppConfig:
    try:
        return load_config(config_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unable to load config: {exc}") from exc


def _job_manager_or_http(state: WebState) -> JobManager:
    manager = state.job_manager
    if manager is None:
        raise HTTPException(status_code=503, detail="Job manager is unavailable.")
    return manager


def _default_state_path(config_path: Path) -> Path:
    configured = str(os.getenv("LIBRARIARR_STATE_PATH", "")).strip()
    if configured:
        return Path(configured)
    return config_path.with_name("librariarr-state.json")


def _runtime_lock_path() -> Path:
    configured = str(os.getenv("LIBRARIARR_RUNTIME_LOCK_PATH", "")).strip()
    if configured:
        return Path(configured)
    return Path("/tmp/librariarr_runtime.lock")


def _try_acquire_runtime_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None

    handle.seek(0)
    handle.truncate(0)
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    return handle


def _release_runtime_lock(lock_handle) -> None:
    if lock_handle is None:
        return
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    lock_handle.close()


def create_app(  # noqa: C901
    *,
    config_path: str | Path | None = None,
    ui_dist_path: str | Path | None = None,
    runtime_supervisor: RuntimeSupervisor | None = None,
    run_runtime_loop: bool = True,
) -> FastAPI:
    if config_path is None:
        config_path = os.getenv("LIBRARIARR_CONFIG_PATH", "/config/config.yaml")

    config_path = Path(config_path)
    state_store = PersistentStateStore(_default_state_path(config_path))
    job_manager = JobManager(state_store=state_store)
    runtime_status_tracker = get_runtime_status_tracker()
    mapped_cache = get_mapped_directories_cache()
    discovery_cache = get_discovery_warnings_cache()
    mapped_cache.attach_state(state_store=state_store, task_manager=job_manager)
    discovery_cache.attach_state(state_store=state_store, task_manager=job_manager)
    configure_runtime_task_callbacks(
        runtime_status_tracker=runtime_status_tracker,
        job_manager=job_manager,
    )
    dashboard_read_model = DashboardReadModel(
        runtime_status_tracker=runtime_status_tracker,
        job_manager=job_manager,
        mapped_cache=mapped_cache,
        discovery_cache=discovery_cache,
        state_store=state_store,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        runtime_thread = None
        runtime_stop_event = None
        runtime_lock_handle = None
        LOG.info("LibrariArr web app starting (config=%s)", config_path)
        job_manager.start()
        warmup_mapped_directories_cache(config_path)
        warmup_discovery_warnings_cache(config_path)
        dashboard_read_model.start()
        dashboard_read_model.refresh_now()

        if run_runtime_loop:
            lock_path = _runtime_lock_path()
            runtime_lock_handle = _try_acquire_runtime_lock(lock_path)
            _app.state.runtime_lock_path = str(lock_path)
            _app.state.runtime_lock_acquired = runtime_lock_handle is not None
            _app.state.runtime_lock_handle = runtime_lock_handle

            if runtime_lock_handle is not None:
                try:
                    LOG.info("Loading config and initializing runtime...")
                    runtime_config = load_config(config_path)
                    service = LibrariArrService(runtime_config)
                    runtime_stop_event = threading.Event()
                    runtime_thread = threading.Thread(
                        target=service.run,
                        kwargs={"stop_event": runtime_stop_event},
                        daemon=True,
                        name="librariarr-runtime-sync",
                    )
                    runtime_thread.start()
                    _app.state.runtime = runtime_thread
                    _app.state.runtime_stop_event = runtime_stop_event
                    LOG.info("Started runtime loop in active API worker")
                except Exception:
                    LOG.exception("Failed to start background runtime loop")
            else:
                LOG.info("Skipped runtime loop startup in this worker (runtime lock already held)")

        try:
            yield
        finally:
            stop_event = getattr(_app.state, "runtime_stop_event", None)
            thread = getattr(_app.state, "runtime", None)
            if isinstance(stop_event, threading.Event):
                stop_event.set()
            if isinstance(thread, threading.Thread) and thread.is_alive():
                thread.join(timeout=30)
            _release_runtime_lock(getattr(_app.state, "runtime_lock_handle", None))
            _app.state.runtime = None
            _app.state.runtime_stop_event = None
            _app.state.runtime_lock_handle = None
            dashboard_read_model.stop()
            job_manager.stop()

    app = FastAPI(title="LibrariArr Web API", version="0.1.0", lifespan=lifespan)
    install_log_buffer()
    state = WebState(
        config_path=config_path,
        runtime_supervisor=runtime_supervisor,
        job_manager=job_manager,
        state_store=state_store,
        dashboard_read_model=dashboard_read_model,
    )
    app.state.web = state
    app.state.job_manager = job_manager
    app.state.runtime_status = runtime_status_tracker
    app.state.runtime = None
    app.state.runtime_stop_event = None
    app.state.runtime_lock_handle = None
    app.state.runtime_lock_path = str(_runtime_lock_path())
    app.state.runtime_lock_acquired = False
    app.include_router(build_operations_router())
    app.include_router(build_hooks_router())

    if ui_dist_path is None:
        ui_dist_path = os.getenv("LIBRARIARR_UI_DIST", "/app/ui/dist")
    dist_dir = Path(ui_dist_path)
    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        snapshot = state.dashboard_read_model.snapshot() if state.dashboard_read_model else None
        if (
            isinstance(snapshot, dict)
            and snapshot.get("updated_at") is None
            and state.dashboard_read_model
        ):
            snapshot = state.dashboard_read_model.refresh_now()
        health_payload = snapshot.get("health") if isinstance(snapshot, dict) else None
        if not isinstance(health_payload, dict):
            return {"status": "starting"}
        return health_payload

    app.include_router(
        build_config_router(
            state=state,
            load_disk_yaml_fn=_load_disk_yaml,
            validate_yaml_text_fn=_validate_yaml_text,
            to_yaml_text_fn=_to_yaml_text,
            checksum_fn=_checksum,
            serialize_config_fn=_serialize_config,
            write_config_with_backup_fn=_write_config_with_backup,
            is_permission_error_fn=_is_permission_error,
            logger=LOG,
        )
    )
    app.include_router(
        build_basic_fs_router(
            state=state,
            safe_load_disk_config_fn=_safe_load_disk_config,
            allowed_roots_fn=_allowed_roots,
            is_allowed_path_fn=_is_allowed_path,
        )
    )
    app.include_router(
        build_metadata_router(
            state=state,
            safe_load_disk_config_fn=_safe_load_disk_config,
            logger=LOG,
            radarr_client_cls=RadarrClient,
            sonarr_client_cls=SonarrClient,
        )
    )
    app.include_router(
        build_diagnostics_router(
            state=state,
            job_manager_or_http_fn=_job_manager_or_http,
            safe_load_disk_config_fn=_safe_load_disk_config,
            run_radarr_diagnostics_fn=run_radarr_diagnostics,
            run_sonarr_diagnostics_fn=run_sonarr_diagnostics,
            logger=LOG,
        )
    )
    app.include_router(
        build_dry_run_router(
            state=state,
            job_manager_or_http_fn=_job_manager_or_http,
            safe_load_disk_config_fn=_safe_load_disk_config,
            validate_yaml_text_fn=_validate_yaml_text,
            discover_movie_folders_fn=discover_movie_folders,
            discover_series_folders_fn=discover_series_folders,
            video_extensions=VIDEO_EXTENSIONS,
        )
    )

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
            target = base if not full_path else f"{base}/{full_path}"
            return RedirectResponse(url=target, status_code=307)

        return JSONResponse(
            status_code=503,
            content={
                "message": "Frontend assets are not built yet.",
                "hint": "Build the UI and ensure LIBRARIARR_UI_DIST points to the dist directory.",
            },
        )

    return app


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
