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
    ShadowCleanupManager,
    ShadowIngestor,
    ShadowLinkManager,
    collect_current_links,
    discover_movie_folders,
    parse_movie_ref,
)

LOG = logging.getLogger(__name__)


class LibrariArrService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.sync_enabled = config.radarr.sync_enabled
        self.auto_add_unmatched = config.radarr.auto_add_unmatched
        self.radarr = RadarrClient(config.radarr.url, config.radarr.api_key)
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
        self._auto_add_quality_profile_id_cache: int | None = None

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
        mappings: list[tuple[Path, Path]] = []

        if config.paths.root_mappings:
            for item in config.paths.root_mappings:
                mappings.append((Path(item.nested_root), Path(item.shadow_root)))
            return mappings

        default_shadow_root = Path(config.radarr.shadow_root)
        for nested_root in config.paths.nested_roots:
            mappings.append((Path(nested_root), default_shadow_root))
        return mappings

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
            self._log_quality_mapping_diagnostics()
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

    def _format_id_name_pairs(self, items: list[dict]) -> str:
        pairs: list[str] = []
        for item in items:
            item_id, item_name = self._extract_quality_id_name(item)
            if item_id is not None:
                pairs.append(f"{item_id}:{item_name}")
        return ", ".join(pairs)

    def _extract_quality_id_name(self, item: dict) -> tuple[int | None, str]:
        quality = item.get("quality")
        if isinstance(quality, dict):
            quality_id = quality.get("id")
            quality_name = str(quality.get("name") or "").strip()
            if isinstance(quality_id, int):
                return quality_id, (quality_name or "(unnamed)")

        item_id = item.get("id")
        item_name = str(item.get("name") or "").strip() or "(unnamed)"
        if isinstance(item_id, int):
            return item_id, item_name

        return None, "(unnamed)"

    def _log_quality_mapping_diagnostics(self) -> None:
        rule_ids = sorted({rule.target_id for rule in self.config.quality_map})
        if not rule_ids:
            LOG.info("quality_map is empty; default quality id fallback applies (id=4).")
            return

        try:
            profiles = self.radarr.get_quality_profiles()
            profile_pairs = self._format_id_name_pairs(profiles)
            if profile_pairs:
                LOG.info("Radarr quality profiles (id:name): %s", profile_pairs)

            profile_ids = {
                profile_id
                for profile_id in (profile.get("id") for profile in profiles)
                if isinstance(profile_id, int)
            }
            configured_profile_id = self.config.radarr.auto_add_quality_profile_id
            if configured_profile_id is not None and configured_profile_id not in profile_ids:
                LOG.warning(
                    "radarr.auto_add_quality_profile_id is not present in Radarr profiles: "
                    "configured_profile_id=%s available_profile_ids=%s",
                    configured_profile_id,
                    sorted(profile_ids),
                )
            if self.auto_add_unmatched:
                LOG.info(
                    "Auto-add unmatched is enabled: quality_profile_id=%s monitored=%s "
                    "search_on_add=%s",
                    self.config.radarr.auto_add_quality_profile_id,
                    self.config.radarr.auto_add_monitored,
                    self.config.radarr.auto_add_search_on_add,
                )
        except Exception as exc:
            LOG.warning("Unable to fetch Radarr quality profiles: %s", exc)

        try:
            definitions = self.radarr.get_quality_definitions()
            definition_pairs = self._format_id_name_pairs(definitions)
            if definition_pairs:
                LOG.info("Radarr quality definitions (id:name): %s", definition_pairs)

            definition_ids = {
                definition_id
                for definition_id, _ in (
                    self._extract_quality_id_name(item) for item in definitions
                )
                if definition_id is not None
            }
            missing_ids = [rule_id for rule_id in rule_ids if rule_id not in definition_ids]
            if missing_ids:
                LOG.warning(
                    "quality_map target_id values not found in Radarr quality definitions: "
                    "configured_ids=%s missing_ids=%s",
                    rule_ids,
                    missing_ids,
                )
            else:
                LOG.info(
                    "quality_map target_id values validated against Radarr quality definitions: %s",
                    rule_ids,
                )
        except Exception as exc:
            LOG.warning("Unable to fetch Radarr quality definitions: %s", exc)

    def _normalize_title_token(self, title: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", title.strip().lower())

    def _pick_lookup_candidate(self, folder: Path, candidates: list[dict]) -> dict | None:
        if not candidates:
            return None

        ref = parse_movie_ref(folder.name)
        with_year = [
            item
            for item in candidates
            if ref.year is not None
            and isinstance(item.get("year"), int)
            and item.get("year") == ref.year
        ]
        if ref.year is not None:
            if not with_year:
                return None
            candidates = with_year

        ref_norm = self._normalize_title_token(ref.title)
        best_score = -1
        best: dict | None = None

        for item in candidates:
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            candidate_norm = self._normalize_title_token(title)
            score = 0
            if candidate_norm == ref_norm:
                score += 100
            elif candidate_norm and (candidate_norm in ref_norm or ref_norm in candidate_norm):
                score += 50

            if ref.year is not None and item.get("year") == ref.year:
                score += 20

            if score > best_score:
                best_score = score
                best = item

        return best if best_score > 0 else None

    def _resolve_auto_add_quality_profile_id(self) -> int | None:
        configured_profile_id = self.config.radarr.auto_add_quality_profile_id
        if configured_profile_id is not None:
            return configured_profile_id

        if self._auto_add_quality_profile_id_cache is not None:
            return self._auto_add_quality_profile_id_cache

        try:
            profiles = self.radarr.get_quality_profiles()
        except Exception as exc:
            LOG.warning("Unable to fetch Radarr quality profiles for auto-add: %s", exc)
            return None

        profile_ids = sorted(
            profile_id
            for profile_id in (profile.get("id") for profile in profiles)
            if isinstance(profile_id, int)
        )
        if not profile_ids:
            LOG.warning(
                "No Radarr quality profiles available; set radarr.auto_add_quality_profile_id "
                "or create profiles in Radarr."
            )
            return None

        self._auto_add_quality_profile_id_cache = profile_ids[0]
        LOG.info(
            "Auto-add unmatched: using default Radarr quality profile id=%s "
            "(lowest available profile id)",
            self._auto_add_quality_profile_id_cache,
        )
        return self._auto_add_quality_profile_id_cache

    def _canonical_name_from_movie(self, movie: dict, fallback_folder: Path) -> str:
        title = str(movie.get("title") or "").strip() or fallback_folder.name
        year = movie.get("year")
        if isinstance(year, int):
            return f"{title} ({year})"
        return title

    def _auto_add_movie_for_folder(self, folder: Path, shadow_root: Path) -> dict | None:
        ref = parse_movie_ref(folder.name)
        term = f"{ref.title} {ref.year}" if ref.year is not None else ref.title

        try:
            candidates = self.radarr.lookup_movies(term)
        except requests.RequestException as exc:
            LOG.warning("Radarr lookup failed for folder=%s term=%s: %s", folder, term, exc)
            return None

        candidate = self._pick_lookup_candidate(folder, candidates)
        if candidate is None:
            LOG.warning(
                "No safe Radarr lookup match for folder: %s (lookup_term=%s)",
                folder,
                term,
            )
            return None

        quality_profile_id = self._resolve_auto_add_quality_profile_id()
        if quality_profile_id is None:
            LOG.warning(
                "Skipping auto-add for folder=%s because no quality profile id is available.",
                folder,
            )
            return None

        canonical_name = self._canonical_name_from_movie(candidate, folder)
        link_path = shadow_root / canonical_name
        try:
            added_movie = self.radarr.add_movie_from_lookup(
                candidate,
                path=str(link_path),
                root_folder_path=str(shadow_root),
                quality_profile_id=quality_profile_id,
                monitored=self.config.radarr.auto_add_monitored,
                search_for_movie=self.config.radarr.auto_add_search_on_add,
            )
        except requests.HTTPError as exc:
            LOG.warning(
                "Radarr auto-add failed for folder=%s canonical=%s profile_id=%s: %s",
                folder,
                canonical_name,
                quality_profile_id,
                exc,
            )
            return None

        LOG.info(
            "Auto-added movie in Radarr: folder=%s canonical=%s movie_id=%s",
            folder,
            canonical_name,
            added_movie.get("id"),
        )
        return added_movie

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
            expected_links: set[Path] = set()
            created_links = 0
            matched_movies = 0
            unmatched_movies = 0

            for folder, shadow_root in sorted(movie_folders.items()):
                movie = (
                    self._match_movie_for_folder(folder, movies_by_ref)
                    if self.sync_enabled
                    else None
                )
                if self.sync_enabled and movie is None and self.auto_add_unmatched:
                    movie = self._auto_add_movie_for_folder(folder, shadow_root)
                    if movie is not None:
                        self._index_movie(index=movies_by_ref, movie=movie)

                existing_links = target_to_links.get(folder, set())
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
    ) -> dict | None:
        ref = parse_movie_ref(folder.name)
        return movies_by_ref.get(ref) or movies_by_ref.get(MovieRef(title=ref.title, year=None))

    def _build_movie_index(self) -> dict[MovieRef, dict]:
        index: dict[MovieRef, dict] = {}
        for movie in self.radarr.get_movies():
            self._index_movie(index=index, movie=movie)
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

    def _sync_radarr_for_folder(
        self,
        folder: Path,
        link: Path,
        movie: dict,
    ) -> None:
        self.radarr.update_movie_path(movie, str(link))
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
