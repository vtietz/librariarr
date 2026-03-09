from __future__ import annotations

import os
from pathlib import Path


def discover_movie_folders(root: Path, video_exts: set[str]) -> set[Path]:
    found: set[Path] = set()
    if not root.exists():
        return found

    for current, dirs, files in os.walk(root):
        cur_path = Path(current)
        if any(Path(filename).suffix.lower() in video_exts for filename in files):
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
