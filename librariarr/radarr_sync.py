from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path

import requests

from .config import AppConfig
from .quality import map_quality_id
from .radarr import RadarrClient
from .sync import parse_movie_ref


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
        self._auto_add_quality_profile_id_cache: int | None = None
        self._auto_add_profile_by_quality_cache: dict[int, int] = {}
        self._auto_add_profiles_cache: list[dict] | None = None
        self._cached_radarr_client_id: int | None = None

    def _radarr(self) -> RadarrClient:
        client = self._get_radarr_client()
        client_id = id(client)
        if self._cached_radarr_client_id != client_id:
            self._cached_radarr_client_id = client_id
            self._auto_add_quality_profile_id_cache = None
            self._auto_add_profile_by_quality_cache = {}
            self._auto_add_profiles_cache = None
        return client

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

    def log_quality_mapping_diagnostics(self, auto_add_unmatched: bool) -> None:
        rule_ids = sorted({rule.target_id for rule in self.config.quality_map})
        if not rule_ids:
            self.log.info("quality_map is empty; default quality id fallback applies (id=4).")
            return

        try:
            profiles = self._radarr().get_quality_profiles()
            profile_pairs = self._format_id_name_pairs(profiles)
            if profile_pairs:
                self.log.info("Radarr quality profiles (id:name): %s", profile_pairs)

            profile_ids = {
                profile_id
                for profile_id in (profile.get("id") for profile in profiles)
                if isinstance(profile_id, int)
            }
            configured_profile_id = self.config.radarr.auto_add_quality_profile_id
            if configured_profile_id is not None and configured_profile_id not in profile_ids:
                self.log.warning(
                    "radarr.auto_add_quality_profile_id is not present in Radarr profiles: "
                    "configured_profile_id=%s available_profile_ids=%s",
                    configured_profile_id,
                    sorted(profile_ids),
                )
            if auto_add_unmatched:
                self.log.info(
                    "Auto-add unmatched is enabled: quality_profile_id=%s "
                    "(null=auto-map from quality_map), monitored=%s search_on_add=%s",
                    self.config.radarr.auto_add_quality_profile_id,
                    self.config.radarr.auto_add_monitored,
                    self.config.radarr.auto_add_search_on_add,
                )
        except Exception as exc:
            self.log.warning("Unable to fetch Radarr quality profiles: %s", exc)

        try:
            definitions = self._radarr().get_quality_definitions()
            definition_pairs = self._format_id_name_pairs(definitions)
            if definition_pairs:
                self.log.info("Radarr quality definitions (id:name): %s", definition_pairs)

            definition_ids = {
                definition_id
                for definition_id, _ in (
                    self._extract_quality_id_name(item) for item in definitions
                )
                if definition_id is not None
            }
            missing_ids = [rule_id for rule_id in rule_ids if rule_id not in definition_ids]
            if missing_ids:
                self.log.warning(
                    "quality_map target_id values not found in Radarr quality definitions: "
                    "configured_ids=%s missing_ids=%s",
                    rule_ids,
                    missing_ids,
                )
            else:
                self.log.info(
                    "quality_map target_id values validated against Radarr quality definitions: %s",
                    rule_ids,
                )
        except Exception as exc:
            self.log.warning("Unable to fetch Radarr quality definitions: %s", exc)

    def _normalize_title_token(self, title: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", title.strip().lower())

    def _extract_profile_quality_definition_ids(self, profile: dict) -> set[int]:
        items = profile.get("items")
        if not isinstance(items, list):
            return set()

        ids: set[int] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            quality = item.get("quality")
            if isinstance(quality, dict):
                quality_id = quality.get("id")
                if isinstance(quality_id, int):
                    ids.add(quality_id)
        return ids

    def _get_auto_add_profiles(self) -> list[dict]:
        if self._auto_add_profiles_cache is not None:
            return self._auto_add_profiles_cache

        profiles = self._radarr().get_quality_profiles()
        self._auto_add_profiles_cache = profiles
        return profiles

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

    def _resolve_auto_add_quality_profile_id(self, folder: Path) -> int | None:
        configured_profile_id = self.config.radarr.auto_add_quality_profile_id
        if configured_profile_id is not None:
            return configured_profile_id

        try:
            profiles = self._get_auto_add_profiles()
        except Exception as exc:
            self.log.warning("Unable to fetch Radarr quality profiles for auto-add: %s", exc)
            return None

        desired_quality_id = map_quality_id(
            folder,
            self.config.quality_map,
            use_nfo=self.config.analysis.use_nfo,
            use_media_probe=self.config.analysis.use_media_probe,
            media_probe_bin=self.config.analysis.media_probe_bin,
        )

        if desired_quality_id in self._auto_add_profile_by_quality_cache:
            return self._auto_add_profile_by_quality_cache[desired_quality_id]

        matching_profile_ids = sorted(
            profile_id
            for profile in profiles
            for profile_id in [profile.get("id")]
            if isinstance(profile_id, int)
            and desired_quality_id in self._extract_profile_quality_definition_ids(profile)
        )

        if matching_profile_ids:
            selected_profile_id = matching_profile_ids[0]
            self._auto_add_profile_by_quality_cache[desired_quality_id] = selected_profile_id
            self.log.info(
                "Auto-add unmatched: mapped folder=%s quality_definition_id=%s "
                "to quality_profile_id=%s",
                folder,
                desired_quality_id,
                selected_profile_id,
            )
            return selected_profile_id

        if self._auto_add_quality_profile_id_cache is not None:
            return self._auto_add_quality_profile_id_cache

        profile_ids = sorted(
            profile_id
            for profile_id in (profile.get("id") for profile in profiles)
            if isinstance(profile_id, int)
        )
        if not profile_ids:
            self.log.warning(
                "No Radarr quality profiles available; set radarr.auto_add_quality_profile_id "
                "or create profiles in Radarr."
            )
            return None

        self._auto_add_quality_profile_id_cache = profile_ids[0]
        self.log.warning(
            "Auto-add unmatched: no quality profile mapped to quality_definition_id=%s; "
            "falling back to lowest profile id=%s",
            desired_quality_id,
            self._auto_add_quality_profile_id_cache,
        )
        return self._auto_add_quality_profile_id_cache

    def _canonical_name_from_movie(self, movie: dict, fallback_folder: Path) -> str:
        title = str(movie.get("title") or "").strip() or fallback_folder.name
        year = movie.get("year")
        if isinstance(year, int):
            return f"{title} ({year})"
        return title

    def auto_add_movie_for_folder(self, folder: Path, shadow_root: Path) -> dict | None:
        ref = parse_movie_ref(folder.name)
        term = f"{ref.title} {ref.year}" if ref.year is not None else ref.title

        try:
            candidates = self._radarr().lookup_movies(term)
        except requests.RequestException as exc:
            self.log.warning("Radarr lookup failed for folder=%s term=%s: %s", folder, term, exc)
            return None

        candidate = self._pick_lookup_candidate(folder, candidates)
        if candidate is None:
            self.log.warning(
                "No safe Radarr lookup match for folder: %s (lookup_term=%s)",
                folder,
                term,
            )
            return None

        quality_profile_id = self._resolve_auto_add_quality_profile_id(folder)
        if quality_profile_id is None:
            self.log.warning(
                "Skipping auto-add for folder=%s because no quality profile id is available.",
                folder,
            )
            return None

        canonical_name = self._canonical_name_from_movie(candidate, folder)
        link_path = shadow_root / canonical_name
        try:
            added_movie = self._radarr().add_movie_from_lookup(
                candidate,
                path=str(link_path),
                root_folder_path=str(shadow_root),
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
