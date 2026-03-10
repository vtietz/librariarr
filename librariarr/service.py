from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from .config import AppConfig
from .quality import VIDEO_EXTENSIONS, map_quality_id
from .radarr import RadarrClient
from .runtime import ReconcileSchedule, RuntimeSyncLoop
from .sync import (
    MovieRef,
    RadarrSyncHelper,
    ShadowCleanupManager,
    ShadowIngestor,
    ShadowLinkManager,
    collect_current_links,
    discover_movie_folders,
    parse_movie_ref,
)

LOG = logging.getLogger(__name__)
TITLE_TOKEN_RE = re.compile(r"[^a-z0-9]+")


class LibrariArrService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.sync_enabled = config.radarr.sync_enabled
        self.auto_add_unmatched = config.radarr.auto_add_unmatched
        self.radarr = RadarrClient(config.radarr.url, config.radarr.api_key)
        self.radarr_sync = RadarrSyncHelper(
            config=config,
            logger=LOG,
            get_radarr_client=lambda: self.radarr,
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
            get_radarr_client=lambda: self.radarr,
            resolve_movie_for_link_name=self._resolve_movie_for_link_name,
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
            "sync_enabled=%s auto_add_unmatched=%s debounce_seconds=%s "
            "maintenance_interval_seconds=%s",
            ",".join(str(root) for root in self.shadow_roots),
            ",".join(str(root) for root in self.nested_roots),
            self.sync_enabled,
            self.auto_add_unmatched,
            self._debounce_seconds,
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
            on_reconcile_error=self._log_sync_config_hint,
            logger=LOG,
        )
        runtime_loop.run()

    def _run_sync_preflight_checks(self) -> None:
        if not self.sync_enabled:
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

    def reconcile(self) -> None:
        with self._lock:
            started = time.time()
            LOG.info("Reconciling shadow links and Radarr state...")
            for shadow_root in self.shadow_roots:
                shadow_root.mkdir(parents=True, exist_ok=True)

            ingested_count = self.ingestor.run() if self.config.ingest.enabled else 0

            movie_folders = self._all_movie_folders()
            target_to_links = collect_current_links(self.shadow_roots)
            movies_by_ref = self._build_movie_index() if self.sync_enabled else {}
            movies_by_path = (
                self._build_movie_path_index(movies_by_ref) if self.sync_enabled else {}
            )
            expected_links: set[Path] = set()
            created_links = 0
            matched_movies = 0
            unmatched_movies = 0

            for folder, shadow_root in sorted(movie_folders.items()):
                existing_links = target_to_links.get(folder, set())
                movie = (
                    self._match_movie_for_folder(
                        folder,
                        movies_by_ref,
                        movies_by_path,
                        existing_links,
                    )
                    if self.sync_enabled
                    else None
                )
                if self.sync_enabled and movie is None and self.auto_add_unmatched:
                    movie = self.radarr_sync.auto_add_movie_for_folder(folder, shadow_root)
                    if movie is not None:
                        self._index_movie(index=movies_by_ref, movie=movie)
                        self._index_movie_path(index=movies_by_path, movie=movie)

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

                if self.sync_enabled:
                    if movie is not None:
                        self._sync_radarr_for_folder(folder, link_path, movie)
                        matched_movies += 1
                    else:
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

            orphaned_links_removed = 0
            if self.config.cleanup.remove_orphaned_links:
                orphaned_links_removed = self.cleanup_manager.cleanup_orphans(
                    set(movie_folders.keys()),
                    movies_by_ref,
                    expected_links,
                )

            duration_seconds = round(time.time() - started, 2)
            LOG.info(
                "Reconcile complete: movie_folders=%s existing_links=%s "
                "created_links=%s matched_movies=%s unmatched_movies=%s "
                "removed_orphans=%s ingested_dirs=%s sync_enabled=%s duration_seconds=%s",
                len(movie_folders),
                sum(len(links) for links in target_to_links.values()),
                created_links,
                matched_movies,
                unmatched_movies,
                orphaned_links_removed,
                ingested_count,
                self.sync_enabled,
                duration_seconds,
            )

    def _all_movie_folders(self) -> dict[Path, Path]:
        all_folders: dict[Path, Path] = {}
        # Prefer more specific nested roots first if mappings overlap.
        sorted_mappings = sorted(
            self.root_mappings,
            key=lambda pair: (-len(pair[0].parts), str(pair[0])),
        )
        for nested_root, shadow_root in sorted_mappings:
            for folder in discover_movie_folders(nested_root, self.video_exts):
                all_folders.setdefault(folder, shadow_root)
        return all_folders

    def _match_movie_for_folder(
        self,
        folder: Path,
        movies_by_ref: dict[MovieRef, dict],
        movies_by_path: dict[str, dict],
        existing_links: set[Path],
    ) -> dict | None:
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

    def _sync_radarr_for_folder(
        self,
        folder: Path,
        link: Path,
        movie: dict,
    ) -> None:
        self.radarr.update_movie_path(movie, str(link))
        if self.config.quality_map:
            quality_id = map_quality_id(
                folder,
                self.config.quality_map,
                use_nfo=self.config.analysis.use_nfo,
                use_media_probe=self.config.analysis.use_media_probe,
                media_probe_bin=self.config.analysis.media_probe_bin,
            )
            self.radarr.try_update_moviefile_quality(movie, quality_id)
        self.radarr.refresh_movie(int(movie["id"]))

    def _resolve_movie_for_link_name(
        self,
        link_name: str,
        movies_by_ref: dict[MovieRef, dict],
    ) -> dict | None:
        ref = parse_movie_ref(link_name.split("--", 1)[0])
        return movies_by_ref.get(ref) or movies_by_ref.get(MovieRef(title=ref.title, year=None))
