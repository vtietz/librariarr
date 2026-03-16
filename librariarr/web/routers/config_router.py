from __future__ import annotations

import difflib
import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field


class ConfigPayload(BaseModel):
    yaml: str | None = Field(default=None)
    config: dict[str, Any] | None = Field(default=None)


class ValidateRequest(ConfigPayload):
    source: str = Field(default="disk")


def build_config_router(  # noqa: C901
    *,
    state: Any,
    load_disk_yaml_fn: Callable[[Any], str],
    validate_yaml_text_fn: Callable[[str], tuple[Any | None, str | None]],
    to_yaml_text_fn: Callable[[ConfigPayload, str], str],
    checksum_fn: Callable[[str], str],
    serialize_config_fn: Callable[[Any, bool], dict[str, Any]],
    write_config_with_backup_fn: Callable[[Any, str, str], None],
    is_permission_error_fn: Callable[[OSError], bool],
    logger: logging.Logger,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/config")
    def get_config(
        include_secrets: bool = Query(default=False),
        source: str = Query(default="disk"),
    ) -> dict[str, Any]:
        with state.lock:
            disk_yaml = load_disk_yaml_fn(state.config_path)
            selected_source = "disk"
            selected_yaml = disk_yaml
            if source == "draft" and state.draft_yaml is not None:
                selected_source = "draft"
                selected_yaml = state.draft_yaml

        config, error = validate_yaml_text_fn(selected_yaml)
        if config is None:
            raise HTTPException(status_code=500, detail=f"Config parse error: {error}")

        return {
            "source": selected_source,
            "checksum": checksum_fn(selected_yaml),
            "yaml": selected_yaml,
            "has_draft": state.draft_yaml is not None,
            "config": serialize_config_fn(config, include_secrets=include_secrets),
        }

    @router.post("/api/config/validate")
    def validate_config(request: ValidateRequest) -> dict[str, Any]:
        logger.info("Config validation requested (source=%s)", request.source)
        with state.lock:
            disk_yaml = load_disk_yaml_fn(state.config_path)
            base_yaml = disk_yaml
            if request.source == "draft" and state.draft_yaml is not None:
                base_yaml = state.draft_yaml

            try:
                candidate_yaml = to_yaml_text_fn(request, base_yaml)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            state.draft_yaml = candidate_yaml

        config, error = validate_yaml_text_fn(candidate_yaml)
        if config is None:
            logger.warning("Config validation failed: %s", error)
            return {
                "valid": False,
                "issues": [{"severity": "error", "message": error or "Invalid YAML"}],
                "checksum": checksum_fn(candidate_yaml),
            }

        logger.info("Config validation passed")
        return {
            "valid": True,
            "issues": [],
            "checksum": checksum_fn(candidate_yaml),
            "config": serialize_config_fn(config, include_secrets=False),
        }

    @router.put("/api/config")
    def put_config(request: ConfigPayload) -> dict[str, Any]:
        logger.info("Config save requested")
        with state.lock:
            disk_yaml = load_disk_yaml_fn(state.config_path)
            try:
                candidate_yaml = to_yaml_text_fn(request, disk_yaml)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            config, error = validate_yaml_text_fn(candidate_yaml)
            if config is None:
                logger.warning("Config save validation failed: %s", error)
                return {
                    "saved": False,
                    "issues": [{"severity": "error", "message": error or "Invalid YAML"}],
                    "checksum": checksum_fn(candidate_yaml),
                }

            try:
                write_config_with_backup_fn(
                    config_path=state.config_path,
                    previous_yaml=disk_yaml,
                    next_yaml=candidate_yaml,
                )
            except OSError as exc:
                if is_permission_error_fn(exc):
                    logger.error(
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
                logger.error("Config save failed due to filesystem error: %s", exc)
                raise HTTPException(
                    status_code=500,
                    detail=f"Unable to save config file: {exc}",
                ) from exc
            state.draft_yaml = None
            logger.info("Config saved to %s (backup written)", state.config_path)

        runtime_will_restart = state.runtime_supervisor is not None
        if runtime_will_restart:
            logger.info("Config file written; runtime config-watcher will pick up the change")

        return {
            "saved": True,
            "issues": [],
            "checksum": checksum_fn(candidate_yaml),
            "runtime_restart_recommended": not runtime_will_restart,
            "runtime_restarted": runtime_will_restart,
            "config": serialize_config_fn(config, include_secrets=False),
        }

    @router.get("/api/config/diff")
    def config_diff() -> dict[str, Any]:
        with state.lock:
            disk_yaml = load_disk_yaml_fn(state.config_path)
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

    return router
