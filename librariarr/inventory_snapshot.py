from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class InventorySnapshot:
    movies: list[dict[str, Any]] = field(default_factory=list)
    series: list[dict[str, Any]] = field(default_factory=list)
    timestamp: float = 0.0


class InventorySnapshotStore:
    """Thread-safe copy-on-write snapshot of Arr inventories.

    Reconcile writes a new snapshot (full reference replacement).
    Dashboard reads the current snapshot without locking.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot = InventorySnapshot()

    def update(
        self,
        *,
        movies: list[dict[str, Any]] | None = None,
        series: list[dict[str, Any]] | None = None,
        timestamp: float,
    ) -> None:
        with self._lock:
            self._snapshot = InventorySnapshot(
                movies=movies if movies is not None else self._snapshot.movies,
                series=series if series is not None else self._snapshot.series,
                timestamp=timestamp,
            )

    @property
    def snapshot(self) -> InventorySnapshot:
        return self._snapshot


_global_store: InventorySnapshotStore | None = None
_global_store_lock = threading.Lock()


def get_inventory_snapshot_store() -> InventorySnapshotStore:
    global _global_store
    if _global_store is None:
        with _global_store_lock:
            if _global_store is None:
                _global_store = InventorySnapshotStore()
    return _global_store


def reset_inventory_snapshot_store() -> None:
    global _global_store
    with _global_store_lock:
        _global_store = None
