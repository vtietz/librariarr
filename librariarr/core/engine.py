"""Reconcile engine: wires config, Arr clients, cache, and the two flows.

Scopes:
- ``consistency``: no tree walk; cache + stat verification per Arr item.
  Cheap enough to run on every webhook and short interval.
- ``full``: builds the inode index (one walk), additionally resolves unknown
  items, runs discovery/auto-add, and prunes stale library/shadow folders.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from ..config.models import AppConfig
from .discovery import MovieDiscovery, SeriesDiscovery
from .index import AdvisoryCache, InodeIndex
from .model import ReconcileReport
from .movies import MovieReconciler
from .series import SeriesReconciler

LOG = logging.getLogger(__name__)

SCOPE_CONSISTENCY = "consistency"
SCOPE_FULL = "full"

_UNSET = object()


def default_cache_path(config_path: str | Path | None = None) -> Path:
    configured = str(os.getenv("LIBRARIARR_STATE_PATH", "")).strip()
    if configured:
        return Path(configured).with_name("librariarr-idcache.json")
    base = Path(config_path) if config_path else Path("/config/config.yaml")
    return base.with_name("librariarr-idcache.json")


class ReconcileEngine:
    def __init__(
        self,
        config: AppConfig,
        *,
        radarr=_UNSET,
        sonarr=_UNSET,
        cache: AdvisoryCache | None = None,
        cache_path: Path | None = None,
    ) -> None:
        self.config = config
        self.radarr = self._build_radarr(config) if radarr is _UNSET else radarr
        self.sonarr = self._build_sonarr(config) if sonarr is _UNSET else sonarr
        self.cache = cache or AdvisoryCache(cache_path or default_cache_path())

    @staticmethod
    def _build_radarr(config: AppConfig):
        if not config.radarr.enabled or not config.radarr.sync_enabled:
            return None
        from ..clients.radarr import RadarrClient

        return RadarrClient(
            base_url=config.radarr.url,
            api_key=config.radarr.api_key,
            timeout=config.radarr.request_timeout_seconds,
            retry_attempts=config.radarr.request_retry_attempts,
            retry_backoff_seconds=config.radarr.request_retry_backoff_seconds,
        )

    @staticmethod
    def _build_sonarr(config: AppConfig):
        if not config.sonarr.enabled or not config.sonarr.sync_enabled:
            return None
        from ..clients.sonarr import SonarrClient

        return SonarrClient(
            base_url=config.sonarr.url,
            api_key=config.sonarr.api_key,
            timeout=config.sonarr.request_timeout_seconds,
            retry_attempts=config.sonarr.request_retry_attempts,
            retry_backoff_seconds=config.sonarr.request_retry_backoff_seconds,
        )

    # ------------------------------------------------------------------

    def run(
        self,
        *,
        scope: str = SCOPE_CONSISTENCY,
        dry_run: bool = False,
        progress=None,
    ) -> ReconcileReport:
        started = time.monotonic()
        report = ReconcileReport(dry_run=dry_run, scope=scope)
        tick = progress or (lambda phase, current, total: None)
        index = None
        if scope == SCOPE_FULL:
            tick("scanning managed tree", 0, 0)
            index = self._build_index()
            report.stats["managed_video_files"] = len(index)

        if self.radarr is not None:
            try:
                movies, movie_inodes = MovieReconciler(
                    self.config, self.radarr, self.cache
                ).reconcile(report, index=index, dry_run=dry_run, progress=tick)
                if scope == SCOPE_FULL:
                    MovieDiscovery(self.config, self.radarr, self.cache).run(
                        movies, movie_inodes, report, dry_run, progress=tick
                    )
            except Exception as exc:  # noqa: BLE001 - keep Sonarr running on Radarr failure
                LOG.exception("Radarr reconcile failed")
                report.errors.append(f"radarr: {exc}")

        if self.sonarr is not None:
            try:
                series_list, series_inodes = SeriesReconciler(
                    self.config, self.sonarr, self.cache
                ).reconcile(report, index=index, dry_run=dry_run, progress=tick)
                if scope == SCOPE_FULL:
                    SeriesDiscovery(self.config, self.sonarr, self.cache).run(
                        series_list, series_inodes, report, dry_run, progress=tick
                    )
            except Exception as exc:  # noqa: BLE001
                LOG.exception("Sonarr reconcile failed")
                report.errors.append(f"sonarr: {exc}")

        if not dry_run:
            self.cache.save()
        report.duration_seconds = time.monotonic() - started
        LOG.info(
            "Reconcile done: scope=%s dry_run=%s items=%d changed=%d "
            "unmatched=%d warnings=%d errors=%d (%.2fs)",
            scope,
            dry_run,
            report.items_seen,
            report.items_changed,
            len(report.unmatched),
            len(report.warnings),
            len(report.errors),
            report.duration_seconds,
        )
        return report

    def manual_add(self, path: str) -> dict:
        """User-initiated add of one managed folder to the matching Arr.

        Returns {"ok": bool, ...} with either the performed actions or the
        reason the folder cannot be added (so the UI can show *why*).
        """
        from .discovery import MovieDiscovery, SeriesDiscovery
        from .fsops import is_within

        folder = Path(path)
        if not folder.is_dir():
            return {"ok": False, "reason": "not_found", "detail": f"Not a directory: {folder}"}
        report = ReconcileReport(scope="manual-add")

        try:
            if self.radarr is not None:
                for mapping in self.config.paths.movie_root_mappings:
                    if is_within(folder, Path(mapping.managed_root)):
                        MovieDiscovery(self.config, self.radarr, self.cache).manual_add(
                            folder, Path(mapping.library_root), report
                        )
                        return self._manual_add_outcome(report)
            if self.sonarr is not None:
                for mapping in self.config.paths.series_root_mappings:
                    if is_within(folder, Path(mapping.managed_root)):
                        SeriesDiscovery(self.config, self.sonarr, self.cache).manual_add(
                            folder, Path(mapping.library_root), report
                        )
                        return self._manual_add_outcome(report)
        except Exception as exc:  # noqa: BLE001 - surface the error to the user
            LOG.exception("Manual add failed for %s", folder)
            return {"ok": False, "reason": "error", "detail": str(exc)}
        return {
            "ok": False,
            "reason": "outside_roots",
            "detail": "Folder is not under any configured managed root (or that Arr is disabled).",
        }

    @staticmethod
    def _manual_add_outcome(report: ReconcileReport) -> dict:
        if report.unmatched:
            entry = report.unmatched[0]
            return {
                "ok": False,
                "reason": entry.reason,
                "detail": "; ".join(entry.candidates) or None,
                "candidates": entry.candidates,
                "parsed_title": entry.parsed_title,
                "parsed_year": entry.parsed_year,
            }
        return {
            "ok": True,
            "actions": [f"{a.kind}: {a.detail}" for a in report.actions],
        }

    def _build_index(self) -> InodeIndex:
        roots: list[Path] = []
        extensions: set[str] = set()
        if self.radarr is not None:
            roots.extend(Path(m.managed_root) for m in self.config.paths.movie_root_mappings)
            extensions.update(self.config.radarr.projection.managed_video_extensions)
        if self.sonarr is not None:
            roots.extend(Path(m.managed_root) for m in self.config.paths.series_root_mappings)
            extensions.update(self.config.sonarr.projection.managed_video_extensions)
        index = InodeIndex.build(roots, sorted(extensions), self.config.paths.exclude_paths)
        LOG.debug("Inode index built: %d video inodes across %d roots", len(index), len(roots))
        return index
