from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path


def soft_delete_unmanaged_shadow_video_files(
    *,
    movie_projection,
    sonarr_projection,
    movie_candidate_ids: set[int],
    series_candidate_ids: set[int],
    video_exts: set[str],
) -> int:
    """Move untracked shadow videos in projected folders to .deletedByLibrariarr.

    Safety rules:
    - never touch managed roots (only projection destination folders are examined),
    - only touch video files under folders that already contain tracked projected files,
    - use soft-delete (rename/move) instead of unlink so data is never removed immediately.
    """
    tracked_destinations, tracked_parent_dirs = tracked_projection_destinations_and_parents(
        movie_projection=movie_projection,
        sonarr_projection=sonarr_projection,
        movie_candidate_ids=movie_candidate_ids,
        series_candidate_ids=series_candidate_ids,
    )
    if not tracked_parent_dirs:
        return 0

    moved = 0
    for parent_dir in sorted(tracked_parent_dirs, key=lambda path: str(path)):
        if not parent_dir.exists() or not parent_dir.is_dir():
            continue
        recycle_root = resolve_shadow_recycle_root(parent_dir)
        if recycle_root is None:
            continue

        for entry in sorted(parent_dir.iterdir(), key=lambda path: path.name):
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in video_exts:
                continue

            file_path = entry.resolve(strict=False)
            if file_path in tracked_destinations:
                continue
            if is_under_path(file_path, recycle_root):
                continue

            recycle_target = build_shadow_soft_delete_target(file_path, recycle_root)
            recycle_target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(file_path), str(recycle_target))
            except OSError:
                continue
            moved += 1

    return moved


def tracked_projection_destinations_and_parents(
    *,
    movie_projection,
    sonarr_projection,
    movie_candidate_ids: set[int],
    series_candidate_ids: set[int],
) -> tuple[set[Path], set[Path]]:
    destinations: set[Path] = set()
    parents: set[Path] = set()

    rows: list[tuple[int, str, str, int | None, int | None]] = []
    if movie_projection is not None and movie_candidate_ids:
        rows.extend(
            movie_projection.state_store.list_managed_projected_rows(movie_ids=movie_candidate_ids)
        )
    if sonarr_projection is not None and series_candidate_ids:
        rows.extend(
            sonarr_projection.state_store.list_managed_projected_rows(
                movie_ids=series_candidate_ids
            )
        )

    for _item_id, dest_path_raw, _source_path_raw, _source_dev, _source_inode in rows:
        dest_path = Path(dest_path_raw).resolve(strict=False)
        destinations.add(dest_path)
        parents.add(dest_path.parent)

    return destinations, parents


def resolve_shadow_recycle_root(path: Path) -> Path | None:
    for current in (path, *path.parents):
        if current.name == ".deletedByLibrariarr":
            return current
        if current.name == ".librariarr":
            return current / ".deletedByLibrariarr"
    return None


def build_shadow_soft_delete_target(path: Path, recycle_root: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    if is_under_path(path, recycle_root):
        return path

    try:
        shadow_anchor = recycle_root.parent
        relative = path.relative_to(shadow_anchor)
    except ValueError:
        relative = Path(path.name)

    candidate = recycle_root / relative.with_name(f"{relative.name}.{timestamp}")
    suffix = 1
    while candidate.exists():
        candidate = recycle_root / relative.with_name(f"{relative.name}.{timestamp}.{suffix}")
        suffix += 1
    return candidate


def is_under_path(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
