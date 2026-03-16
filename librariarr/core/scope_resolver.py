from __future__ import annotations

from pathlib import Path


def resolve_reconcile_mode(affected_paths: set[Path] | None) -> tuple[str, int | str]:
    reconcile_mode = "incremental" if affected_paths is not None else "full"
    affected_paths_count: int | str = len(affected_paths) if affected_paths is not None else "all"
    return reconcile_mode, affected_paths_count
