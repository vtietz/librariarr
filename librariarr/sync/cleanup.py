from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


class ShadowCleanupManager:
    def __init__(
        self,
        shadow_roots: list[Path],
        sync_enabled: bool,
        on_missing_action: str,
        missing_grace_seconds: int,
        get_arr_client: Callable[[], Any],
        resolve_item_for_link_name: Callable[[str, dict[Any, dict]], dict | None],
        unmonitor_item: Callable[[Any, dict], None],
        delete_item: Callable[[Any, int], None],
        refresh_item: Callable[[Any, int], None],
        logger: logging.Logger | None = None,
    ) -> None:
        self.shadow_roots = shadow_roots
        self.sync_enabled = sync_enabled
        normalized_action = str(on_missing_action).strip().lower()
        if normalized_action not in {"none", "unmonitor", "delete"}:
            raise ValueError("on_missing_action must be one of: none, unmonitor, delete")
        self.on_missing_action = normalized_action
        self.missing_grace_seconds = max(0, int(missing_grace_seconds))
        self.get_arr_client = get_arr_client
        self.resolve_item_for_link_name = resolve_item_for_link_name
        self.unmonitor_item = unmonitor_item
        self.delete_item = delete_item
        self.refresh_item = refresh_item
        self.log = logger or logging.getLogger(__name__)
        self._missing_since_by_item_id: dict[int, float] = {}

    def _build_items_by_id(self, items_by_ref: dict[Any, dict]) -> dict[int, dict]:
        items_by_id: dict[int, dict] = {}
        for item in items_by_ref.values():
            item_id = item.get("id")
            if isinstance(item_id, int):
                items_by_id.setdefault(item_id, item)
        return items_by_id

    def _queue_missing_item(self, item_id: int) -> None:
        self._missing_since_by_item_id.setdefault(item_id, time.time())

    def _clear_pending_missing(self, item_id: int) -> None:
        self._missing_since_by_item_id.pop(item_id, None)

    def _apply_pending_missing_actions(
        self,
        items_by_ref: dict[Any, dict],
        matched_item_ids: set[int],
    ) -> None:
        if not self.sync_enabled or self.on_missing_action == "none":
            self._missing_since_by_item_id.clear()
            return

        if not self._missing_since_by_item_id:
            return

        items_by_id = self._build_items_by_id(items_by_ref)
        now = time.time()
        arr_client = None

        for item_id, first_missing_at in list(self._missing_since_by_item_id.items()):
            if item_id in matched_item_ids:
                self._clear_pending_missing(item_id)
                continue

            item = items_by_id.get(item_id)
            if item is None:
                self._clear_pending_missing(item_id)
                continue

            elapsed = now - first_missing_at
            if elapsed < self.missing_grace_seconds:
                continue

            if arr_client is None:
                arr_client = self.get_arr_client()

            if self.on_missing_action == "delete":
                self.delete_item(arr_client, item_id)
            else:
                self.unmonitor_item(arr_client, item)
                self.refresh_item(arr_client, item_id)
            self._clear_pending_missing(item_id)

    def _queue_missing_action_for_link(
        self,
        link_name: str,
        items_by_ref: dict[Any, dict],
        matched_item_ids: set[int],
    ) -> None:
        if not self.sync_enabled or self.on_missing_action == "none":
            return

        item = self.resolve_item_for_link_name(link_name, items_by_ref)
        if not item:
            return

        item_id = item.get("id")
        if not isinstance(item_id, int):
            return

        if item_id in matched_item_ids:
            self._clear_pending_missing(item_id)
            return

        self._queue_missing_item(item_id)

    def cleanup_orphans(
        self,
        existing_folders: set[Path],
        movies_by_ref: dict[Any, dict],
        expected_links: set[Path],
        matched_movie_ids: set[int] | None = None,
    ) -> int:
        matched_ids = matched_movie_ids or set()
        removed_count = 0
        for shadow_root in self.shadow_roots:
            if not shadow_root.exists():
                continue

            for child in shadow_root.iterdir():
                if not child.is_symlink():
                    continue

                try:
                    target = child.resolve(strict=False)
                except OSError:
                    target = None

                target_exists = target is not None and target in existing_folders
                link_is_expected = child in expected_links
                if target_exists and link_is_expected:
                    continue

                child.unlink(missing_ok=True)
                removed_count += 1
                if target_exists:
                    self.log.debug("Removed stale symlink: %s", child)
                else:
                    self.log.info("Removed orphaned symlink: %s", child)

                if target_exists:
                    continue
                self._queue_missing_action_for_link(
                    link_name=child.name,
                    items_by_ref=movies_by_ref,
                    matched_item_ids=matched_ids,
                )

        self._apply_pending_missing_actions(
            items_by_ref=movies_by_ref,
            matched_item_ids=matched_ids,
        )

        return removed_count

    def cleanup_orphans_for_targets(
        self,
        existing_folders: set[Path],
        movies_by_ref: dict[Any, dict],
        expected_links: set[Path],
        affected_targets: set[Path],
        matched_movie_ids: set[int] | None = None,
    ) -> int:
        if not affected_targets:
            return 0

        matched_ids = matched_movie_ids or set()
        removed_count = 0
        for shadow_root in self.shadow_roots:
            if not shadow_root.exists():
                continue

            for child in shadow_root.iterdir():
                if not child.is_symlink():
                    continue

                try:
                    target = child.resolve(strict=False)
                except OSError:
                    target = None

                if target is None or target not in affected_targets:
                    continue

                target_exists = target in existing_folders
                link_is_expected = child in expected_links
                if target_exists and link_is_expected:
                    continue

                child.unlink(missing_ok=True)
                removed_count += 1
                if target_exists:
                    self.log.debug("Removed stale symlink: %s", child)
                else:
                    self.log.info("Removed orphaned symlink: %s", child)

                if target_exists:
                    continue
                self._queue_missing_action_for_link(
                    link_name=child.name,
                    items_by_ref=movies_by_ref,
                    matched_item_ids=matched_ids,
                )

        self._apply_pending_missing_actions(
            items_by_ref=movies_by_ref,
            matched_item_ids=matched_ids,
        )

        return removed_count
