from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query


def build_basic_fs_router(
    *,
    state: Any,
    safe_load_disk_config_fn: Callable[[Path], Any],
    allowed_roots_fn: Callable[[Any], list[Path]],
    is_allowed_path_fn: Callable[[Path, list[Path]], bool],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/fs/roots")
    def fs_roots() -> dict[str, Any]:
        config = safe_load_disk_config_fn(state.config_path)
        roots = allowed_roots_fn(config)
        return {"roots": [str(root) for root in roots]}

    @router.get("/api/fs/ls")
    def fs_ls(
        path: str | None = Query(default=None),
        include_hidden: bool = Query(default=False),
    ) -> dict[str, Any]:
        config = safe_load_disk_config_fn(state.config_path)
        allowed = allowed_roots_fn(config)

        if path is None:
            return {"path": None, "entries": [], "allowed_roots": [str(root) for root in allowed]}

        requested = Path(path)
        if not is_allowed_path_fn(requested, allowed):
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

    return router
