from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request

from ..config import AppConfig, load_config


def load_config_or_http(config_path: Path) -> AppConfig:
    try:
        return load_config(config_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unable to load config: {exc}") from exc


def read_config_path(request: Request) -> Path:
    return Path(request.app.state.web.config_path)


def job_manager_or_http(request: Request):
    manager = getattr(request.app.state.web, "job_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Job manager is unavailable.")
    return manager
