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
        get_radarr_client: Callable[[], Any],
        resolve_movie_for_link_name: Callable[[str, dict[Any, dict]], dict | None],
        logger: logging.Logger | None = None,
    ) -> None:
        self.shadow_roots = shadow_roots
        self.sync_enabled = sync_enabled
        normalized_action = str(on_missing_action).strip().lower()
        if normalized_action not in {"none", "unmonitor", "delete"}:
            raise ValueError("on_missing_action must be one of: none, unmonitor, delete")
        self.on_missing_action = normalized_action
        self.missing_grace_seconds = max(0, int(missing_grace_seconds))
        self.get_radarr_client = get_radarr_client
        self.resolve_movie_for_link_name = resolve_movie_for_link_name
        self.log = logger or logging.getLogger(__name__)
        self._missing_since_by_movie_id: dict[int, float] = {}

    def _build_movies_by_id(self, movies_by_ref: dict[Any, dict]) -> dict[int, dict]:
        movies_by_id: dict[int, dict] = {}
        for movie in movies_by_ref.values():
            movie_id = movie.get("id")
            if isinstance(movie_id, int):
                movies_by_id.setdefault(movie_id, movie)
        return movies_by_id

    def _queue_missing_movie(self, movie_id: int) -> None:
        self._missing_since_by_movie_id.setdefault(movie_id, time.time())

    def _clear_pending_missing(self, movie_id: int) -> None:
        self._missing_since_by_movie_id.pop(movie_id, None)

    def _apply_pending_missing_actions(
        self,
        movies_by_ref: dict[Any, dict],
        matched_movie_ids: set[int],
    ) -> None:
        if not self.sync_enabled or self.on_missing_action == "none":
            self._missing_since_by_movie_id.clear()
            return

        if not self._missing_since_by_movie_id:
            return

        movies_by_id = self._build_movies_by_id(movies_by_ref)
        now = time.time()
        radarr = None

        for movie_id, first_missing_at in list(self._missing_since_by_movie_id.items()):
            if movie_id in matched_movie_ids:
                self._clear_pending_missing(movie_id)
                continue

            movie = movies_by_id.get(movie_id)
            if movie is None:
                self._clear_pending_missing(movie_id)
                continue

            elapsed = now - first_missing_at
            if elapsed < self.missing_grace_seconds:
                continue

            if radarr is None:
                radarr = self.get_radarr_client()

            if self.on_missing_action == "delete":
                radarr.delete_movie(movie_id, delete_files=False)
            else:
                radarr.unmonitor_movie(movie)
                radarr.refresh_movie(movie_id)
            self._clear_pending_missing(movie_id)

    def _queue_missing_action_for_link(
        self,
        link_name: str,
        movies_by_ref: dict[Any, dict],
        matched_movie_ids: set[int],
    ) -> None:
        if not self.sync_enabled or self.on_missing_action == "none":
            return

        movie = self.resolve_movie_for_link_name(link_name, movies_by_ref)
        if not movie:
            return

        movie_id = movie.get("id")
        if not isinstance(movie_id, int):
            return

        if movie_id in matched_movie_ids:
            self._clear_pending_missing(movie_id)
            return

        self._queue_missing_movie(movie_id)

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
                    movies_by_ref=movies_by_ref,
                    matched_movie_ids=matched_ids,
                )

        self._apply_pending_missing_actions(
            movies_by_ref=movies_by_ref,
            matched_movie_ids=matched_ids,
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
                    movies_by_ref=movies_by_ref,
                    matched_movie_ids=matched_ids,
                )

        return removed_count
