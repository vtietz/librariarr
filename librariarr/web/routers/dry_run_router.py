from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field


class DryRunRequest(BaseModel):
    yaml: str | None = Field(default=None)


def build_dry_run_router(
    *,
    state: Any,
    job_manager_or_http_fn: Callable[[Any], Any],
    safe_load_disk_config_fn: Callable[[Path], Any],
    validate_yaml_text_fn: Callable[[str], tuple[Any | None, str | None]],
    discover_movie_folders_fn: Callable[[Path, set[str], list[str]], dict[Path, Path]],
    discover_series_folders_fn: Callable[[Path, set[str], list[str]], dict[Path, Path]],
    video_extensions: set[str],
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/dry-run")
    def dry_run(request: DryRunRequest) -> dict[str, Any]:
        manager = job_manager_or_http_fn(state)

        def action() -> dict[str, Any]:
            if request.yaml is None:
                config = safe_load_disk_config_fn(state.config_path)
            else:
                config, error = validate_yaml_text_fn(request.yaml)
                if config is None:
                    return {
                        "ok": False,
                        "issues": [{"severity": "error", "message": error or "Invalid YAML"}],
                    }

            video_exts = set(config.runtime.scan_video_extensions or video_extensions)
            movie_folder_count = 0
            series_folder_count = 0

            for mapping in config.paths.root_mappings:
                nested_root = Path(mapping.nested_root)
                if config.radarr.enabled:
                    movie_folder_count += len(
                        discover_movie_folders_fn(
                            nested_root,
                            video_exts,
                            config.paths.exclude_paths,
                        )
                    )
                if config.sonarr.enabled:
                    series_folder_count += len(
                        discover_series_folders_fn(
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

    return router
