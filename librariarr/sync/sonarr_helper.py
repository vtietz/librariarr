from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import requests

from ..clients.sonarr import SonarrClient
from ..config import AppConfig
from ..quality import map_profile_id
from .naming import parse_movie_ref
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

    def _get_auto_add_language_profiles(self) -> list[dict]:
        if self._auto_add_language_profiles_cache is not None:
            return self._auto_add_language_profiles_cache

        try:
            profiles = self._sonarr().get_language_profiles()
        except requests.RequestException:
            profiles = []
        self._auto_add_language_profiles_cache = profiles
        return profiles

    def _resolve_auto_add_quality_profile_id(self, folder: Path) -> int | None:
        configured_profile_id = self.config.sonarr.auto_add_quality_profile_id
        if configured_profile_id is not None:
            return configured_profile_id

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
                self.log.info(
                    "Sonarr auto-add: mapped folder=%s to quality_profile_id=%s "
                    "via sonarr.mapping.quality_profile_map",
                    folder,
                    mapped_profile_id,
                )
                return mapped_profile_id

        if self._auto_add_quality_profile_id_cache is not None:
            return self._auto_add_quality_profile_id_cache

        profiles = self._get_auto_add_profiles()
        profile_ids = sorted(
            profile_id
            for profile_id in (profile.get("id") for profile in profiles)
            if isinstance(profile_id, int)
        )
        if not profile_ids:
            return None

        self._auto_add_quality_profile_id_cache = profile_ids[0]
        return self._auto_add_quality_profile_id_cache

    def _resolve_auto_add_language_profile_id(self, folder: Path) -> int | None:
        configured_profile_id = self.config.sonarr.auto_add_language_profile_id
        if configured_profile_id is not None:
            return configured_profile_id

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
                self.log.info(
                    "Sonarr auto-add: mapped folder=%s to language_profile_id=%s "
                    "via sonarr.mapping.language_profile_map",
                    folder,
                    mapped_profile_id,
                )
                return mapped_profile_id

        if self._auto_add_language_profile_id_cache is not None:
            return self._auto_add_language_profile_id_cache

        profiles = self._get_auto_add_language_profiles()
        profile_ids = sorted(
            profile_id
            for profile_id in (profile.get("id") for profile in profiles)
            if isinstance(profile_id, int)
        )
        if not profile_ids:
            return None

        self._auto_add_language_profile_id_cache = profile_ids[0]
        return self._auto_add_language_profile_id_cache

    def _canonical_name_from_series(self, series: dict, fallback_folder: Path) -> str:
        title = str(series.get("title") or "").strip() or fallback_folder.name
        year = series.get("year")
        if isinstance(year, int):
            return f"{title} ({year})"
        return title

    def auto_add_series_for_folder(self, folder: Path, shadow_root: Path) -> dict | None:
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
        link_path = shadow_root / canonical_name
        try:
            added_series = self._sonarr().add_series_from_lookup(
                candidate,
                path=str(link_path),
                root_folder_path=str(shadow_root),
                quality_profile_id=quality_profile_id,
                language_profile_id=language_profile_id,
                monitored=self.config.sonarr.auto_add_monitored,
                season_folder=self.config.sonarr.auto_add_season_folder,
                search_for_missing_episodes=self.config.sonarr.auto_add_search_on_add,
            )
        except requests.HTTPError as exc:
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
