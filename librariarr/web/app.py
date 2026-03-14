from __future__ import annotations

import difflib
import hashlib
import io
import logging
import os
import threading
from collections.abc import Mapping, MutableMapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from ..clients.radarr import RadarrClient
from ..clients.sonarr import SonarrClient
from ..config import AppConfig, load_config
from ..quality import VIDEO_EXTENSIONS
from ..sync.discovery import discover_movie_folders, discover_series_folders
from .jobs import JobManager
from .log_buffer import install_log_buffer
from .operations import build_operations_router, run_radarr_diagnostics, run_sonarr_diagnostics
from .runtime_supervisor import RuntimeSupervisor

LOG = logging.getLogger(__name__)


class ConfigPayload(BaseModel):
    yaml: str | None = Field(default=None)
    config: dict[str, Any] | None = Field(default=None)


class ValidateRequest(ConfigPayload):
    source: str = Field(default="disk")


class DryRunRequest(BaseModel):
    yaml: str | None = Field(default=None)


@dataclass
class WebState:
    config_path: Path
    lock: threading.RLock = field(default_factory=threading.RLock)
    draft_yaml: str | None = None
    runtime_supervisor: RuntimeSupervisor | None = None
    job_manager: JobManager | None = None


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_disk_yaml(config_path: Path) -> str:
    return config_path.read_text(encoding="utf-8")


def _config_backup_path(config_path: Path) -> Path:
    return config_path.with_name(f"{config_path.name}.bak")


def _write_config_with_backup(config_path: Path, previous_yaml: str, next_yaml: str) -> None:
    backup_path = _config_backup_path(config_path)
    backup_path.write_text(previous_yaml, encoding="utf-8")
    config_path.write_text(next_yaml, encoding="utf-8")


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


def _to_yaml_text(payload: ConfigPayload, base_yaml_text: str) -> str:
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
    for mapping in config.paths.root_mappings:
        roots.add(Path(mapping.nested_root))
        roots.add(Path(mapping.shadow_root))
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


def create_app(  # noqa: C901
    *,
    config_path: str | Path | None = None,
    ui_dist_path: str | Path | None = None,
    runtime_supervisor: RuntimeSupervisor | None = None,
) -> FastAPI:
    if config_path is None:
        config_path = os.getenv("LIBRARIARR_CONFIG_PATH", "/config/config.yaml")

    app = FastAPI(title="LibrariArr Web API", version="0.1.0")
    install_log_buffer()
    state = WebState(
        config_path=Path(config_path),
        runtime_supervisor=runtime_supervisor,
        job_manager=JobManager(),
    )
    app.state.web = state
    app.include_router(build_operations_router())

    @app.on_event("startup")
    def startup() -> None:
        if state.job_manager is not None:
            state.job_manager.start()

    @app.on_event("shutdown")
    def shutdown() -> None:
        if state.job_manager is not None:
            state.job_manager.stop()

    if ui_dist_path is None:
        ui_dist_path = os.getenv("LIBRARIARR_UI_DIST", "/app/ui/dist")
    dist_dir = Path(ui_dist_path)
    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/config")
    def get_config(
        include_secrets: bool = Query(default=False),
        source: str = Query(default="disk"),
    ) -> dict[str, Any]:
        with state.lock:
            disk_yaml = _load_disk_yaml(state.config_path)
            selected_source = "disk"
            selected_yaml = disk_yaml
            if source == "draft" and state.draft_yaml is not None:
                selected_source = "draft"
                selected_yaml = state.draft_yaml

        config, error = _validate_yaml_text(selected_yaml)
        if config is None:
            raise HTTPException(status_code=500, detail=f"Config parse error: {error}")

        return {
            "source": selected_source,
            "checksum": _checksum(selected_yaml),
            "yaml": selected_yaml,
            "has_draft": state.draft_yaml is not None,
            "config": _serialize_config(config, include_secrets=include_secrets),
        }

    @app.post("/api/config/validate")
    def validate_config(request: ValidateRequest) -> dict[str, Any]:
        LOG.info("Config validation requested (source=%s)", request.source)
        with state.lock:
            disk_yaml = _load_disk_yaml(state.config_path)
            base_yaml = disk_yaml
            if request.source == "draft" and state.draft_yaml is not None:
                base_yaml = state.draft_yaml

            try:
                candidate_yaml = _to_yaml_text(request, base_yaml)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            state.draft_yaml = candidate_yaml

        config, error = _validate_yaml_text(candidate_yaml)
        if config is None:
            LOG.warning("Config validation failed: %s", error)
            return {
                "valid": False,
                "issues": [{"severity": "error", "message": error or "Invalid YAML"}],
                "checksum": _checksum(candidate_yaml),
            }

        LOG.info("Config validation passed")
        return {
            "valid": True,
            "issues": [],
            "checksum": _checksum(candidate_yaml),
            "config": _serialize_config(config, include_secrets=False),
        }

    @app.put("/api/config")
    def put_config(request: ConfigPayload) -> dict[str, Any]:
        LOG.info("Config save requested")
        with state.lock:
            disk_yaml = _load_disk_yaml(state.config_path)
            try:
                candidate_yaml = _to_yaml_text(request, disk_yaml)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            config, error = _validate_yaml_text(candidate_yaml)
            if config is None:
                LOG.warning("Config save validation failed: %s", error)
                return {
                    "saved": False,
                    "issues": [{"severity": "error", "message": error or "Invalid YAML"}],
                    "checksum": _checksum(candidate_yaml),
                }

            try:
                _write_config_with_backup(
                    config_path=state.config_path,
                    previous_yaml=disk_yaml,
                    next_yaml=candidate_yaml,
                )
            except OSError as exc:
                if _is_permission_error(exc):
                    LOG.error(
                        "Config save failed due to permissions for %s: %s",
                        state.config_path,
                        exc,
                    )
                    raise HTTPException(
                        status_code=500,
                        detail=(
                            "Unable to save config file due to permissions. "
                            "Ensure the runtime user can write both config.yaml "
                            "and config.yaml.bak."
                        ),
                    ) from exc
                LOG.error("Config save failed due to filesystem error: %s", exc)
                raise HTTPException(
                    status_code=500,
                    detail=f"Unable to save config file: {exc}",
                ) from exc
            state.draft_yaml = None
            LOG.info("Config saved to %s (backup written)", state.config_path)

        # The RuntimeSupervisor config-watch loop detects the mtime change
        # and triggers a restart automatically — no explicit restart needed.
        runtime_will_restart = state.runtime_supervisor is not None
        if runtime_will_restart:
            LOG.info("Config file written; runtime config-watcher will pick up the change")

        return {
            "saved": True,
            "issues": [],
            "checksum": _checksum(candidate_yaml),
            "runtime_restart_recommended": not runtime_will_restart,
            "runtime_restarted": runtime_will_restart,
            "config": _serialize_config(config, include_secrets=False),
        }

    @app.get("/api/config/diff")
    def config_diff() -> dict[str, Any]:
        with state.lock:
            disk_yaml = _load_disk_yaml(state.config_path)
            draft_yaml = state.draft_yaml

        if draft_yaml is None:
            return {"has_diff": False, "diff": ""}

        diff = "".join(
            difflib.unified_diff(
                disk_yaml.splitlines(keepends=True),
                draft_yaml.splitlines(keepends=True),
                fromfile="config.yaml",
                tofile="draft.yaml",
            )
        )
        return {"has_diff": bool(diff.strip()), "diff": diff}

    @app.get("/api/fs/roots")
    def fs_roots() -> dict[str, Any]:
        config = _safe_load_disk_config(state.config_path)
        roots = _allowed_roots(config)
        return {"roots": [str(root) for root in roots]}

    @app.get("/api/fs/ls")
    def fs_ls(
        path: str | None = Query(default=None),
        include_hidden: bool = Query(default=False),
    ) -> dict[str, Any]:
        config = _safe_load_disk_config(state.config_path)
        allowed = _allowed_roots(config)

        if path is None:
            return {"path": None, "entries": [], "allowed_roots": [str(root) for root in allowed]}

        requested = Path(path)
        if not _is_allowed_path(requested, allowed):
            raise HTTPException(status_code=403, detail="Requested path is outside allowed roots.")
        if not requested.exists() or not requested.is_dir():
            raise HTTPException(status_code=404, detail="Requested path does not exist.")

        entries: list[dict[str, Any]] = []
        sorted_entries = sorted(
            requested.iterdir(),
            key=lambda item: (not item.is_dir(), item.name.lower()),
        )
        for child in sorted_entries:
            if not include_hidden and child.name.startswith("."):
                continue
            entries.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "is_dir": child.is_dir(),
                    "is_symlink": child.is_symlink(),
                }
            )

        return {
            "path": str(requested),
            "entries": entries,
            "allowed_roots": [str(root) for root in allowed],
        }

    def _radarr_items(fetch: callable) -> dict[str, Any]:
        config = _safe_load_disk_config(state.config_path)
        if not config.radarr.enabled:
            return {"enabled": False, "items": [], "error": None}

        client = RadarrClient(config.radarr.url, config.radarr.api_key, timeout=5)
        try:
            items = fetch(client)
            count = len(items) if isinstance(items, list) else 0
            LOG.debug("Radarr metadata fetch returned %d items", count)
            return {"enabled": True, "items": items, "error": None}
        except Exception as exc:
            LOG.error("Radarr metadata fetch failed: %s", exc)
            return {"enabled": True, "items": [], "error": str(exc)}

    def _sonarr_items(fetch: callable) -> dict[str, Any]:
        config = _safe_load_disk_config(state.config_path)
        if not config.sonarr.enabled:
            return {"enabled": False, "items": [], "error": None}

        client = SonarrClient(config.sonarr.url, config.sonarr.api_key, timeout=5)
        try:
            items = fetch(client)
            count = len(items) if isinstance(items, list) else 0
            LOG.debug("Sonarr metadata fetch returned %d items", count)
            return {"enabled": True, "items": items, "error": None}
        except Exception as exc:
            LOG.error("Sonarr metadata fetch failed: %s", exc)
            return {"enabled": True, "items": [], "error": str(exc)}

    @app.get("/api/radarr/quality-profiles")
    def radarr_quality_profiles() -> dict[str, Any]:
        return _radarr_items(lambda client: client.get_quality_profiles())

    @app.get("/api/radarr/quality-definitions")
    def radarr_quality_definitions() -> dict[str, Any]:
        return _radarr_items(lambda client: client.get_quality_definitions())

    @app.get("/api/radarr/custom-formats")
    def radarr_custom_formats() -> dict[str, Any]:
        return _radarr_items(lambda client: client.get_custom_formats())

    @app.get("/api/radarr/root-folders")
    def radarr_root_folders() -> dict[str, Any]:
        return _radarr_items(lambda client: client.get_root_folders())

    @app.get("/api/radarr/tags")
    def radarr_tags() -> dict[str, Any]:
        return _radarr_items(lambda client: client.get_tags())

    @app.get("/api/sonarr/quality-profiles")
    def sonarr_quality_profiles() -> dict[str, Any]:
        return _sonarr_items(lambda client: client.get_quality_profiles())

    @app.get("/api/sonarr/language-profiles")
    def sonarr_language_profiles() -> dict[str, Any]:
        return _sonarr_items(lambda client: client.get_language_profiles())

    @app.get("/api/sonarr/root-folders")
    def sonarr_root_folders() -> dict[str, Any]:
        return _sonarr_items(lambda client: client.get_root_folders())

    @app.get("/api/sonarr/tags")
    def sonarr_tags() -> dict[str, Any]:
        return _sonarr_items(lambda client: client.get_tags())

    @app.post("/api/diagnostics/radarr")
    def diagnostics_radarr() -> dict[str, Any]:
        manager = _job_manager_or_http(state)

        def action() -> dict[str, Any]:
            LOG.info("Running Radarr diagnostics")
            config = _safe_load_disk_config(state.config_path)
            result = run_radarr_diagnostics(config)
            issue_count = len(result.get("issues", []))
            LOG.info(
                "Radarr diagnostics completed: status=%s, issues=%d",
                result.get("status"),
                issue_count,
            )
            return result

        job_id = manager.submit(kind="diagnostics-radarr", func=action)
        return {
            "ok": True,
            "queued": True,
            "job_id": job_id,
            "message": "Radarr diagnostics scheduled.",
        }

    @app.post("/api/diagnostics/sonarr")
    def diagnostics_sonarr() -> dict[str, Any]:
        manager = _job_manager_or_http(state)

        def action() -> dict[str, Any]:
            LOG.info("Running Sonarr diagnostics")
            config = _safe_load_disk_config(state.config_path)
            result = run_sonarr_diagnostics(config)
            issue_count = len(result.get("issues", []))
            LOG.info(
                "Sonarr diagnostics completed: status=%s, issues=%d",
                result.get("status"),
                issue_count,
            )
            return result

        job_id = manager.submit(kind="diagnostics-sonarr", func=action)
        return {
            "ok": True,
            "queued": True,
            "job_id": job_id,
            "message": "Sonarr diagnostics scheduled.",
        }

    @app.post("/api/dry-run")
    def dry_run(request: DryRunRequest) -> dict[str, Any]:
        manager = _job_manager_or_http(state)

        def action() -> dict[str, Any]:
            if request.yaml is None:
                config = _safe_load_disk_config(state.config_path)
            else:
                config, error = _validate_yaml_text(request.yaml)
                if config is None:
                    return {
                        "ok": False,
                        "issues": [{"severity": "error", "message": error or "Invalid YAML"}],
                    }

            video_exts = set(config.runtime.scan_video_extensions or VIDEO_EXTENSIONS)
            movie_folder_count = 0
            series_folder_count = 0

            for mapping in config.paths.root_mappings:
                nested_root = Path(mapping.nested_root)
                if config.radarr.enabled:
                    movie_folder_count += len(
                        discover_movie_folders(
                            nested_root,
                            video_exts,
                            config.paths.exclude_paths,
                        )
                    )
                if config.sonarr.enabled:
                    series_folder_count += len(
                        discover_series_folders(
                            nested_root,
                            video_exts,
                            config.paths.exclude_paths,
                        )
                    )

            return {
                "ok": True,
                "summary": {
                    "movie_folders_detected": movie_folder_count,
                    "series_folders_detected": series_folder_count,
                    "root_mappings": len(config.paths.root_mappings),
                },
                "issues": [],
                "mode": "read-only",
            }

        job_id = manager.submit(kind="dry-run", func=action)
        return {
            "ok": True,
            "queued": True,
            "job_id": job_id,
            "message": "Dry-run scheduled.",
        }

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
    runtime_supervisor: RuntimeSupervisor | None = None
    if run_runtime_loop:
        runtime_supervisor = RuntimeSupervisor(config_path=Path(config_path))
        runtime_supervisor.start()

    app = create_app(config_path=config_path, runtime_supervisor=runtime_supervisor)
    try:
        uvicorn.run(app, host=host, port=port, log_level=log_level.lower())
    finally:
        if runtime_supervisor is not None:
            runtime_supervisor.stop()
