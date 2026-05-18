from __future__ import annotations

from pathlib import Path
from typing import Any

from ...quality import VIDEO_EXTENSIONS


def build_folder_comparison_info(target_path: Path) -> dict[str, Any]:
    resolved_path = target_path.resolve(strict=False)
    info: dict[str, Any] = {
        "path": str(resolved_path),
        "exists": resolved_path.exists(),
        "is_dir": resolved_path.is_dir(),
        "video_count": 0,
        "video_size_bytes": 0,
        "sample_video_files": [],
        "latest_video_file": None,
        "latest_video_mtime": None,
        "folder_created_at": None,
        "folder_changed_at": None,
        "folder_modified_at": None,
    }

    try:
        stat_result = resolved_path.stat()
    except OSError:
        return info

    info["folder_changed_at"] = float(stat_result.st_ctime)
    info["folder_modified_at"] = float(stat_result.st_mtime)
    birthtime = getattr(stat_result, "st_birthtime", None)
    if isinstance(birthtime, int | float):
        info["folder_created_at"] = float(birthtime)

    if not resolved_path.is_dir():
        return info

    latest_mtime: float | None = None
    latest_file: str | None = None
    sample_video_files: list[str] = []
    total_size = 0
    video_count = 0

    for child in sorted(resolved_path.glob("*"), key=lambda item: item.name.lower()):
        if not child.is_file() or child.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        video_count += 1
        if len(sample_video_files) < 3:
            sample_video_files.append(child.name)
        try:
            child_stat = child.stat()
        except OSError:
            continue
        total_size += int(child_stat.st_size)
        file_mtime = float(child_stat.st_mtime)
        if latest_mtime is None or file_mtime > latest_mtime:
            latest_mtime = file_mtime
            latest_file = child.name

    info["video_count"] = video_count
    info["video_size_bytes"] = total_size
    info["sample_video_files"] = sample_video_files
    info["latest_video_file"] = latest_file
    info["latest_video_mtime"] = latest_mtime
    return info
