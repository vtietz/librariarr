from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ...quality import VIDEO_EXTENSIONS
from ...service.reconcile_helpers import resolve_managed_root_for_folder
from ...sync.naming import parse_movie_ref
from ..history_events import append_history_event


def build_fs_router(  # noqa: C901
    *,
    load_config_or_http_fn: Callable[[Path], Any],
    read_config_path_fn: Callable[[Request], Path],
    job_manager_or_http_fn: Callable[[Request], Any],
    mapped_cache: Any,
    discovery_cache: Any,
    shadow_roots_fn: Callable[[Any], list[Path]],
    enrich_mapped_directories_with_radarr_state_fn: Callable[..., list[dict[str, Any]]],
    apply_path_mapping_outcomes_fn: Callable[..., list[dict[str, Any]]],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/fs/mapped-directories")
    def mapped_directories(
        request: Request,
        search: str = Query(default=""),
        shadow_root: str | None = Query(default=None),
        limit: int = Query(default=500, ge=1, le=5000),
        include_arr_state: bool = Query(default=False),
        arr_virtual_path: Annotated[list[str] | None, Query()] = None,
    ) -> dict[str, Any]:
        config = load_config_or_http_fn(read_config_path_fn(request))
        all_roots = shadow_roots_fn(config)

        snapshot = mapped_cache.snapshot()

        if shadow_root is None:
            selected_roots = {str(root) for root in all_roots}
        else:
            selected_roots = {str(root) for root in all_roots if str(root) == shadow_root}
            if not selected_roots:
                raise HTTPException(status_code=400, detail="Unknown shadow_root filter value")

        lowered_search = search.strip().lower()
        items: list[dict[str, Any]] = []

        for entry in snapshot["items"]:
            root_str = str(entry.get("shadow_root", ""))
            if root_str not in selected_roots:
                continue
            virtual_path = str(entry.get("virtual_path", ""))
            real_path = str(entry.get("real_path", ""))
            if (
                lowered_search
                and lowered_search not in virtual_path.lower()
                and lowered_search not in real_path.lower()
            ):
                continue
            items.append(entry)

        if include_arr_state:
            scoped_virtual_paths = {
                value.strip()
                for value in (arr_virtual_path or [])
                if isinstance(value, str) and value.strip()
            }
            if scoped_virtual_paths:
                scoped_items = [
                    item
                    for item in items
                    if str(item.get("virtual_path", "")) in scoped_virtual_paths
                ]
                scoped_enriched = enrich_mapped_directories_with_radarr_state_fn(
                    scoped_items,
                    config=config,
                    selected_roots=selected_roots,
                    lowered_search=lowered_search,
                    include_missing_virtual_paths=False,
                )
                enriched_by_virtual_path = {
                    str(entry.get("virtual_path", "")): entry for entry in scoped_enriched
                }
                items = [
                    enriched_by_virtual_path.get(str(item.get("virtual_path", "")), item)
                    for item in items
                ]
            else:
                items = enrich_mapped_directories_with_radarr_state_fn(
                    items,
                    config=config,
                    selected_roots=selected_roots,
                    lowered_search=lowered_search,
                    include_missing_virtual_paths=True,
                )

        items = apply_path_mapping_outcomes_fn(
            items,
            state_store=getattr(request.app.state.web, "state_store", None),
        )

        truncated = len(items) > limit
        if truncated:
            items = items[:limit]

        return {
            "items": items,
            "shadow_roots": [str(root) for root in all_roots],
            "truncated": truncated,
            "cache": {
                "ready": bool(snapshot["ready"]),
                "building": bool(snapshot["building"]),
                "updated_at_ms": snapshot["updated_at_ms"],
                "last_error": snapshot["last_error"],
                "entries_total": len(snapshot["items"]),
                "version": snapshot["version"],
                "last_build_duration_ms": snapshot.get("last_build_duration_ms"),
            },
        }

    @router.get("/api/fs/discovery-warnings")
    def discovery_warnings(
        request: Request,
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> dict[str, Any]:
        config = load_config_or_http_fn(read_config_path_fn(request))
        discovery_cache.request_refresh(config)
        snapshot = discovery_cache.snapshot(limit=limit)
        if snapshot["cache"]["building"]:
            discovery_cache.wait_for_build(timeout=2.0)
            snapshot = discovery_cache.snapshot(limit=limit)
        return snapshot

    @router.post("/api/fs/mapped-directories/refresh")
    def refresh_mapped_directories(request: Request) -> dict[str, Any]:
        manager = job_manager_or_http_fn(request)
        config_path = read_config_path_fn(request)

        def action() -> dict[str, Any]:
            config = load_config_or_http_fn(config_path)
            started = mapped_cache.request_refresh(config, force=True)
            return {
                "ok": True,
                "started": bool(started),
                "message": (
                    "Mapped directory refresh started."
                    if started
                    else "Mapped directory refresh already in progress."
                ),
            }

        snapshot = mapped_cache.snapshot()
        job_id = manager.submit(
            kind="cache-refresh-mapped-request",
            name="Refresh Mapped Directories",
            source="job-manager",
            detail="queued",
            func=action,
            history_visible=False,
        )
        return {
            "ok": True,
            "queued": True,
            "job_id": job_id,
            "cache": {
                "ready": bool(snapshot["ready"]),
                "building": bool(snapshot["building"]),
                "entries_total": len(snapshot["items"]),
                "version": snapshot["version"],
                "last_build_duration_ms": snapshot.get("last_build_duration_ms"),
            },
        }

    @router.get("/api/fs/mapped-directories/stream")
    async def mapped_directories_stream(
        request: Request,
        interval_ms: int = Query(default=2000, ge=200, le=10000),
        max_events: int = Query(default=0, ge=0),
    ) -> StreamingResponse:
        async def event_stream():
            previous_version: int | None = None
            event_count = 0
            while True:
                if await request.is_disconnected():
                    break

                snapshot = mapped_cache.snapshot()
                current_version = int(snapshot["version"])
                changed = previous_version is not None and current_version != previous_version

                if previous_version is None or changed:
                    payload = {
                        "changed": changed,
                        "cache_ready": bool(snapshot["ready"]),
                        "cache_building": bool(snapshot["building"]),
                        "cache_entries_total": len(snapshot["items"]),
                        "timestamp_ms": int(time.time() * 1000),
                    }
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\\n\\n"
                    event_count += 1
                    if max_events > 0 and event_count >= max_events:
                        break
                else:
                    yield ": keepalive\\n\\n"

                previous_version = current_version
                await asyncio.sleep(interval_ms / 1000)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.delete("/api/fs/shadow-folder")
    def delete_shadow_folder(
        request: Request,
        path: str = Query(...),
    ) -> dict[str, Any]:
        path_value = path.strip()
        if not path_value:
            raise HTTPException(status_code=400, detail="path must not be empty")
        target = Path(path_value)
        if not target.is_absolute():
            raise HTTPException(status_code=400, detail="path must be an absolute path")

        config = load_config_or_http_fn(read_config_path_fn(request))
        all_roots = shadow_roots_fn(config)
        if not any(target == root or root in target.parents for root in all_roots):
            raise HTTPException(
                status_code=403, detail="path is not under a known shadow/library root"
            )

        if not target.exists():
            raise HTTPException(status_code=404, detail="shadow folder does not exist")
        if not target.is_dir():
            raise HTTPException(status_code=400, detail="path is not a directory")

        # Safety: refuse to delete the shadow root itself
        if target in all_roots:
            raise HTTPException(status_code=400, detail="cannot delete a shadow root directory")

        removed_files = 0
        for item in target.rglob("*"):
            if item.is_file() or item.is_symlink():
                removed_files += 1
        shutil.rmtree(target)

        # Remove provenance entries for this shadow path
        _purge_provenance_for_shadow_path(target)

        # Trigger cache refresh
        mapped_cache.request_refresh(config, force=True)

        return {
            "ok": True,
            "removed_path": str(target),
            "removed_files": removed_files,
        }

    @router.post("/api/fs/orphaned-managed-folders/recycle")
    def recycle_orphaned_managed_folder(
        request: Request,
        path: str = Query(...),
    ) -> dict[str, Any]:
        target = _validated_absolute_path(path)
        config = load_config_or_http_fn(read_config_path_fn(request))
        managed_root_mappings = [
            (
                Path(item.managed_root).resolve(strict=False),
                Path(item.library_root).resolve(strict=False),
            )
            for item in config.paths.movie_root_mappings
        ]
        managed_root = resolve_managed_root_for_folder(target, managed_root_mappings)

        if managed_root is None:
            raise HTTPException(
                status_code=403,
                detail="path is not under a configured managed movie root",
            )
        if not target.exists():
            raise HTTPException(status_code=404, detail="folder does not exist")
        if not target.is_dir():
            raise HTTPException(status_code=400, detail="path is not a directory")
        if target == managed_root:
            raise HTTPException(status_code=400, detail="cannot recycle a managed root directory")

        trash_root = _trash_root_for_managed_root(managed_root)
        if target == trash_root or trash_root in target.parents:
            raise HTTPException(
                status_code=400,
                detail="path is already inside .deletedByLibrariarr",
            )

        video_exts = set(config.runtime.scan_video_extensions or VIDEO_EXTENSIONS)
        if not _is_orphaned_managed_movie_folder(target, video_exts):
            raise HTTPException(
                status_code=409,
                detail=(
                    "folder is not orphaned: requires parseable movie folder name "
                    "and no video files"
                ),
            )

        recycled_path = _recycle_folder_target(target=target, managed_root=managed_root)
        recycled_path.parent.mkdir(parents=True, exist_ok=True)
        target.rename(recycled_path)

        state_store = getattr(getattr(request.app.state, "web", None), "state_store", None)
        if state_store is not None:
            append_history_event(
                state_store,
                scenario="2",
                category="deleted_files",
                title=f"Recycled orphaned folder: {target.name}",
                message=(
                    "Moved orphaned managed folder to .deletedByLibrariarr: "
                    f"{target} -> {recycled_path}"
                ),
            )

        discovery_cache.request_refresh(config, force=True)

        return {
            "ok": True,
            "source_path": str(target),
            "recycled_path": str(recycled_path),
        }

    @router.get("/api/fs/deleted-files")
    def list_deleted_files(
        request: Request,
        managed_root: str | None = Query(default=None),
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> dict[str, Any]:
        config = load_config_or_http_fn(read_config_path_fn(request))
        managed_roots = _managed_roots_for_deleted_files(config)
        selected_roots = _selected_managed_roots(managed_roots, managed_root)

        items: list[dict[str, Any]] = []
        for root in selected_roots:
            trash_root = _trash_root_for_managed_root(root)
            if not trash_root.exists() or not trash_root.is_dir():
                continue
            for entry in trash_root.rglob("*"):
                if not entry.is_file():
                    continue
                try:
                    relative = entry.relative_to(trash_root)
                except ValueError:
                    continue
                restore_rel = _restore_relative_path(relative)
                if restore_rel is None:
                    continue
                restore_path = root / restore_rel
                stat = entry.stat()
                items.append(
                    {
                        "path": str(entry),
                        "managed_root": str(root),
                        "restore_path": str(restore_path),
                        "size_bytes": int(stat.st_size),
                        "updated_at": float(stat.st_mtime),
                        "exists": restore_path.exists(),
                    }
                )

        items.sort(key=lambda item: float(item.get("updated_at") or 0.0), reverse=True)
        truncated = len(items) > limit
        if truncated:
            items = items[:limit]

        return {
            "items": items,
            "managed_roots": [str(root) for root in managed_roots],
            "truncated": truncated,
        }

    @router.post("/api/fs/deleted-files/restore")
    def restore_deleted_file(
        request: Request,
        path: str = Query(...),
    ) -> dict[str, Any]:
        target = _validated_absolute_path(path)
        config = load_config_or_http_fn(read_config_path_fn(request))
        managed_roots = _managed_roots_for_deleted_files(config)
        managed_root = _managed_root_for_deleted_file(target, managed_roots)

        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="deleted file does not exist")

        trash_root = _trash_root_for_managed_root(managed_root)
        try:
            relative = target.relative_to(trash_root)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="path is not inside a managed trash folder",
            ) from exc

        restore_rel = _restore_relative_path(relative)
        if restore_rel is None:
            raise HTTPException(
                status_code=400,
                detail="cannot determine restore target from deleted filename",
            )

        restore_path = managed_root / restore_rel
        if restore_path.exists():
            raise HTTPException(status_code=409, detail="restore target already exists")

        restore_path.parent.mkdir(parents=True, exist_ok=True)
        target.rename(restore_path)
        _prune_empty_parents(trash_root, target.parent)

        state_store = getattr(getattr(request.app.state, "web", None), "state_store", None)
        if state_store is not None:
            append_history_event(
                state_store,
                scenario="2",
                category="deleted_files",
                title=f"Restored file: {restore_path.name}",
                message="A file was restored from .deletedByLibrariarr back to managed storage.",
            )

        return {
            "ok": True,
            "restored_path": str(restore_path),
            "source_path": str(target),
        }

    @router.delete("/api/fs/deleted-files")
    def delete_deleted_file(
        request: Request,
        path: str = Query(...),
    ) -> dict[str, Any]:
        target = _validated_absolute_path(path)
        config = load_config_or_http_fn(read_config_path_fn(request))
        managed_roots = _managed_roots_for_deleted_files(config)
        managed_root = _managed_root_for_deleted_file(target, managed_roots)

        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="deleted file does not exist")

        trash_root = _trash_root_for_managed_root(managed_root)
        target.unlink()
        _prune_empty_parents(trash_root, target.parent)

        state_store = getattr(getattr(request.app.state, "web", None), "state_store", None)
        if state_store is not None:
            append_history_event(
                state_store,
                scenario="2",
                category="deleted_files",
                title=f"Permanently deleted: {target.name}",
                message="A file was permanently removed from .deletedByLibrariarr.",
            )

        return {
            "ok": True,
            "deleted_path": str(target),
        }

    @router.post("/api/fs/deleted-files/clear")
    def clear_deleted_files(
        request: Request,
        managed_root: str | None = Query(default=None),
    ) -> dict[str, Any]:
        config = load_config_or_http_fn(read_config_path_fn(request))
        managed_roots = _managed_roots_for_deleted_files(config)
        selected_roots = _selected_managed_roots(managed_roots, managed_root)

        removed_files = 0
        removed_roots = 0
        for root in selected_roots:
            trash_root = _trash_root_for_managed_root(root)
            if not trash_root.exists() or not trash_root.is_dir():
                continue
            removed_files += sum(
                1 for item in trash_root.rglob("*") if item.is_file() or item.is_symlink()
            )
            shutil.rmtree(trash_root)
            removed_roots += 1

        state_store = getattr(getattr(request.app.state, "web", None), "state_store", None)
        if state_store is not None and removed_files > 0:
            append_history_event(
                state_store,
                scenario="2",
                category="deleted_files",
                title=f"Cleared deleted files ({removed_files})",
                message="Removed files from one or more managed .deletedByLibrariarr folders.",
            )

        return {
            "ok": True,
            "removed_files": removed_files,
            "removed_roots": removed_roots,
        }

    return router


_SOFT_DELETE_SUFFIX_RE = re.compile(r"\.\d{8}T\d{12}Z(?:\.\d+)?$")
_ORPHAN_RECYCLE_SUFFIX_RE = re.compile(r"\.orphan\.\d{8}T\d{12}Z(?:\.\d+)?$")


def _managed_roots_for_deleted_files(config: Any) -> list[Path]:
    roots = {
        Path(item.managed_root).resolve(strict=False) for item in config.paths.movie_root_mappings
    }
    roots.update(
        Path(item.nested_root).resolve(strict=False) for item in config.paths.series_root_mappings
    )
    return sorted(roots)


def _selected_managed_roots(managed_roots: list[Path], selected_root: str | None) -> list[Path]:
    if selected_root is None:
        return managed_roots
    selected = Path(selected_root.strip()).resolve(strict=False)
    if selected not in managed_roots:
        raise HTTPException(status_code=400, detail="Unknown managed_root filter value")
    return [selected]


def _trash_root_for_managed_root(managed_root: Path) -> Path:
    return managed_root / ".deletedByLibrariarr"


def _restore_relative_path(relative_path: Path) -> Path | None:
    restored_parts: list[str] = []
    changed = False

    for index, part in enumerate(relative_path.parts):
        updated = _ORPHAN_RECYCLE_SUFFIX_RE.sub("", part)
        if index == len(relative_path.parts) - 1:
            updated = _SOFT_DELETE_SUFFIX_RE.sub("", updated)
        if updated != part:
            changed = True
        restored_parts.append(updated)

    if not changed:
        return None
    return Path(*restored_parts)


def _is_orphaned_managed_movie_folder(folder: Path, video_exts: set[str]) -> bool:
    ref = parse_movie_ref(folder.name)
    if ref.year is None or not ref.title:
        return False
    return not _contains_video_recursively(folder, video_exts)


def _contains_video_recursively(folder: Path, video_exts: set[str]) -> bool:
    for _current, _dirs, files in os.walk(folder):
        if any(Path(filename).suffix.lower() in video_exts for filename in files):
            return True
    return False


def _recycle_folder_target(*, target: Path, managed_root: Path) -> Path:
    trash_root = _trash_root_for_managed_root(managed_root)
    try:
        relative = target.relative_to(managed_root)
    except ValueError:
        relative = Path(target.name)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    folder_name = f"{relative.name}.orphan.{timestamp}"
    candidate = trash_root / relative.parent / folder_name
    suffix = 1
    while candidate.exists():
        candidate = trash_root / relative.parent / f"{folder_name}.{suffix}"
        suffix += 1
    return candidate


def _validated_absolute_path(raw_path: str) -> Path:
    value = raw_path.strip()
    if not value:
        raise HTTPException(status_code=400, detail="path must not be empty")
    path = Path(value)
    if not path.is_absolute():
        raise HTTPException(status_code=400, detail="path must be an absolute path")
    return path.resolve(strict=False)


def _managed_root_for_deleted_file(path: Path, managed_roots: list[Path]) -> Path:
    for managed_root in managed_roots:
        trash_root = _trash_root_for_managed_root(managed_root)
        if path == trash_root or trash_root in path.parents:
            return managed_root
    raise HTTPException(status_code=403, detail="path is not under a managed deleted-files folder")


def _prune_empty_parents(stop_root: Path, start_dir: Path) -> None:
    current = start_dir
    while current != stop_root and stop_root in current.parents:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _purge_provenance_for_shadow_path(shadow_path: Path) -> None:
    """Remove projected_files rows whose dest_path is under the deleted shadow folder."""
    from ...projection.orchestrator import _projection_state_db_path
    from ...projection.provenance import ProjectionStateStore
    from ...projection.sonarr_orchestrator import _sonarr_projection_state_db_path

    for db_path_fn in (_projection_state_db_path, _sonarr_projection_state_db_path):
        db_path = db_path_fn()
        if db_path.exists():
            store = ProjectionStateStore(db_path)
            store.delete_projected_files_under_path(shadow_path)
