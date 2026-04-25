from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import requests

from ..clients.sonarr import SonarrClient
from ..config import AppConfig
from ..quality import map_profile_id
from .naming import canonical_name_from_folder, parse_movie_ref, safe_path_component
from .radarr_mapping import pick_lookup_candidate
from .sonarr_diagnostics import log_profile_mapping_diagnostics


class SonarrSyncHelper:
    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger,
        get_sonarr_client: Callable[[], SonarrClient],
    ) -> None:
        self.config = config
        self.log = logger
        self._get_sonarr_client = get_sonarr_client
        self._auto_add_quality_profile_id_cache: int | None = None
        self._auto_add_language_profile_id_cache: int | None = None
        self._auto_add_profiles_cache: list[dict] | None = None
        self._auto_add_language_profiles_cache: list[dict] | None = None
        self._cached_sonarr_client_id: int | None = None

    def _sonarr(self) -> SonarrClient:
        client = self._get_sonarr_client()
        client_id = id(client)
        if self._cached_sonarr_client_id != client_id:
            self._cached_sonarr_client_id = client_id
            self._auto_add_quality_profile_id_cache = None
            self._auto_add_language_profile_id_cache = None
            self._auto_add_profiles_cache = None
            self._auto_add_language_profiles_cache = None
        return client

    def log_profile_mapping_diagnostics(self, auto_add_unmatched: bool) -> None:
        log_profile_mapping_diagnostics(
            config=self.config,
            log=self.log,
            sonarr=self._sonarr(),
            auto_add_unmatched=auto_add_unmatched,
        )

    def _get_auto_add_profiles(self) -> list[dict]:
        if self._auto_add_profiles_cache is not None:
            return self._auto_add_profiles_cache

        profiles = self._sonarr().get_quality_profiles()
        self._auto_add_profiles_cache = profiles
        return profiles

    def _available_quality_profile_ids(self) -> set[int]:
        return {
            profile_id
            for profile_id in (profile.get("id") for profile in self._get_auto_add_profiles())
            if isinstance(profile_id, int)
        }

    def _get_auto_add_language_profiles(self) -> list[dict]:
        if self._auto_add_language_profiles_cache is not None:
            return self._auto_add_language_profiles_cache

        try:
            profiles = self._sonarr().get_language_profiles()
        except requests.RequestException:
            profiles = []
        self._auto_add_language_profiles_cache = profiles
        return profiles

    def _available_language_profile_ids(self) -> set[int]:
        return {
            profile_id
            for profile_id in (
                profile.get("id") for profile in self._get_auto_add_language_profiles()
            )
            if isinstance(profile_id, int)
        }

    def _resolve_auto_add_quality_profile_id(self, folder: Path) -> int | None:
        available_profile_ids = self._available_quality_profile_ids()
        configured_profile_id = self.config.sonarr.auto_add_quality_profile_id
        if configured_profile_id is not None:
            if configured_profile_id in available_profile_ids:
                return configured_profile_id
            self.log.warning(
                "Configured sonarr.auto_add_quality_profile_id=%s is unavailable; "
                "falling back to available profile ids=%s",
                configured_profile_id,
                sorted(available_profile_ids),
            )

        quality_profile_map = self.config.sonarr.mapping.quality_profile_map
        if quality_profile_map:
            mapped_profile_id = map_profile_id(
                folder,
                quality_profile_map,
                default_id=None,
                use_nfo=self.config.analysis.use_nfo,
                use_media_probe=self.config.analysis.use_media_probe,
                media_probe_bin=self.config.analysis.media_probe_bin,
            )
            if mapped_profile_id is not None:
                if mapped_profile_id in available_profile_ids:
                    self.log.info(
                        "Sonarr auto-add: mapped folder=%s to quality_profile_id=%s "
                        "via sonarr.mapping.quality_profile_map",
                        folder,
                        mapped_profile_id,
                    )
                    return mapped_profile_id
                self.log.warning(
                    "Mapped Sonarr quality_profile_id=%s for folder=%s is unavailable; "
                    "falling back to available profile ids=%s",
                    mapped_profile_id,
                    folder,
                    sorted(available_profile_ids),
                )

        if self._auto_add_quality_profile_id_cache is not None:
            if self._auto_add_quality_profile_id_cache in available_profile_ids:
                return self._auto_add_quality_profile_id_cache
            self._auto_add_quality_profile_id_cache = None

        profile_ids = sorted(available_profile_ids)
        if not profile_ids:
            return None

        self._auto_add_quality_profile_id_cache = profile_ids[0]
        return self._auto_add_quality_profile_id_cache

    def _resolve_auto_add_language_profile_id(self, folder: Path) -> int | None:
        available_profile_ids = self._available_language_profile_ids()
        configured_profile_id = self.config.sonarr.auto_add_language_profile_id
        if configured_profile_id is not None:
            if configured_profile_id in available_profile_ids:
                return configured_profile_id
            self.log.warning(
                "Configured sonarr.auto_add_language_profile_id=%s is unavailable; "
                "falling back to available profile ids=%s",
                configured_profile_id,
                sorted(available_profile_ids),
            )

        language_profile_map = self.config.sonarr.mapping.language_profile_map
        if language_profile_map:
            mapped_profile_id = map_profile_id(
                folder,
                language_profile_map,
                default_id=None,
                use_nfo=self.config.analysis.use_nfo,
                use_media_probe=self.config.analysis.use_media_probe,
                media_probe_bin=self.config.analysis.media_probe_bin,
            )
            if mapped_profile_id is not None:
                if mapped_profile_id in available_profile_ids:
                    self.log.info(
                        "Sonarr auto-add: mapped folder=%s to language_profile_id=%s "
                        "via sonarr.mapping.language_profile_map",
                        folder,
                        mapped_profile_id,
                    )
                    return mapped_profile_id
                self.log.warning(
                    "Mapped Sonarr language_profile_id=%s for folder=%s is unavailable; "
                    "falling back to available profile ids=%s",
                    mapped_profile_id,
                    folder,
                    sorted(available_profile_ids),
                )

        if self._auto_add_language_profile_id_cache is not None:
            if self._auto_add_language_profile_id_cache in available_profile_ids:
                return self._auto_add_language_profile_id_cache
            self._auto_add_language_profile_id_cache = None

        profile_ids = sorted(available_profile_ids)
        if not profile_ids:
            return None

        self._auto_add_language_profile_id_cache = profile_ids[0]
        return self._auto_add_language_profile_id_cache

    def _canonical_name_from_series(self, series: dict, fallback_folder: Path) -> str:
        del series
        return canonical_name_from_folder(safe_path_component(fallback_folder.name))

    def _managed_root_priority(self, folder: Path) -> int | None:
        """Return the config-order index of the managed root containing *folder*.

        Lower index means higher priority.  Returns ``None`` when the folder
        does not fall under any configured series managed root.
        """
        for index, mapping in enumerate(self.config.paths.series_root_mappings):
            managed_root = Path(mapping.nested_root)
            try:
                folder.relative_to(managed_root)
                return index
            except ValueError:
                continue
        return None

    def _find_existing_series(self, candidate: dict, target_path: Path) -> dict | None:
        try:
            existing_series = self._sonarr().get_series()
        except requests.RequestException:
            return None

        candidate_tvdb_id = candidate.get("tvdbId")
        if isinstance(candidate_tvdb_id, int):
            for series in existing_series:
                if int(series.get("tvdbId") or 0) == candidate_tvdb_id:
                    return series

        target_path_text = str(target_path)
        for series in existing_series:
            series_path = str(series.get("path") or "").strip()
            if series_path == target_path_text:
                return series

        return None

    def auto_add_series_for_folder(self, folder: Path, managed_root: Path) -> dict | None:
        ref = parse_movie_ref(folder.name)
        term = f"{ref.title} {ref.year}" if ref.year is not None else ref.title

        try:
            candidates = self._sonarr().lookup_series(term)
        except requests.RequestException as exc:
            self.log.warning("Sonarr lookup failed for folder=%s term=%s: %s", folder, term, exc)
            return None

        candidate = pick_lookup_candidate(folder, candidates)
        if candidate is None:
            self.log.warning(
                "No safe Sonarr lookup match for folder: %s (lookup_term=%s)",
                folder,
                term,
            )
            return None

        quality_profile_id = self._resolve_auto_add_quality_profile_id(folder)
        if quality_profile_id is None:
            self.log.warning(
                "Skipping Sonarr auto-add for folder=%s because no quality profile id "
                "is available.",
                folder,
            )
            return None

        language_profile_id = self._resolve_auto_add_language_profile_id(folder)

        canonical_name = self._canonical_name_from_series(candidate, folder)
        existing_series = self._find_existing_series(candidate, folder)
        if existing_series is not None:
            existing_path = str(existing_series.get("path") or "").strip()
            target_path = str(folder)
            if existing_path != target_path:
                # Deterministic tie-break: only update the Arr path when the
                # new folder has equal or higher priority (lower config index)
                # than the folder Arr currently points to.
                existing_priority = self._managed_root_priority(Path(existing_path))
                new_priority = self._managed_root_priority(folder)
                if (
                    existing_priority is not None
                    and new_priority is not None
                    and new_priority > existing_priority
                ):
                    self.log.info(
                        "Skipping path update for series_id=%s; existing path has "
                        "higher root priority (existing_idx=%s new_idx=%s) "
                        "folder=%s existing_path=%s",
                        existing_series.get("id"),
                        existing_priority,
                        new_priority,
                        folder,
                        existing_path,
                    )
                    return existing_series

                try:
                    self._sonarr().update_series_path(existing_series, target_path)
                    existing_series["path"] = target_path
                    self.log.info(
                        "Updated existing Sonarr series path for folder=%s canonical=%s "
                        "series_id=%s",
                        folder,
                        canonical_name,
                        existing_series.get("id"),
                    )
                except requests.RequestException as exc:
                    self.log.warning(
                        "Failed to update existing Sonarr series path for folder=%s canonical=%s "
                        "series_id=%s: %s",
                        folder,
                        canonical_name,
                        existing_series.get("id"),
                        exc,
                    )
                    return None
            self.log.info(
                "Series already present in Sonarr; skipping auto-add for folder=%s canonical=%s "
                "series_id=%s",
                folder,
                canonical_name,
                existing_series.get("id"),
            )
            return existing_series

        try:
            added_series = self._sonarr().add_series_from_lookup(
                candidate,
                path=str(folder),
                root_folder_path=str(managed_root),
                quality_profile_id=quality_profile_id,
                language_profile_id=language_profile_id,
                monitored=self.config.sonarr.auto_add_monitored,
                season_folder=self.config.sonarr.auto_add_season_folder,
                search_for_missing_episodes=self.config.sonarr.auto_add_search_on_add,
            )
        except requests.RequestException as exc:
            self.log.warning(
                "Sonarr auto-add failed for folder=%s canonical=%s profile_id=%s: %s",
                folder,
                canonical_name,
                quality_profile_id,
                exc,
            )
            return None

        self.log.info(
            "Auto-added series in Sonarr: folder=%s canonical=%s series_id=%s",
            folder,
            canonical_name,
            added_series.get("id"),
        )
        return added_series
