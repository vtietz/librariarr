from __future__ import annotations

import os
import re
from fnmatch import fnmatch
from pathlib import Path

SEASON_DIR_RE = re.compile(r"^(?:season|staffel)\s*\d{1,2}$|^s\d{1,2}$", re.IGNORECASE)
EPISODE_TOKEN_RE = re.compile(r"\bs\d{1,2}e\d{1,3}\b", re.IGNORECASE)


def _contains_video_file(folder: Path, video_exts: set[str]) -> bool:
    if not folder.exists():
        return False
    try:
        for child in folder.iterdir():
            if child.is_file() and child.suffix.lower() in video_exts:
                return True
    except OSError:
        return False
    return False


def _contains_video_recursively(folder: Path, video_exts: set[str]) -> bool:
    if not folder.exists():
        return False
    for current, _dirs, files in os.walk(folder):
        if any(Path(filename).suffix.lower() in video_exts for filename in files):
            return True
        # Keep recursive walk for nested release layouts.
        if current != str(folder):
            continue
    return False


def _contains_video_recursively_filtered(
    folder: Path,
    root: Path,
    video_exts: set[str],
    exclude_patterns: list[str],
) -> bool:
    if not folder.exists():
        return False
    for current, dirs, files in os.walk(folder):
        cur_path = Path(current)
        if _is_excluded_path(cur_path, root, exclude_patterns, is_dir=True):
            dirs[:] = []
            continue
        dirs[:] = [
            dirname
            for dirname in dirs
            if not _is_excluded_path(cur_path / dirname, root, exclude_patterns, is_dir=True)
        ]
        if any(
            Path(filename).suffix.lower() in video_exts
            and not _is_excluded_path(cur_path / filename, root, exclude_patterns, is_dir=False)
            for filename in files
        ):
            return True
        if current != str(folder):
            continue
    return False


def _looks_like_episode_file(filename: str) -> bool:
    stem = Path(filename).stem
    return EPISODE_TOKEN_RE.search(stem) is not None


def _is_season_folder_name(name: str) -> bool:
    return SEASON_DIR_RE.match(name.strip()) is not None


def _normalize_exclude_patterns(exclude_patterns: list[str] | None) -> list[str]:
    if not exclude_patterns:
        return []
    normalized: list[str] = []
    for raw_pattern in exclude_patterns:
        pattern = str(raw_pattern).strip().replace("\\", "/")
        if not pattern or pattern.startswith("#"):
            continue
        if pattern.startswith("./"):
            pattern = pattern[2:]
        normalized.append(pattern)
    return normalized


def _is_excluded_path(
    path: Path,
    root: Path,
    patterns: list[str],
    *,
    is_dir: bool,
) -> bool:
    if not patterns:
        return False

    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.as_posix()

    if relative == ".":
        return False

    parts = [part for part in Path(relative).parts if part not in {".", ""}]
    suffix_candidates = ["/".join(parts[index:]) for index in range(len(parts))]
    basename = path.name
    relative_ci = relative.lower()
    basename_ci = basename.lower()
    suffix_candidates_ci = [candidate.lower() for candidate in suffix_candidates]

    for pattern in patterns:
        anchored = pattern.startswith("/")
        dir_only = pattern.endswith("/")
        core = pattern.strip("/")
        core_ci = core.lower()
        if not core:
            continue
        if dir_only and not is_dir:
            continue

        if anchored:
            if fnmatch(relative_ci, core_ci):
                return True
            continue

        if fnmatch(basename_ci, core_ci):
            return True
        if fnmatch(relative_ci, core_ci):
            return True
        if any(fnmatch(candidate, core_ci) for candidate in suffix_candidates_ci):
            return True

    return False


def discover_movie_folders(
    root: Path,
    video_exts: set[str],
    exclude_patterns: list[str] | None = None,
) -> set[Path]:
    found: set[Path] = set()
    if not root.exists():
        return found

    excludes = _normalize_exclude_patterns(exclude_patterns)

    for current, dirs, files in os.walk(root):
        cur_path = Path(current)
        if _is_excluded_path(cur_path, root, excludes, is_dir=True):
            dirs[:] = []
            continue

        dirs[:] = [
            dirname
            for dirname in dirs
            if not _is_excluded_path(cur_path / dirname, root, excludes, is_dir=True)
        ]

        if any(
            Path(filename).suffix.lower() in video_exts
            and not _is_excluded_path(cur_path / filename, root, excludes, is_dir=False)
            for filename in files
        ):
            if _is_season_folder_name(cur_path.name):
                continue
            found.add(cur_path)
            dirs[:] = []
    return found


def discover_series_folders(
    root: Path,
    video_exts: set[str],
    exclude_patterns: list[str] | None = None,
) -> set[Path]:
    found: set[Path] = set()
    if not root.exists():
        return found

    excludes = _normalize_exclude_patterns(exclude_patterns)

    for current, dirs, files in os.walk(root):
        cur_path = Path(current)

        if _is_excluded_path(cur_path, root, excludes, is_dir=True):
            dirs[:] = []
            continue

        dirs[:] = [
            dirname
            for dirname in dirs
            if not _is_excluded_path(cur_path / dirname, root, excludes, is_dir=True)
        ]

        # Flat-series fallback: treat folder as a series root when it contains episode files.
        if any(
            Path(filename).suffix.lower() in video_exts
            and _looks_like_episode_file(filename)
            and not _is_excluded_path(cur_path / filename, root, excludes, is_dir=False)
            for filename in files
        ):
            found.add(cur_path)
            dirs[:] = []
            continue

        season_dirs = [dirname for dirname in dirs if _is_season_folder_name(dirname)]
        if not season_dirs:
            continue

        has_video_in_season = False
        for season_dir in season_dirs:
            if _contains_video_recursively_filtered(
                cur_path / season_dir,
                root,
                video_exts,
                excludes,
            ):
                has_video_in_season = True
                break

        if has_video_in_season:
            found.add(cur_path)
            dirs[:] = []

    return found


def collect_current_links(shadow_roots: list[Path]) -> dict[Path, set[Path]]:
    out: dict[Path, set[Path]] = {}
    for shadow_root in shadow_roots:
        if not shadow_root.exists():
            continue

        for child in shadow_root.iterdir():
            if not child.is_symlink():
                continue
            try:
                target = child.resolve(strict=False)
            except OSError:
                continue
            out.setdefault(target, set()).add(child)
    return out
