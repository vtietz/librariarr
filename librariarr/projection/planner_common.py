from __future__ import annotations

import fnmatch
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .models import MovieProjectionMapping, PlannedProjectionFile


def resolve_mapping_for_path(
    item_path: Path,
    mappings: list[MovieProjectionMapping],
) -> tuple[MovieProjectionMapping | None, Path | None, str | None]:
    for mapping in mappings:
        try:
            relative = item_path.relative_to(mapping.managed_root)
        except ValueError:
            pass
        else:
            return mapping, relative, "managed"

        try:
            relative = item_path.relative_to(mapping.library_root)
        except ValueError:
            continue
        return mapping, relative, "library"
    return None, None, None


def resolve_library_folder(
    *,
    item: dict[str, Any],
    relative_folder: Path,
    mapping: MovieProjectionMapping,
    path_component_sanitizer: Callable[[str], str],
    fallback_prefix: str,
) -> Path:
    title = str(item.get("title") or "").strip()
    year = item.get("year")
    if title and isinstance(year, int):
        return mapping.library_root / path_component_sanitizer(f"{title} ({year})")
    if title:
        return mapping.library_root / path_component_sanitizer(title)

    fallback_name = relative_folder.name or f"{fallback_prefix}-{item.get('id')}"
    return mapping.library_root / path_component_sanitizer(fallback_name)


def classify_file(
    *,
    relative_path: str,
    source_path: Path,
    managed_video_extensions: set[str],
    extras_allowlist: list[str],
) -> str | None:
    suffix = source_path.suffix.lower()
    if suffix in managed_video_extensions:
        return "video"

    relative_lower = relative_path.lower()
    name_lower = source_path.name.lower()
    for pattern in extras_allowlist:
        normalized_pattern = str(pattern).strip().lower()
        if not normalized_pattern:
            continue
        if fnmatch.fnmatch(name_lower, normalized_pattern):
            return "extra"
        if fnmatch.fnmatch(relative_lower, normalized_pattern):
            return "extra"

    return None


def collect_projection_files(
    *,
    managed_folder: Path,
    library_folder: Path,
    managed_video_extensions: set[str],
    extras_allowlist: list[str],
    classify_file_fn: Callable[..., str | None] | None = None,
) -> list[PlannedProjectionFile]:
    classifier = classify_file_fn or classify_file
    planned_files: list[PlannedProjectionFile] = []
    for current, _dirs, files in os.walk(managed_folder):
        current_path = Path(current)
        for filename in sorted(files):
            source_path = current_path / filename
            relative_path = source_path.relative_to(managed_folder).as_posix()
            file_kind = classifier(
                relative_path=relative_path,
                source_path=source_path,
                managed_video_extensions=managed_video_extensions,
                extras_allowlist=extras_allowlist,
            )
            if file_kind is None:
                continue
            planned_files.append(
                PlannedProjectionFile(
                    relative_path=relative_path,
                    source_path=source_path,
                    dest_path=library_folder / relative_path,
                    kind=file_kind,
                )
            )
    return planned_files


def emit_planning_progress(
    callback: Callable[[int, int], None] | None,
    processed: int,
    total: int,
) -> None:
    if callback is not None:
        callback(processed, total)


def repair_unmatched_managed_folders_generic(
    *,
    items: list[dict[str, Any]],
    mappings: list[MovieProjectionMapping],
    known_folders: dict[int, Path],
) -> list[tuple[int, Path]]:
    sorted_mappings = sorted(mappings, key=lambda item: len(item.managed_root.parts), reverse=True)
    repairs: list[tuple[int, Path]] = []
    managed_roots = {m.managed_root for m in mappings}

    for item in items:
        item_id = item.get("id")
        if not isinstance(item_id, int):
            continue

        existing = known_folders.get(item_id)
        if (
            existing
            and existing.exists()
            and existing.is_dir()
            and any(existing == mr or mr in existing.parents for mr in managed_roots)
        ):
            continue

        item_path_raw = str(item.get("path") or "").strip()
        if not item_path_raw:
            continue

        item_path = Path(item_path_raw)
        mapping, relative_folder, path_mode = resolve_mapping_for_path(item_path, sorted_mappings)
        if mapping is None or relative_folder is None:
            continue

        if path_mode == "managed":
            if item_path.exists() and item_path.is_dir():
                repairs.append((item_id, item_path))
        else:
            direct = mapping.managed_root / relative_folder
            if direct.exists() and direct.is_dir():
                repairs.append((item_id, direct))

    return repairs
