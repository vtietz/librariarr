from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import requests

from ..clients.radarr import RadarrClient
from ..config import AppConfig
from ..service.external_id_parsing import extract_external_ids_from_nfo
from .naming import canonical_name_from_folder, parse_movie_ref, safe_path_component
from .radarr_autoadd_profile import AutoAddProfileResolver
from .radarr_diagnostics import log_quality_mapping_diagnostics
from .radarr_mapping import (
    pick_lookup_candidate,
)


def _managed_equivalent(library_path: str, mappings: list[tuple[Path, Path]]) -> Path | None:
    """Resolve a library path back to its managed-root equivalent."""
    path = Path(library_path)
    for managed_root, library_root in mappings:
        try:
            relative = path.relative_to(library_root)
        except ValueError:
            continue
        return managed_root / relative
    return None


class RadarrSyncHelper:
    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger,
        get_radarr_client: Callable[[], RadarrClient],
    ) -> None:
        self.config = config
        self.log = logger
        self._get_radarr_client = get_radarr_client
        self._profile_resolver = AutoAddProfileResolver(config, logger, get_radarr_client)
        self._auto_add_no_safe_lookup_signature_cache: dict[str, int | None] = {}
        self._cached_radarr_client_id: int | None = None

    def _radarr(self) -> RadarrClient:
        client = self._get_radarr_client()
        client_id = id(client)
        if self._cached_radarr_client_id != client_id:
            self._cached_radarr_client_id = client_id
            self._profile_resolver.reset_caches()
            self._auto_add_no_safe_lookup_signature_cache = {}
        return client

    def _auto_add_cache_key_for_folder(self, folder: Path) -> str:
        return str(folder.resolve(strict=False))

    def _auto_add_signature_for_folder(self, folder: Path) -> int | None:
        try:
            return folder.stat().st_mtime_ns
        except OSError:
            return None

    def _should_skip_no_safe_lookup_retry(self, folder: Path) -> bool:
        cache_key = self._auto_add_cache_key_for_folder(folder)
        cached_signature = self._auto_add_no_safe_lookup_signature_cache.get(cache_key)
        if (
            cached_signature is None
            and cache_key not in self._auto_add_no_safe_lookup_signature_cache
        ):
            return False
        current_signature = self._auto_add_signature_for_folder(folder)
        return cached_signature == current_signature

    def _remember_no_safe_lookup_for_folder(self, folder: Path) -> None:
        cache_key = self._auto_add_cache_key_for_folder(folder)
        folder_signature = self._auto_add_signature_for_folder(folder)
        self._auto_add_no_safe_lookup_signature_cache[cache_key] = folder_signature

    def _clear_no_safe_lookup_for_folder(self, folder: Path) -> None:
        cache_key = self._auto_add_cache_key_for_folder(folder)
        self._auto_add_no_safe_lookup_signature_cache.pop(cache_key, None)

    def log_quality_mapping_diagnostics(self, auto_add_unmatched: bool) -> None:
        log_quality_mapping_diagnostics(
            config=self.config,
            log=self.log,
            radarr=self._radarr(),
            auto_add_unmatched=auto_add_unmatched,
        )

    def _canonical_name_from_movie(self, movie: dict, fallback_folder: Path) -> str:
        title = str(movie.get("title") or "").strip()
        year = movie.get("year")
        if title and isinstance(year, int):
            return f"{title} ({year})"
        if title:
            return title
        return canonical_name_from_folder(safe_path_component(fallback_folder.name))

    def _managed_root_priority(self, folder: Path) -> int | None:
        """Return the config-order index of the mapping containing *folder*.

        Lower index means higher priority.  Returns ``None`` when the folder
        does not fall under any configured movie managed/library root.
        """
        for index, mapping in enumerate(self.config.paths.movie_root_mappings):
            managed_root = Path(mapping.managed_root)
            try:
                folder.relative_to(managed_root)
                return index
            except ValueError:
                pass
            library_root = Path(mapping.library_root)
            try:
                folder.relative_to(library_root)
                return index
            except ValueError:
                continue
        return None

    def _library_root_for_managed_root(
        self,
        folder: Path,
        managed_root: Path,
    ) -> Path | None:
        """Resolve the library root corresponding to a managed folder.

        Returns the ``library_root`` from the first mapping whose
        ``managed_root`` matches, or ``None`` when no mapping applies.
        """
        for mapping in self.config.paths.movie_root_mappings:
            configured_managed_root = Path(mapping.managed_root)
            if configured_managed_root != managed_root:
                continue
            try:
                folder.relative_to(configured_managed_root)
            except ValueError:
                break
            return Path(mapping.library_root)
        return None

    def _find_existing_movie(
        self,
        candidate: dict,
        target_path: Path,
        movies_cache: list[dict] | None = None,
    ) -> dict | None:
        if movies_cache is not None:
            existing_movies = movies_cache
        else:
            try:
                existing_movies = self._radarr().get_movies()
            except requests.RequestException:
                return None

        candidate_tmdb_id = candidate.get("tmdbId")
        if isinstance(candidate_tmdb_id, int):
            for movie in existing_movies:
                if int(movie.get("tmdbId") or 0) == candidate_tmdb_id:
                    return movie

        target_path_text = str(target_path)
        for movie in existing_movies:
            movie_path = str(movie.get("path") or "").strip()
            if movie_path == target_path_text:
                return movie

        return None

    def _reconcile_existing_movie(
        self,
        *,
        existing_movie: dict,
        target_folder: Path,
        canonical_name: str,
        folder: Path,
    ) -> dict | None:
        """Handle auto-add when the movie already exists in Radarr."""
        existing_path = str(existing_movie.get("path") or "").strip()
        target_path = str(target_folder)
        path_updated = False

        if existing_path != target_path:
            result = self._try_update_existing_path(
                existing_movie, existing_path, target_folder, canonical_name
            )
            if result == "skipped_lower_priority":
                return existing_movie
            if result == "failed":
                return None
            path_updated = result == "updated"

        self._log_duplicate_or_skip(
            existing_movie, existing_path, target_path, path_updated, canonical_name, folder
        )
        return existing_movie

    def _try_update_existing_path(
        self,
        existing_movie: dict,
        existing_path: str,
        target_folder: Path,
        canonical_name: str,
    ) -> str:
        """Attempt to update an existing movie's path.

        Returns ``"updated"``, ``"skipped_lower_priority"``, or ``"failed"``.
        """
        existing_priority = self._managed_root_priority(Path(existing_path))
        new_priority = self._managed_root_priority(target_folder)
        if (
            existing_priority is not None
            and new_priority is not None
            and new_priority > existing_priority
        ):
            self.log.warning(
                "Duplicate folder ignored: movie_id=%s already tracked at "
                "higher-priority path. existing=%s duplicate=%s "
                "(existing_idx=%s new_idx=%s)",
                existing_movie.get("id"),
                existing_path,
                target_folder,
                existing_priority,
                new_priority,
            )
            return "skipped_lower_priority"

        try:
            self._radarr().update_movie_path(existing_movie, str(target_folder))
            existing_movie["path"] = str(target_folder)
            self.log.info(
                "Radarr path reconciliation updated movie_id=%s canonical=%s from=%s to=%s",
                existing_movie.get("id"),
                canonical_name,
                existing_path,
                target_folder,
            )
            return "updated"
        except requests.RequestException as exc:
            self.log.warning(
                "Radarr path reconciliation failed for movie_id=%s canonical=%s from=%s to=%s: %s",
                existing_movie.get("id"),
                canonical_name,
                existing_path,
                target_folder,
                exc,
            )
            return "failed"

    def _log_duplicate_or_skip(
        self,
        existing_movie: dict,
        existing_path: str,
        target_path: str,
        path_updated: bool,
        canonical_name: str,
        folder: Path,
    ) -> None:
        """Log appropriate message for an existing movie encounter."""
        if not path_updated and existing_path != target_path:
            self.log.warning(
                "Duplicate folder ignored: movie_id=%s canonical=%s already tracked "
                "at %s; folder %s will not be projected",
                existing_movie.get("id"),
                canonical_name,
                existing_path,
                folder,
            )
            return

        if not path_updated:
            managed_mappings = [
                (Path(m.managed_root), Path(m.library_root))
                for m in self.config.paths.movie_root_mappings
            ]
            existing_managed = _managed_equivalent(existing_path, managed_mappings)
            if existing_managed is not None and existing_managed.resolve() != folder.resolve():
                self.log.debug(
                    "Radarr movie already tracked at canonical shadow path; "
                    "movie_id=%s canonical=%s managed_equivalent=%s folder=%s",
                    existing_movie.get("id"),
                    canonical_name,
                    existing_managed,
                    folder,
                )
                return

        self.log.debug(
            "Radarr movie already exists; auto-add skipped movie_id=%s "
            "canonical=%s path_reconciled=%s effective_path=%s",
            existing_movie.get("id"),
            canonical_name,
            path_updated,
            existing_movie.get("path"),
        )

    def _lookup_candidate_for_folder(self, folder: Path, name_term: str) -> dict | None:
        """Try NFO-based ID lookup first, then fall back to name-based search."""
        nfo_candidate = self._try_nfo_lookup(folder)
        if nfo_candidate is not None:
            return nfo_candidate

        try:
            candidates = self._radarr().lookup_movies(name_term)
        except requests.RequestException as exc:
            self.log.warning(
                "Radarr lookup failed for folder=%s term=%s: %s", folder, name_term, exc
            )
            return None

        return pick_lookup_candidate(folder, candidates)

    def _try_nfo_lookup(self, folder: Path) -> dict | None:
        """Extract TMDb/IMDb ID from NFO files and use Radarr's ID-based lookup."""
        try:
            nfo_files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() == ".nfo"]
        except OSError:
            return None

        if not nfo_files:
            return None

        for nfo_file in sorted(nfo_files):
            tmdb_id, imdb_id, _tvdb_id = extract_external_ids_from_nfo(nfo_file)

            if tmdb_id is not None:
                try:
                    candidates = self._radarr().lookup_movies(f"tmdb:{tmdb_id}")
                except requests.RequestException:
                    continue
                if candidates:
                    self.log.debug("NFO lookup matched via tmdb:%s for folder=%s", tmdb_id, folder)
                    return candidates[0]

            if imdb_id is not None:
                try:
                    candidates = self._radarr().lookup_movies(f"imdb:{imdb_id}")
                except requests.RequestException:
                    continue
                if candidates:
                    self.log.debug("NFO lookup matched via imdb:%s for folder=%s", imdb_id, folder)
                    return candidates[0]

        return None

    def auto_add_movie_for_folder(
        self,
        folder: Path,
        managed_root: Path,
        movies_cache: list[dict] | None = None,
    ) -> dict | None:
        ref = parse_movie_ref(folder.name)
        term = f"{ref.title} {ref.year}" if ref.year is not None else ref.title

        library_root = self._library_root_for_managed_root(folder, managed_root)
        if library_root is None:
            self.log.warning(
                "Skipping auto-add for folder=%s because no movie_root_mapping matched "
                "managed_root=%s",
                folder,
                managed_root,
            )
            return None

        if self._should_skip_no_safe_lookup_retry(folder):
            return None

        candidate = self._lookup_candidate_for_folder(folder, term)
        if candidate is None:
            self._remember_no_safe_lookup_for_folder(folder)
            self.log.warning(
                "No safe Radarr lookup match for folder: %s (lookup_term=%s)",
                folder,
                term,
            )
            return None

        self._clear_no_safe_lookup_for_folder(folder)

        quality_profile_id = self._profile_resolver.resolve(folder)
        if quality_profile_id is None:
            self.log.warning(
                "Skipping auto-add for folder=%s because no quality profile id is available.",
                folder,
            )
            return None

        canonical_name = self._canonical_name_from_movie(candidate, folder)
        target_folder = library_root / safe_path_component(canonical_name)

        existing_movie = self._find_existing_movie(candidate, target_folder, movies_cache)
        if existing_movie is not None:
            return self._reconcile_existing_movie(
                existing_movie=existing_movie,
                target_folder=target_folder,
                canonical_name=canonical_name,
                folder=folder,
            )

        try:
            added_movie = self._radarr().add_movie_from_lookup(
                candidate,
                path=str(target_folder),
                root_folder_path=str(library_root),
                quality_profile_id=quality_profile_id,
                monitored=self.config.radarr.auto_add_monitored,
                search_for_movie=self.config.radarr.auto_add_search_on_add,
            )
        except requests.HTTPError as exc:
            self.log.warning(
                "Radarr auto-add failed for folder=%s canonical=%s profile_id=%s: %s",
                folder,
                canonical_name,
                quality_profile_id,
                exc,
            )
            return None

        self.log.info(
            "Auto-added movie in Radarr: folder=%s canonical=%s movie_id=%s",
            folder,
            canonical_name,
            added_movie.get("id"),
        )
        return added_movie
