from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MediaScope:
    folders: dict[Path, Path]
    all_folders: dict[Path, Path]
    affected_targets: set[Path]
    incremental_mode: bool


@dataclass(frozen=True)
class ReconcilePlan:
    mode: str
    affected_paths_count: int | str
    movie_scope: MediaScope
    series_scope: MediaScope
    fetch_movie_index: bool
    fetch_series_index: bool


@dataclass(frozen=True)
class MediaReconcileOutcome:
    created_links: int
    matched_items: int
    unmatched_items: int
    matched_item_ids: set[int]
