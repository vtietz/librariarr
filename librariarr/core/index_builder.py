from __future__ import annotations

from .plan import MediaScope


def should_fetch_arr_index(sync_enabled: bool, scope: MediaScope) -> bool:
    if not sync_enabled:
        return False
    if not scope.incremental_mode:
        return True
    return bool(scope.folders) or bool(scope.affected_targets)
