from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any


class ShadowCleanupManager:
    def __init__(
        self,
        shadow_roots: list[Path],
        sync_enabled: bool,
        unmonitor_on_delete: bool,
        delete_from_radarr_on_missing: bool,
        get_radarr_client: Callable[[], Any],
        resolve_movie_for_link_name: Callable[[str, dict[Any, dict]], dict | None],
        logger: logging.Logger | None = None,
    ) -> None:
        self.shadow_roots = shadow_roots
        self.sync_enabled = sync_enabled
        self.unmonitor_on_delete = unmonitor_on_delete
        self.delete_from_radarr_on_missing = delete_from_radarr_on_missing
        self.get_radarr_client = get_radarr_client
        self.resolve_movie_for_link_name = resolve_movie_for_link_name
        self.log = logger or logging.getLogger(__name__)

    def cleanup_orphans(
        self,
        existing_folders: set[Path],
        movies_by_ref: dict[Any, dict],
        expected_links: set[Path],
    ) -> int:
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
                self.log.info("Removed orphaned symlink: %s", child)

                if target_exists:
                    continue
                if not self.sync_enabled:
                    continue
                if not self.unmonitor_on_delete:
                    continue

                radarr = self.get_radarr_client()
                movie = self.resolve_movie_for_link_name(child.name, movies_by_ref)
                if not movie:
                    continue

                if self.delete_from_radarr_on_missing:
                    radarr.delete_movie(int(movie["id"]), delete_files=False)
                    continue
                radarr.unmonitor_movie(movie)
                radarr.refresh_movie(int(movie["id"]))

        return removed_count
