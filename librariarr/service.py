from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import requests

from .config import AppConfig
from .quality import VIDEO_EXTENSIONS, map_quality_id
from .radarr import RadarrClient
from .runtime import ReconcileSchedule, RuntimeSyncLoop
from .sonarr import SonarrClient
from .sync import (
    MovieRef,
    RadarrSyncHelper,
    ShadowCleanupManager,
    ShadowIngestor,
    ShadowLinkManager,
    SonarrSyncHelper,
    collect_current_links,
    discover_movie_folders,
    discover_series_folders,
    parse_movie_ref,
)

LOG = logging.getLogger(__name__)
TITLE_TOKEN_RE = re.compile(r"[^a-z0-9]+")
IMDB_ID_RE = re.compile(r"\btt\d{5,10}\b", re.IGNORECASE)
IMDB_NEAR_TOKEN_RE = re.compile(r"(?:imdb)(?:id)?[^a-z0-9]{0,16}(tt\d{5,10})", re.IGNORECASE)
TMDB_ID_RE = re.compile(
    r"(?:tmdb|themoviedb)(?:id)?[^0-9]{0,16}(\d{2,})",
    re.IGNORECASE,
)
TMDB_UNIQUE_ID_RE = re.compile(
    r"<\s*uniqueid[^>]*type\s*=\s*[\"']tmdb[\"'][^>]*>\s*(\d{2,})\s*<",
    re.IGNORECASE,
)
TVDB_ID_RE = re.compile(
    r"(?:tvdb)(?:id)?[^0-9]{0,16}(\d{2,})",
    re.IGNORECASE,
)
TVDB_UNIQUE_ID_RE = re.compile(
    r"<\s*uniqueid[^>]*type\s*=\s*[\"']tvdb[\"'][^>]*>\s*(\d{2,})\s*<",
    re.IGNORECASE,
)
IMDB_UNIQUE_ID_RE = re.compile(
    r"<\s*uniqueid[^>]*type\s*=\s*[\"']imdb[\"'][^>]*>\s*(tt\d{5,10})\s*<",
    re.IGNORECASE,
)


class LibrariArrService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.radarr_enabled = config.radarr.enabled
        self.sync_enabled = config.radarr.enabled and config.radarr.sync_enabled
        self.auto_add_unmatched = config.radarr.enabled and config.radarr.auto_add_unmatched
        self.sonarr_enabled = config.sonarr.enabled
        self.sonarr_sync_enabled = config.sonarr.enabled and config.sonarr.sync_enabled
        self.sonarr_auto_add_unmatched = config.sonarr.enabled and config.sonarr.auto_add_unmatched
        self.radarr = RadarrClient(
            config.radarr.url,
            config.radarr.api_key,
            refresh_debounce_seconds=config.radarr.refresh_debounce_seconds,
        )
        self.sonarr = SonarrClient(
            config.sonarr.url,
            config.sonarr.api_key,
            refresh_debounce_seconds=config.sonarr.refresh_debounce_seconds,
        )
        self.radarr_sync = RadarrSyncHelper(
            config=config,
            logger=LOG,
            get_radarr_client=lambda: self.radarr,
        )
        self.sonarr_sync = SonarrSyncHelper(
            config=config,
            logger=LOG,
            get_sonarr_client=lambda: self.sonarr,
        )
        self.root_mappings = self._build_root_mappings(config)
        self.nested_roots = [nested for nested, _ in self.root_mappings]
        self.shadow_roots = self._unique_paths([shadow for _, shadow in self.root_mappings])
        self.shadow_to_nested_roots = self._build_shadow_to_nested_roots(self.root_mappings)
        self._validate_ingest_root_mappings(config.ingest.enabled)
        self.video_exts = set(config.runtime.scan_video_extensions or VIDEO_EXTENSIONS)
        self.link_manager = ShadowLinkManager(self.nested_roots, logger=LOG)
        self.ingestor = ShadowIngestor(
            config=config.ingest,
            video_exts=self.video_exts,
            shadow_roots=self.shadow_roots,
            shadow_to_nested_roots=self.shadow_to_nested_roots,
            logger=LOG,
        )
        self.cleanup_manager = ShadowCleanupManager(
            shadow_roots=self.shadow_roots,
            sync_enabled=self.sync_enabled,
            unmonitor_on_delete=config.cleanup.unmonitor_on_delete,
            delete_from_radarr_on_missing=config.cleanup.delete_from_radarr_on_missing,
            missing_grace_seconds=config.cleanup.missing_grace_seconds,
            get_radarr_client=lambda: self.radarr,
            resolve_movie_for_link_name=self._resolve_movie_for_link_name,
            logger=LOG,
        )
        self.sonarr_cleanup_manager = ShadowCleanupManager(
            shadow_roots=self.shadow_roots,
            sync_enabled=self.sonarr_sync_enabled,
            unmonitor_on_delete=config.cleanup.unmonitor_on_delete,
            delete_from_radarr_on_missing=config.cleanup.delete_from_sonarr_on_missing,
            missing_grace_seconds=config.cleanup.missing_grace_seconds,
            get_radarr_client=lambda: self.sonarr,
            resolve_movie_for_link_name=self._resolve_series_for_link_name,
            logger=LOG,
        )

        self._debounce_seconds = max(1, config.runtime.debounce_seconds)
        maintenance_minutes = config.runtime.maintenance_interval_minutes
        # 0 or negative disables periodic maintenance; startup + FS events still run.
        self._maintenance_interval = (
            None if maintenance_minutes <= 0 else max(60, maintenance_minutes * 60)
        )
        self._lock = threading.Lock()
        self._sync_hint_logged = False
        self._sonarr_sync_hint_logged = False
        self._known_movie_folders: dict[Path, Path] | None = None
        self._known_series_folders: dict[Path, Path] | None = None

    def _log_arr_sync_config_hints(self, exc: Exception) -> None:
        self._log_sync_config_hint(exc)
        self._log_sonarr_sync_config_hint(exc)

    def _log_sync_config_hint(self, exc: Exception) -> None:
        if not self.sync_enabled or self._sync_hint_logged:
            return

        request_exc = self._extract_request_exception(exc)
        if request_exc is None:
            return

        if isinstance(request_exc, requests.HTTPError):
            status_code = (
                request_exc.response.status_code if request_exc.response is not None else None
            )
            if status_code in (401, 403):
                LOG.error(
                    "Radarr API auth failed while sync is enabled (status=%s). "
                    "Review radarr.url/radarr.api_key (or LIBRARIARR_RADARR_URL/"
                    "LIBRARIARR_RADARR_API_KEY), or set radarr.sync_enabled=false "
                    "for filesystem-only mode.",
                    status_code,
                )
                self._sync_hint_logged = True
                return

            if status_code is not None:
                LOG.warning(
                    "Radarr API request failed while sync is enabled (status=%s). "
                    "Review Radarr URL/API key, or disable sync for filesystem-only mode. "
                    "url=%s",
                    status_code,
                    self.config.radarr.url,
                )
                self._sync_hint_logged = True
                return

        if isinstance(request_exc, requests.ConnectionError):
            LOG.warning(
                "Radarr is unreachable while sync is enabled. "
                "Review radarr.url/network/API key, or set radarr.sync_enabled=false "
                "for filesystem-only mode. url=%s error=%s",
                self.config.radarr.url,
                request_exc,
            )
            self._sync_hint_logged = True
            return

        if isinstance(request_exc, requests.Timeout):
            LOG.warning(
                "Radarr request timed out while sync is enabled. "
                "Review radarr.url/network latency/API key, or set "
                "radarr.sync_enabled=false for filesystem-only mode. "
                "url=%s error=%s",
                self.config.radarr.url,
                request_exc,
            )
            self._sync_hint_logged = True
            return

        LOG.warning(
            "Radarr is unreachable while sync is enabled. Review radarr.url/network/API key, "
            "or set radarr.sync_enabled=false for filesystem-only mode. "
            "url=%s error_type=%s",
            self.config.radarr.url,
            type(request_exc).__name__,
        )
        self._sync_hint_logged = True

    def _log_sonarr_sync_config_hint(self, exc: Exception) -> None:
        if not self.sonarr_sync_enabled or self._sonarr_sync_hint_logged:
            return

        request_exc = self._extract_request_exception(exc)
        if request_exc is None:
            return

        if isinstance(request_exc, requests.HTTPError):
            status_code = (
                request_exc.response.status_code if request_exc.response is not None else None
            )
            if status_code in (401, 403):
                LOG.error(
                    "Sonarr API auth failed while sync is enabled (status=%s). "
                    "Review sonarr.url/sonarr.api_key (or LIBRARIARR_SONARR_URL/"
                    "LIBRARIARR_SONARR_API_KEY), or set sonarr.sync_enabled=false "
                    "for filesystem-only mode.",
                    status_code,
                )
                self._sonarr_sync_hint_logged = True
                return

            if status_code is not None:
                LOG.warning(
                    "Sonarr API request failed while sync is enabled (status=%s). "
                    "Review Sonarr URL/API key, or disable sync for filesystem-only mode. "
                    "url=%s",
                    status_code,
                    self.config.sonarr.url,
                )
                self._sonarr_sync_hint_logged = True
                return

        if isinstance(request_exc, requests.ConnectionError):
            LOG.warning(
                "Sonarr is unreachable while sync is enabled. "
                "Review sonarr.url/network/API key, or set sonarr.sync_enabled=false "
                "for filesystem-only mode. url=%s error=%s",
                self.config.sonarr.url,
                request_exc,
            )
            self._sonarr_sync_hint_logged = True
            return

        if isinstance(request_exc, requests.Timeout):
            LOG.warning(
                "Sonarr request timed out while sync is enabled. "
                "Review sonarr.url/network latency/API key, or set "
                "sonarr.sync_enabled=false for filesystem-only mode. "
                "url=%s error=%s",
                self.config.sonarr.url,
                request_exc,
            )
            self._sonarr_sync_hint_logged = True
            return

        LOG.warning(
            "Sonarr is unreachable while sync is enabled. Review sonarr.url/network/API key, "
            "or set sonarr.sync_enabled=false for filesystem-only mode. "
            "url=%s error_type=%s",
            self.config.sonarr.url,
            type(request_exc).__name__,
        )
        self._sonarr_sync_hint_logged = True

    def _extract_request_exception(self, exc: Exception) -> requests.RequestException | None:
        current: BaseException | None = exc
        seen: set[int] = set()

        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, requests.RequestException):
                return current
            current = current.__cause__ or current.__context__
        return None

    def _build_root_mappings(self, config: AppConfig) -> list[tuple[Path, Path]]:
        return [
            (Path(item.nested_root), Path(item.shadow_root)) for item in config.paths.root_mappings
        ]

    def _unique_paths(self, paths: list[Path]) -> list[Path]:
        seen: set[Path] = set()
        ordered: list[Path] = []
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            ordered.append(path)
        return ordered

    def _build_shadow_to_nested_roots(
        self,
        mappings: list[tuple[Path, Path]],
    ) -> dict[Path, list[Path]]:
        out: dict[Path, list[Path]] = {}
        for nested_root, shadow_root in mappings:
            out.setdefault(shadow_root, [])
            if nested_root not in out[shadow_root]:
                out[shadow_root].append(nested_root)
        return out

    def _validate_ingest_root_mappings(self, ingest_enabled: bool) -> None:
        if not ingest_enabled:
            return

        ambiguous = [
            shadow_root
            for shadow_root, nested_roots in self.shadow_to_nested_roots.items()
            if len(nested_roots) != 1
        ]
        if not ambiguous:
            return

        roots = ", ".join(str(root) for root in sorted(ambiguous))
        raise ValueError(
            "Ingest requires a 1:1 mapping between each shadow root and nested root. "
            f"Ambiguous shadow roots: {roots}. Use paths.root_mappings with unique "
            "shadow_root values when ingest is enabled."
        )

    def run(self) -> None:
        LOG.info(
            "Starting LibrariArr service: shadow_roots=%s nested_roots=%s "
            "radarr_enabled=%s sync_enabled=%s auto_add_unmatched=%s debounce_seconds=%s "
            "sonarr_enabled=%s sonarr_sync_enabled=%s sonarr_auto_add_unmatched=%s "
            "maintenance_interval_seconds=%s",
            ",".join(str(root) for root in self.shadow_roots),
            ",".join(str(root) for root in self.nested_roots),
            self.radarr_enabled,
            self.sync_enabled,
            self.auto_add_unmatched,
            self._debounce_seconds,
            self.sonarr_enabled,
            self.sonarr_sync_enabled,
            self.sonarr_auto_add_unmatched,
            self._maintenance_interval if self._maintenance_interval is not None else "disabled",
        )
        for shadow_root in self.shadow_roots:
            shadow_root.mkdir(parents=True, exist_ok=True)
        self._run_sync_preflight_checks()
        runtime_loop = RuntimeSyncLoop(
            nested_roots=self.nested_roots,
            shadow_roots=self.shadow_roots,
            schedule=ReconcileSchedule(
                debounce_seconds=self._debounce_seconds,
                maintenance_interval_seconds=self._maintenance_interval,
            ),
            reconcile=self.reconcile,
            on_reconcile_error=self._log_arr_sync_config_hints,
            logger=LOG,
        )
        runtime_loop.run()

    def _run_sync_preflight_checks(self) -> None:
        if not self.radarr_enabled:
            self._run_sonarr_preflight_checks()
            return

        if not self.sync_enabled:
            self._run_sonarr_preflight_checks()
            return

        parsed_url = urlparse(self.config.radarr.url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            LOG.warning(
                "Radarr URL sanity check failed while sync is enabled. "
                "Expected an absolute http(s) URL. current_url=%s",
                self.config.radarr.url,
            )

        if not self.config.radarr.api_key.strip():
            LOG.warning(
                "Radarr sync is enabled but radarr.api_key is empty. "
                "Set radarr.api_key (or LIBRARIARR_RADARR_API_KEY) or disable sync."
            )

        if parsed_url.hostname in {"localhost", "127.0.0.1", "::1"}:
            LOG.warning(
                "Radarr URL uses localhost while sync is enabled (url=%s). "
                "If LibrariArr runs in Docker, localhost points to the LibrariArr container.",
                self.config.radarr.url,
            )

        try:
            status = self.radarr.get_system_status()
            version = str(status.get("version", "unknown"))
            app_name = str(status.get("appName", "Radarr"))
            LOG.info(
                "Radarr preflight check succeeded: app=%s version=%s url=%s",
                app_name,
                version,
                self.config.radarr.url,
            )
            self.radarr_sync.log_quality_mapping_diagnostics(
                auto_add_unmatched=self.auto_add_unmatched,
            )
        except Exception as exc:
            self._log_sync_config_hint(exc)
            request_exc = self._extract_request_exception(exc)
            detail = request_exc if request_exc is not None else exc
            LOG.warning(
                "Radarr preflight check failed; initial reconcile may fail as well. "
                "url=%s error=%s",
                self.config.radarr.url,
                detail,
            )
        self._run_sonarr_preflight_checks()

    def _run_sonarr_preflight_checks(self) -> None:
        if not self.sonarr_sync_enabled:
            return

        parsed_url = urlparse(self.config.sonarr.url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            LOG.warning(
                "Sonarr URL sanity check failed while sync is enabled. "
                "Expected an absolute http(s) URL. current_url=%s",
                self.config.sonarr.url,
            )

        if not self.config.sonarr.api_key.strip():
            LOG.warning(
                "Sonarr sync is enabled but sonarr.api_key is empty. "
                "Set sonarr.api_key (or LIBRARIARR_SONARR_API_KEY) or disable sync."
            )

        if parsed_url.hostname in {"localhost", "127.0.0.1", "::1"}:
            LOG.warning(
                "Sonarr URL uses localhost while sync is enabled (url=%s). "
                "If LibrariArr runs in Docker, localhost points to the LibrariArr container.",
                self.config.sonarr.url,
            )

        try:
            status = self.sonarr.get_system_status()
            version = str(status.get("version", "unknown"))
            app_name = str(status.get("appName", "Sonarr"))
            LOG.info(
                "Sonarr preflight check succeeded: app=%s version=%s url=%s",
                app_name,
                version,
                self.config.sonarr.url,
            )
        except Exception as exc:
            self._log_sonarr_sync_config_hint(exc)
            request_exc = self._extract_request_exception(exc)
            detail = request_exc if request_exc is not None else exc
            LOG.warning(
                "Sonarr preflight check failed; initial reconcile may fail as well. "
                "url=%s error=%s",
                self.config.sonarr.url,
                detail,
            )

    def reconcile(self, affected_paths: set[Path] | None = None) -> bool:
        with self._lock:
            started = time.time()
            LOG.info("Reconciling shadow links and Arr state...")
            for shadow_root in self.shadow_roots:
                shadow_root.mkdir(parents=True, exist_ok=True)

            ingested_count = self.ingestor.run() if self.config.ingest.enabled else 0
            ingest_pending = False
            if self.config.ingest.enabled:
                ingest_pending = self.ingestor.last_pending_quiescent_count > 0

            movie_folders: dict[Path, Path] = {}
            all_movie_folders: dict[Path, Path] = {}
            movie_affected_targets: set[Path] = set()
            movie_incremental_mode = False
            if self.radarr_enabled:
                (
                    movie_folders,
                    all_movie_folders,
                    movie_affected_targets,
                    movie_incremental_mode,
                ) = self._resolve_reconcile_scope(
                    affected_paths,
                    known_folders=self._known_movie_folders,
                    discover=discover_movie_folders,
                )
                self._known_movie_folders = dict(all_movie_folders)

            series_folders: dict[Path, Path] = {}
            all_series_folders: dict[Path, Path] = {}
            series_affected_targets: set[Path] = set()
            series_incremental_mode = False
            if self.sonarr_enabled:
                (
                    series_folders,
                    all_series_folders,
                    series_affected_targets,
                    series_incremental_mode,
                ) = self._resolve_reconcile_scope(
                    affected_paths,
                    known_folders=self._known_series_folders,
                    discover=discover_series_folders,
                )
                self._known_series_folders = dict(all_series_folders)

            target_to_links = collect_current_links(self.shadow_roots)
            movies_by_ref = self._build_movie_index() if self.sync_enabled else {}
            movies_by_path = (
                self._build_movie_path_index(movies_by_ref) if self.sync_enabled else {}
            )
            movies_by_external_id = (
                self._build_movie_external_id_index(movies_by_ref) if self.sync_enabled else {}
            )
            series_by_ref = self._build_series_index() if self.sonarr_sync_enabled else {}
            series_by_path = (
                self._build_series_path_index(series_by_ref) if self.sonarr_sync_enabled else {}
            )
            series_by_external_id = (
                self._build_series_external_id_index(series_by_ref)
                if self.sonarr_sync_enabled
                else {}
            )
            expected_links: set[Path] = set()
            movie_created_links = 0
            matched_movies = 0
            unmatched_movies = 0
            matched_movie_ids: set[int] = set()
            if self.radarr_enabled:
                (
                    movie_created_links,
                    matched_movies,
                    unmatched_movies,
                    matched_movie_ids,
                ) = self._reconcile_movie_links(
                    movie_folders=movie_folders,
                    target_to_links=target_to_links,
                    expected_links=expected_links,
                    movies_by_ref=movies_by_ref,
                    movies_by_path=movies_by_path,
                    movies_by_external_id=movies_by_external_id,
                )
            (
                series_created_links,
                matched_series,
                unmatched_series,
                matched_series_ids,
            ) = self._reconcile_series_links(
                series_folders=series_folders,
                target_to_links=target_to_links,
                expected_links=expected_links,
                series_by_ref=series_by_ref,
                series_by_path=series_by_path,
                series_by_external_id=series_by_external_id,
            )
            created_links = movie_created_links + series_created_links

            orphaned_links_removed = self._cleanup_orphans(
                all_movie_folders=all_movie_folders,
                all_series_folders=all_series_folders,
                expected_links=expected_links,
                movies_by_ref=movies_by_ref,
                series_by_ref=series_by_ref,
                movie_incremental_mode=movie_incremental_mode,
                series_incremental_mode=series_incremental_mode,
                movie_affected_targets=movie_affected_targets,
                series_affected_targets=series_affected_targets,
                matched_movie_ids=matched_movie_ids,
                matched_series_ids=matched_series_ids,
            )

            duration_seconds = round(time.time() - started, 2)
            LOG.info(
                "Reconcile complete: movie_folders=%s existing_links=%s "
                "created_links=%s matched_movies=%s unmatched_movies=%s "
                "series_folders=%s matched_series=%s unmatched_series=%s "
                "removed_orphans=%s ingested_dirs=%s ingest_pending=%s "
                "sync_enabled=%s sonarr_sync_enabled=%s duration_seconds=%s",
                len(movie_folders),
                sum(len(links) for links in target_to_links.values()),
                created_links,
                matched_movies,
                unmatched_movies,
                len(series_folders),
                matched_series,
                unmatched_series,
                orphaned_links_removed,
                ingested_count,
                ingest_pending,
                self.sync_enabled,
                self.sonarr_sync_enabled,
                duration_seconds,
            )
            return ingest_pending

    def _resolve_reconcile_scope(
        self,
        affected_paths: set[Path] | None,
        known_folders: dict[Path, Path] | None,
        discover: Callable[[Path, set[str]], set[Path]],
    ) -> tuple[dict[Path, Path], dict[Path, Path], set[Path], bool]:
        if (
            affected_paths is None
            or not affected_paths
            or self.config.ingest.enabled
            or known_folders is None
        ):
            found_folders = self._all_folders(discover)
            return found_folders, found_folders, set(found_folders.keys()), False

        scan_scopes = self._collect_incremental_scan_scopes(affected_paths)
        if not scan_scopes:
            found_folders = self._all_folders(discover)
            return found_folders, found_folders, set(found_folders.keys()), False

        known_discovered_folders = dict(known_folders)
        affected_targets: set[Path] = set()

        for scan_root, shadow_root in scan_scopes:
            removed_in_scope = [
                folder
                for folder in known_discovered_folders
                if self._path_is_equal_or_child(folder, scan_root)
            ]
            for folder in removed_in_scope:
                known_discovered_folders.pop(folder, None)
                affected_targets.add(folder)

            for folder in discover(scan_root, self.video_exts):
                known_discovered_folders[folder] = shadow_root
                affected_targets.add(folder)

        scoped_folders = {
            folder: known_discovered_folders[folder]
            for folder in affected_targets
            if folder in known_discovered_folders
        }
        return scoped_folders, known_discovered_folders, affected_targets, True

    def _collect_incremental_scan_scopes(
        self,
        affected_paths: set[Path],
    ) -> list[tuple[Path, Path]]:
        scopes: list[tuple[Path, Path]] = []
        seen: set[tuple[Path, Path]] = set()

        for changed_path in affected_paths:
            mapping = self._mapping_for_nested_path(changed_path)
            if mapping is None:
                return []

            nested_root, shadow_root = mapping
            scan_root = self._resolve_incremental_scan_root(changed_path, nested_root)
            if scan_root is None:
                return []

            scope = (scan_root, shadow_root)
            if scope in seen:
                continue
            seen.add(scope)
            scopes.append(scope)

        return scopes

    def _mapping_for_nested_path(self, path: Path) -> tuple[Path, Path] | None:
        for nested_root, shadow_root in sorted(
            self.root_mappings,
            key=lambda pair: (-len(pair[0].parts), str(pair[0])),
        ):
            if self._path_is_equal_or_child(path, nested_root):
                return nested_root, shadow_root
        return None

    def _resolve_incremental_scan_root(self, changed_path: Path, nested_root: Path) -> Path | None:
        if changed_path.exists() and changed_path.is_file():
            current = changed_path.parent
        elif changed_path.exists():
            current = changed_path
        else:
            current = changed_path.parent

        while self._path_is_equal_or_child(current, nested_root):
            if current.exists():
                return current
            if current == nested_root:
                break
            current = current.parent

        if nested_root.exists():
            return nested_root
        return None

    def _path_is_equal_or_child(self, path: Path, parent: Path) -> bool:
        if path == parent:
            return True
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False

    def _all_movie_folders(self) -> dict[Path, Path]:
        return self._all_folders(discover_movie_folders)

    def _all_series_folders(self) -> dict[Path, Path]:
        return self._all_folders(discover_series_folders)

    def _all_folders(
        self,
        discover: Callable[[Path, set[str]], set[Path]],
    ) -> dict[Path, Path]:
        all_folders: dict[Path, Path] = {}
        # Prefer more specific nested roots first if mappings overlap.
        sorted_mappings = sorted(
            self.root_mappings,
            key=lambda pair: (-len(pair[0].parts), str(pair[0])),
        )
        for nested_root, shadow_root in sorted_mappings:
            for folder in discover(nested_root, self.video_exts):
                all_folders.setdefault(folder, shadow_root)
        return all_folders

    def _reconcile_movie_links(
        self,
        movie_folders: dict[Path, Path],
        target_to_links: dict[Path, set[Path]],
        expected_links: set[Path],
        movies_by_ref: dict[MovieRef, dict],
        movies_by_path: dict[str, dict],
        movies_by_external_id: dict[str, dict],
    ) -> tuple[int, int, int, set[int]]:
        created_links = 0
        matched_movies = 0
        unmatched_movies = 0
        auto_added_movie_ids: set[int] = set()
        matched_movie_ids: set[int] = set()

        for folder, shadow_root in sorted(movie_folders.items()):
            existing_links = target_to_links.get(folder, set())
            movie = (
                self._match_movie_for_folder(
                    folder,
                    movies_by_ref,
                    movies_by_path,
                    movies_by_external_id,
                    existing_links,
                )
                if self.sync_enabled
                else None
            )
            if self.sync_enabled and movie is None and self.auto_add_unmatched:
                movie = self.radarr_sync.auto_add_movie_for_folder(folder, shadow_root)
                if movie is not None:
                    self._add_movie_id_if_present(auto_added_movie_ids, movie)
                    self._index_movie(index=movies_by_ref, movie=movie)
                    self._index_movie_path(index=movies_by_path, movie=movie)
                    self._index_movie_external_ids(index=movies_by_external_id, movie=movie)

            link_path, was_created = self.link_manager.ensure_link(
                folder,
                shadow_root,
                existing_links,
                movie,
            )
            expected_links.add(link_path)
            target_to_links.setdefault(folder, set()).add(link_path)
            if was_created:
                created_links += 1

            if not self.sync_enabled:
                continue

            if movie is not None:
                movie_id = self._add_movie_id_if_present(matched_movie_ids, movie)
                self._sync_radarr_for_folder(
                    folder,
                    link_path,
                    movie,
                    force_refresh=movie_id is not None and movie_id in auto_added_movie_ids,
                )
                matched_movies += 1
                continue

            if self.auto_add_unmatched:
                LOG.warning(
                    "No Radarr match for folder after auto-add attempt: %s",
                    folder,
                )
            else:
                LOG.warning(
                    "No Radarr match for folder: %s "
                    "(enable radarr.auto_add_unmatched=true to auto-create, "
                    "or add/import in Radarr first)",
                    folder,
                )
            unmatched_movies += 1

        return created_links, matched_movies, unmatched_movies, matched_movie_ids

    def _reconcile_series_links(
        self,
        series_folders: dict[Path, Path],
        target_to_links: dict[Path, set[Path]],
        expected_links: set[Path],
        series_by_ref: dict[MovieRef, dict],
        series_by_path: dict[str, dict],
        series_by_external_id: dict[str, dict],
    ) -> tuple[int, int, int, set[int]]:
        created_links = 0
        matched_series = 0
        unmatched_series = 0
        auto_added_series_ids: set[int] = set()
        matched_series_ids: set[int] = set()

        for folder, shadow_root in sorted(series_folders.items()):
            existing_links = target_to_links.get(folder, set())
            series = (
                self._match_series_for_folder(
                    folder,
                    series_by_ref,
                    series_by_path,
                    series_by_external_id,
                    existing_links,
                )
                if self.sonarr_sync_enabled
                else None
            )
            if self.sonarr_sync_enabled and series is None and self.sonarr_auto_add_unmatched:
                series = self.sonarr_sync.auto_add_series_for_folder(folder, shadow_root)
                if series is not None:
                    self._add_movie_id_if_present(auto_added_series_ids, series)
                    self._index_series(index=series_by_ref, series=series)
                    self._index_series_path(index=series_by_path, series=series)
                    self._index_series_external_ids(index=series_by_external_id, series=series)

            link_path, was_created = self.link_manager.ensure_link(
                folder,
                shadow_root,
                existing_links,
                series,
            )
            expected_links.add(link_path)
            target_to_links.setdefault(folder, set()).add(link_path)
            if was_created:
                created_links += 1

            if not self.sonarr_sync_enabled:
                continue

            if series is not None:
                series_id = self._add_movie_id_if_present(matched_series_ids, series)
                self._sync_sonarr_for_folder(
                    folder,
                    link_path,
                    series,
                    force_refresh=series_id is not None and series_id in auto_added_series_ids,
                )
                matched_series += 1
                continue

            if self.sonarr_auto_add_unmatched:
                LOG.warning(
                    "No Sonarr match for folder after auto-add attempt: %s",
                    folder,
                )
            else:
                LOG.warning(
                    "No Sonarr match for folder: %s "
                    "(enable sonarr.auto_add_unmatched=true to auto-create, "
                    "or add/import in Sonarr first)",
                    folder,
                )
            unmatched_series += 1

        return created_links, matched_series, unmatched_series, matched_series_ids

    def _cleanup_orphans(
        self,
        all_movie_folders: dict[Path, Path],
        all_series_folders: dict[Path, Path],
        expected_links: set[Path],
        movies_by_ref: dict[MovieRef, dict],
        series_by_ref: dict[MovieRef, dict],
        movie_incremental_mode: bool,
        series_incremental_mode: bool,
        movie_affected_targets: set[Path],
        series_affected_targets: set[Path],
        matched_movie_ids: set[int],
        matched_series_ids: set[int],
    ) -> int:
        if not self.config.cleanup.remove_orphaned_links:
            return 0

        existing_folders = set(all_movie_folders.keys()) | set(all_series_folders.keys())
        removed_orphans = 0
        if self.radarr_enabled:
            removed_orphans = self._cleanup_with_manager(
                manager=self.cleanup_manager,
                existing_folders=existing_folders,
                items_by_ref=movies_by_ref,
                expected_links=expected_links,
                incremental_mode=movie_incremental_mode,
                affected_targets=movie_affected_targets,
                matched_item_ids=matched_movie_ids,
            )

        if self.sonarr_enabled:
            removed_orphans += self._cleanup_with_manager(
                manager=self.sonarr_cleanup_manager,
                existing_folders=existing_folders,
                items_by_ref=series_by_ref,
                expected_links=expected_links,
                incremental_mode=series_incremental_mode,
                affected_targets=series_affected_targets,
                matched_item_ids=matched_series_ids,
            )

        return removed_orphans

    def _cleanup_with_manager(
        self,
        manager: ShadowCleanupManager,
        existing_folders: set[Path],
        items_by_ref: dict[MovieRef, dict],
        expected_links: set[Path],
        incremental_mode: bool,
        affected_targets: set[Path],
        matched_item_ids: set[int],
    ) -> int:
        if incremental_mode:
            return manager.cleanup_orphans_for_targets(
                existing_folders=existing_folders,
                movies_by_ref=items_by_ref,
                expected_links=expected_links,
                affected_targets=affected_targets,
                matched_movie_ids=matched_item_ids,
            )

        return manager.cleanup_orphans(
            existing_folders,
            items_by_ref,
            expected_links,
            matched_movie_ids=matched_item_ids,
        )

    def _match_movie_for_folder(
        self,
        folder: Path,
        movies_by_ref: dict[MovieRef, dict],
        movies_by_path: dict[str, dict],
        movies_by_external_id: dict[str, dict],
        existing_links: set[Path],
    ) -> dict | None:
        external_id_match = self._match_movie_for_external_ids(folder, movies_by_external_id)
        if external_id_match is not None:
            return external_id_match

        ref = parse_movie_ref(folder.name)
        exact_match = movies_by_ref.get(ref) or movies_by_ref.get(
            MovieRef(title=ref.title, year=None)
        )
        if exact_match is not None:
            return exact_match

        link_match = self._match_movie_for_existing_links(
            existing_links,
            movies_by_ref,
            movies_by_path,
        )
        if link_match is not None:
            return link_match

        # Safe fallback: same-year fuzzy title matching for folder aliases/suffixes
        # like "Fixture Title - Variant (2017)" vs Radarr title "Fixture Title (2017)".
        return self._fuzzy_match_movie_for_folder(ref, movies_by_ref)

    def _normalize_fs_path(self, value: str) -> str:
        return value.rstrip("/")

    def _match_movie_for_existing_links(
        self,
        existing_links: set[Path],
        movies_by_ref: dict[MovieRef, dict],
        movies_by_path: dict[str, dict],
    ) -> dict | None:
        for link in sorted(existing_links):
            linked_movie = movies_by_path.get(self._normalize_fs_path(str(link)))
            if linked_movie is not None:
                return linked_movie

            ref = parse_movie_ref(link.name.split("--", 1)[0])
            named_movie = movies_by_ref.get(ref) or movies_by_ref.get(
                MovieRef(title=ref.title, year=None)
            )
            if named_movie is not None:
                return named_movie

        return None

    def _normalize_title_token(self, title: str) -> str:
        return TITLE_TOKEN_RE.sub("", title.strip().lower())

    def _fuzzy_match_movie_for_folder(
        self,
        ref: MovieRef,
        movies_by_ref: dict[MovieRef, dict],
    ) -> dict | None:
        if ref.year is None:
            return None

        ref_norm = self._normalize_title_token(ref.title)
        if not ref_norm:
            return None

        best_score = -1
        best: dict | None = None
        seen_ids: set[int] = set()

        for movie in movies_by_ref.values():
            movie_id = movie.get("id")
            if not isinstance(movie_id, int) or movie_id in seen_ids:
                continue
            seen_ids.add(movie_id)

            year = movie.get("year")
            if not isinstance(year, int) or year != ref.year:
                continue

            movie_title = str(movie.get("title") or "").strip()
            movie_norm = self._normalize_title_token(movie_title)
            if not movie_norm:
                continue

            score = 0
            if movie_norm == ref_norm:
                score += 100
            elif movie_norm in ref_norm or ref_norm in movie_norm:
                score += 50

            if score > best_score:
                best_score = score
                best = movie

        return best if best_score > 0 else None

    def _build_movie_index(self) -> dict[MovieRef, dict]:
        index: dict[MovieRef, dict] = {}
        for movie in self.radarr.get_movies():
            self._index_movie(index=index, movie=movie)
        return index

    def _build_movie_path_index(self, movies_by_ref: dict[MovieRef, dict]) -> dict[str, dict]:
        index: dict[str, dict] = {}
        seen_ids: set[int] = set()
        for movie in movies_by_ref.values():
            movie_id = movie.get("id")
            if not isinstance(movie_id, int) or movie_id in seen_ids:
                continue
            seen_ids.add(movie_id)
            self._index_movie_path(index=index, movie=movie)
        return index

    def _build_movie_external_id_index(
        self,
        movies_by_ref: dict[MovieRef, dict],
    ) -> dict[str, dict]:
        index: dict[str, dict] = {}
        seen_ids: set[int] = set()
        for movie in movies_by_ref.values():
            movie_id = movie.get("id")
            if not isinstance(movie_id, int) or movie_id in seen_ids:
                continue
            seen_ids.add(movie_id)
            self._index_movie_external_ids(index=index, movie=movie)
        return index

    def _index_movie(self, index: dict[MovieRef, dict], movie: dict) -> None:
        title = (movie.get("title") or "").strip().lower()
        if not title:
            return
        year = movie.get("year")
        ref = MovieRef(title=title, year=year if isinstance(year, int) else None)
        index[ref] = movie
        # Fallback key: title only
        if MovieRef(title=title, year=None) not in index:
            index[MovieRef(title=title, year=None)] = movie

    def _index_movie_path(self, index: dict[str, dict], movie: dict) -> None:
        path_raw = movie.get("path")
        path = str(path_raw).strip() if path_raw is not None else ""
        if not path:
            return
        index[self._normalize_fs_path(path)] = movie

    def _add_movie_id_if_present(self, target: set[int], movie: dict) -> int | None:
        movie_id = movie.get("id")
        if isinstance(movie_id, int):
            target.add(movie_id)
            return movie_id
        return None

    def _index_movie_external_ids(self, index: dict[str, dict], movie: dict) -> None:
        tmdb_id = movie.get("tmdbId")
        if isinstance(tmdb_id, int):
            index.setdefault(f"tmdb:{tmdb_id}", movie)

        imdb_raw = movie.get("imdbId")
        imdb_id = str(imdb_raw).strip().lower() if imdb_raw is not None else ""
        if imdb_id.startswith("tt"):
            index.setdefault(f"imdb:{imdb_id}", movie)

    def _collect_folder_identity_text(self, folder: Path) -> str:
        parts = [folder.name]
        try:
            for child in sorted(folder.iterdir()):
                if not child.is_file():
                    continue

                parts.append(child.name)
                if child.suffix.lower() != ".nfo":
                    continue

                try:
                    parts.append(child.read_text(encoding="utf-8", errors="ignore"))
                except OSError:
                    continue
        except OSError:
            return " ".join(parts).lower()

        return " ".join(parts).lower()

    def _extract_external_ids_from_text(self, text: str) -> tuple[int | None, str | None]:
        tmdb_id: int | None = None
        imdb_id: str | None = None

        tmdb_match = TMDB_UNIQUE_ID_RE.search(text) or TMDB_ID_RE.search(text)
        if tmdb_match is not None:
            try:
                tmdb_id = int(tmdb_match.group(1))
            except (TypeError, ValueError):
                tmdb_id = None

        imdb_match = (
            IMDB_UNIQUE_ID_RE.search(text)
            or IMDB_NEAR_TOKEN_RE.search(text)
            or IMDB_ID_RE.search(text)
        )
        if imdb_match is not None:
            imdb_id = (
                imdb_match.group(1).lower() if imdb_match.lastindex else imdb_match.group(0).lower()
            )

        return tmdb_id, imdb_id

    def _match_movie_for_external_ids(
        self,
        folder: Path,
        movies_by_external_id: dict[str, dict],
    ) -> dict | None:
        if not movies_by_external_id:
            return None

        identity_text = self._collect_folder_identity_text(folder)
        tmdb_id, imdb_id = self._extract_external_ids_from_text(identity_text)

        if tmdb_id is not None:
            tmdb_match = movies_by_external_id.get(f"tmdb:{tmdb_id}")
            if tmdb_match is not None:
                return tmdb_match

        if imdb_id is not None:
            return movies_by_external_id.get(f"imdb:{imdb_id}")

        return None

    def _sync_radarr_for_folder(
        self,
        folder: Path,
        link: Path,
        movie: dict,
        force_refresh: bool = False,
    ) -> None:
        path_updated = self.radarr.update_movie_path(movie, str(link))
        quality_updated = False
        if self.config.quality_map:
            quality_id = map_quality_id(
                folder,
                self.config.quality_map,
                use_nfo=self.config.analysis.use_nfo,
                use_media_probe=self.config.analysis.use_media_probe,
                media_probe_bin=self.config.analysis.media_probe_bin,
            )
            quality_updated = self.radarr.try_update_moviefile_quality(movie, quality_id)

        if force_refresh or path_updated or quality_updated:
            self.radarr.refresh_movie(int(movie["id"]), force=force_refresh)

    def _resolve_movie_for_link_name(
        self,
        link_name: str,
        movies_by_ref: dict[MovieRef, dict],
    ) -> dict | None:
        ref = parse_movie_ref(link_name.split("--", 1)[0])
        return movies_by_ref.get(ref) or movies_by_ref.get(MovieRef(title=ref.title, year=None))

    def _extract_tvdb_id_from_text(self, text: str) -> int | None:
        tvdb_match = TVDB_UNIQUE_ID_RE.search(text) or TVDB_ID_RE.search(text)
        if tvdb_match is None:
            return None
        try:
            return int(tvdb_match.group(1))
        except (TypeError, ValueError):
            return None

    def _build_series_index(self) -> dict[MovieRef, dict]:
        index: dict[MovieRef, dict] = {}
        for series in self.sonarr.get_series():
            self._index_series(index=index, series=series)
        return index

    def _build_series_path_index(self, series_by_ref: dict[MovieRef, dict]) -> dict[str, dict]:
        index: dict[str, dict] = {}
        seen_ids: set[int] = set()
        for series in series_by_ref.values():
            series_id = series.get("id")
            if not isinstance(series_id, int) or series_id in seen_ids:
                continue
            seen_ids.add(series_id)
            self._index_series_path(index=index, series=series)
        return index

    def _build_series_external_id_index(
        self,
        series_by_ref: dict[MovieRef, dict],
    ) -> dict[str, dict]:
        index: dict[str, dict] = {}
        seen_ids: set[int] = set()
        for series in series_by_ref.values():
            series_id = series.get("id")
            if not isinstance(series_id, int) or series_id in seen_ids:
                continue
            seen_ids.add(series_id)
            self._index_series_external_ids(index=index, series=series)
        return index

    def _index_series(self, index: dict[MovieRef, dict], series: dict) -> None:
        title = (series.get("title") or "").strip().lower()
        if not title:
            return
        year = series.get("year")
        ref = MovieRef(title=title, year=year if isinstance(year, int) else None)
        index[ref] = series
        if MovieRef(title=title, year=None) not in index:
            index[MovieRef(title=title, year=None)] = series

    def _index_series_path(self, index: dict[str, dict], series: dict) -> None:
        path_raw = series.get("path")
        path = str(path_raw).strip() if path_raw is not None else ""
        if not path:
            return
        index[self._normalize_fs_path(path)] = series

    def _index_series_external_ids(self, index: dict[str, dict], series: dict) -> None:
        tvdb_id = series.get("tvdbId")
        if isinstance(tvdb_id, int):
            index.setdefault(f"tvdb:{tvdb_id}", series)

        tmdb_id = series.get("tmdbId")
        if isinstance(tmdb_id, int):
            index.setdefault(f"tmdb:{tmdb_id}", series)

        imdb_raw = series.get("imdbId")
        imdb_id = str(imdb_raw).strip().lower() if imdb_raw is not None else ""
        if imdb_id.startswith("tt"):
            index.setdefault(f"imdb:{imdb_id}", series)

    def _match_series_for_external_ids(
        self,
        folder: Path,
        series_by_external_id: dict[str, dict],
    ) -> dict | None:
        if not series_by_external_id:
            return None

        identity_text = self._collect_folder_identity_text(folder)
        tvdb_id = self._extract_tvdb_id_from_text(identity_text)
        tmdb_id, imdb_id = self._extract_external_ids_from_text(identity_text)

        if tvdb_id is not None:
            tvdb_match = series_by_external_id.get(f"tvdb:{tvdb_id}")
            if tvdb_match is not None:
                return tvdb_match

        if tmdb_id is not None:
            tmdb_match = series_by_external_id.get(f"tmdb:{tmdb_id}")
            if tmdb_match is not None:
                return tmdb_match

        if imdb_id is not None:
            return series_by_external_id.get(f"imdb:{imdb_id}")

        return None

    def _match_series_for_existing_links(
        self,
        existing_links: set[Path],
        series_by_ref: dict[MovieRef, dict],
        series_by_path: dict[str, dict],
    ) -> dict | None:
        for link in sorted(existing_links):
            linked_series = series_by_path.get(self._normalize_fs_path(str(link)))
            if linked_series is not None:
                return linked_series

            ref = parse_movie_ref(link.name.split("--", 1)[0])
            named_series = series_by_ref.get(ref) or series_by_ref.get(
                MovieRef(title=ref.title, year=None)
            )
            if named_series is not None:
                return named_series

        return None

    def _match_series_for_folder(
        self,
        folder: Path,
        series_by_ref: dict[MovieRef, dict],
        series_by_path: dict[str, dict],
        series_by_external_id: dict[str, dict],
        existing_links: set[Path],
    ) -> dict | None:
        external_id_match = self._match_series_for_external_ids(folder, series_by_external_id)
        if external_id_match is not None:
            return external_id_match

        ref = parse_movie_ref(folder.name)
        exact_match = series_by_ref.get(ref) or series_by_ref.get(
            MovieRef(title=ref.title, year=None)
        )
        if exact_match is not None:
            return exact_match

        link_match = self._match_series_for_existing_links(
            existing_links,
            series_by_ref,
            series_by_path,
        )
        if link_match is not None:
            return link_match

        return self._fuzzy_match_movie_for_folder(ref, series_by_ref)

    def _sync_sonarr_for_folder(
        self,
        _folder: Path,
        link: Path,
        series: dict,
        force_refresh: bool = False,
    ) -> None:
        path_updated = self.sonarr.update_series_path(series, str(link))
        if force_refresh or path_updated:
            self.sonarr.refresh_series(int(series["id"]), force=force_refresh)

    def _resolve_series_for_link_name(
        self,
        link_name: str,
        series_by_ref: dict[MovieRef, dict],
    ) -> dict | None:
        ref = parse_movie_ref(link_name.split("--", 1)[0])
        return series_by_ref.get(ref) or series_by_ref.get(MovieRef(title=ref.title, year=None))
