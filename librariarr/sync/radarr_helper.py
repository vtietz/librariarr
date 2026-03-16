from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import requests

from ..clients.radarr import RadarrClient
from ..config import AppConfig
from ..quality import VIDEO_EXTENSIONS, map_custom_format_ids, map_quality_id
from .naming import canonical_name_from_folder, parse_movie_ref, safe_path_component
from .radarr_diagnostics import log_quality_mapping_diagnostics
from .radarr_mapping import (
    extract_id_name,
    extract_parse_custom_format_ids,
    extract_parse_quality_definition_id,
    parse_candidates_for_folder,
    pick_lookup_candidate,
)
from .radarr_profile import (
    score_profile_for_custom_formats,
    score_profile_for_quality,
    sorted_profile_ids,
)


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
        self._auto_add_profile_by_custom_formats_cache: dict[
            tuple[int | None, tuple[int, ...]], int
        ] = {}
        self._auto_add_profiles_cache: list[dict] | None = None
        self._quality_definition_rank_cache: dict[int, int] | None = None
        self._cached_radarr_client_id: int | None = None

    def _radarr(self) -> RadarrClient:
        client = self._get_radarr_client()
        client_id = id(client)
        if self._cached_radarr_client_id != client_id:
            self._cached_radarr_client_id = client_id
            self._auto_add_quality_profile_id_cache = None
            self._auto_add_profile_by_quality_cache = {}
            self._auto_add_profile_by_custom_formats_cache = {}
            self._auto_add_profiles_cache = None
            self._quality_definition_rank_cache = None
        return client

    def log_quality_mapping_diagnostics(self, auto_add_unmatched: bool) -> None:
        log_quality_mapping_diagnostics(
            config=self.config,
            log=self.log,
            radarr=self._radarr(),
            auto_add_unmatched=auto_add_unmatched,
        )

    def _get_quality_definition_rank_map(self) -> dict[int, int]:
        if self._quality_definition_rank_cache is not None:
            return self._quality_definition_rank_cache

        try:
            definitions = self._radarr().get_quality_definitions()
        except Exception as exc:
            self.log.warning(
                "Unable to fetch Radarr quality definitions for auto-add profile ranking: %s",
                exc,
            )
            self._quality_definition_rank_cache = {}
            return self._quality_definition_rank_cache

        definition_ids = sorted(
            definition_id
            for definition_id, _ in (extract_id_name(item) for item in definitions)
            if definition_id is not None
        )
        self._quality_definition_rank_cache = {
            definition_id: rank for rank, definition_id in enumerate(definition_ids)
        }
        return self._quality_definition_rank_cache

    def _detect_custom_format_ids(self, folder: Path) -> set[int]:
        detected_ids: set[int] = set()
        custom_format_map = self.config.effective_radarr_custom_format_map()

        for candidate in parse_candidates_for_folder(folder, VIDEO_EXTENSIONS):
            if not candidate.strip():
                continue
            try:
                parse_result = self._radarr().parse_title(candidate)
            except Exception as exc:
                self.log.debug("Radarr parse failed for title=%s: %s", candidate, exc)
                continue

            detected_ids.update(extract_parse_custom_format_ids(parse_result))
            if detected_ids:
                break

        if custom_format_map:
            detected_ids.update(
                map_custom_format_ids(
                    folder,
                    custom_format_map,
                    use_nfo=self.config.analysis.use_nfo,
                    use_media_probe=self.config.analysis.use_media_probe,
                    media_probe_bin=self.config.analysis.media_probe_bin,
                )
            )

        return detected_ids

    def _get_auto_add_profiles(self) -> list[dict]:
        if self._auto_add_profiles_cache is not None:
            return self._auto_add_profiles_cache

        profiles = self._radarr().get_quality_profiles()
        self._auto_add_profiles_cache = profiles
        return profiles

    def _detect_parse_quality_definition_id(self, folder: Path) -> int | None:
        for candidate in parse_candidates_for_folder(folder, VIDEO_EXTENSIONS):
            if not candidate.strip():
                continue
            try:
                parse_result = self._radarr().parse_title(candidate)
            except Exception as exc:
                self.log.debug("Radarr parse failed for title=%s: %s", candidate, exc)
                continue

            quality_definition_id = extract_parse_quality_definition_id(parse_result)
            if quality_definition_id is not None:
                return quality_definition_id

        return None

    def _resolve_profile_from_quality_definition_id(
        self,
        folder: Path,
        profiles: list[dict],
        desired_quality_id: int,
        source: str,
    ) -> int | None:
        if desired_quality_id in self._auto_add_profile_by_quality_cache:
            return self._auto_add_profile_by_quality_cache[desired_quality_id]

        rank_map = self._get_quality_definition_rank_map()
        ranked_profiles: list[tuple[tuple[int, int, int, int, int, int], int, str]] = []
        for profile in profiles:
            ranked = score_profile_for_quality(profile, desired_quality_id, rank_map)
            if ranked is None:
                continue
            score, reason = ranked
            profile_id = profile.get("id")
            if isinstance(profile_id, int):
                ranked_profiles.append((score, profile_id, reason))

        if not ranked_profiles:
            return None

        ranked_profiles.sort(key=lambda item: item[0])
        _, selected_profile_id, selection_reason = ranked_profiles[0]
        self._auto_add_profile_by_quality_cache[desired_quality_id] = selected_profile_id
        self.log.info(
            "Auto-add unmatched: mapped folder=%s quality_definition_id=%s "
            "to quality_profile_id=%s selection_reason=%s source=%s",
            folder,
            desired_quality_id,
            selected_profile_id,
            selection_reason,
            source,
        )
        return selected_profile_id

    def _fallback_to_lowest_profile(
        self,
        profiles: list[dict],
        message: str,
        level: str = "info",
    ) -> int | None:
        if self._auto_add_quality_profile_id_cache is not None:
            return self._auto_add_quality_profile_id_cache

        profile_ids = sorted_profile_ids(profiles)
        if not profile_ids:
            self.log.warning(
                "No Radarr quality profiles available; set radarr.auto_add_quality_profile_id "
                "or create profiles in Radarr."
            )
            return None

        self._auto_add_quality_profile_id_cache = profile_ids[0]
        log_fn = self.log.warning if level == "warning" else self.log.info
        log_fn(message, self._auto_add_quality_profile_id_cache)
        return self._auto_add_quality_profile_id_cache

    def _resolve_profile_from_custom_formats(
        self,
        folder: Path,
        profiles: list[dict],
    ) -> int | None:
        detected_custom_format_ids = self._detect_custom_format_ids(folder)
        if not detected_custom_format_ids:
            return None

        parse_quality_id = self._detect_parse_quality_definition_id(folder)
        detected_key = (parse_quality_id, tuple(sorted(detected_custom_format_ids)))
        if detected_key in self._auto_add_profile_by_custom_formats_cache:
            return self._auto_add_profile_by_custom_formats_cache[detected_key]

        custom_ranked_profiles: list[tuple[tuple[int, int, int, int], int, str]] = []
        for profile in profiles:
            ranked = score_profile_for_custom_formats(
                profile,
                detected_custom_format_ids,
                desired_quality_id=parse_quality_id,
            )
            if ranked is None:
                continue
            score, reason = ranked
            profile_id = profile.get("id")
            if isinstance(profile_id, int):
                custom_ranked_profiles.append((score, profile_id, reason))

        if not custom_ranked_profiles:
            return None

        custom_ranked_profiles.sort(key=lambda item: item[0])
        _, selected_profile_id, selection_reason = custom_ranked_profiles[0]
        self._auto_add_profile_by_custom_formats_cache[detected_key] = selected_profile_id
        self.log.info(
            "Auto-add unmatched: mapped folder=%s custom_format_ids=%s "
            "to quality_profile_id=%s selection_reason=%s parse_quality_definition_id=%s",
            folder,
            list(detected_key[1]),
            selected_profile_id,
            selection_reason,
            parse_quality_id,
        )
        return selected_profile_id

    def _resolve_profile_from_quality_map(self, folder: Path, profiles: list[dict]) -> int | None:
        quality_map = self.config.effective_radarr_quality_map()
        if not quality_map:
            parse_quality_id = self._detect_parse_quality_definition_id(folder)
            if parse_quality_id is not None:
                parse_profile_id = self._resolve_profile_from_quality_definition_id(
                    folder,
                    profiles,
                    parse_quality_id,
                    source="radarr_parse_quality",
                )
                if parse_profile_id is not None:
                    return parse_profile_id
                return self._fallback_to_lowest_profile(
                    profiles,
                    f"Auto-add unmatched: parse returned quality_definition_id={parse_quality_id} "
                    "but no profile mapped and no quality_map fallback is configured; "
                    "using lowest profile id=%s",
                    level="warning",
                )

            return self._fallback_to_lowest_profile(
                profiles,
                "Auto-add unmatched: no custom format signal, no parse quality signal, "
                "and no quality_map; "
                "using lowest profile id=%s",
            )

        desired_quality_id = map_quality_id(
            folder,
            quality_map,
            use_nfo=self.config.analysis.use_nfo,
            use_media_probe=self.config.analysis.use_media_probe,
            media_probe_bin=self.config.analysis.media_probe_bin,
        )

        selected_profile_id = self._resolve_profile_from_quality_definition_id(
            folder,
            profiles,
            desired_quality_id,
            source="quality_map",
        )
        if selected_profile_id is not None:
            return selected_profile_id

        return self._fallback_to_lowest_profile(
            profiles,
            "Auto-add unmatched: no quality profile mapped to "
            f"quality_definition_id={desired_quality_id}; "
            "falling back to lowest profile id=%s",
            level="warning",
        )

    def _resolve_auto_add_quality_profile_id(self, folder: Path) -> int | None:
        configured_profile_id = self.config.radarr.auto_add_quality_profile_id
        if configured_profile_id is not None:
            return configured_profile_id

        try:
            profiles = self._get_auto_add_profiles()
        except Exception as exc:
            self.log.warning("Unable to fetch Radarr quality profiles for auto-add: %s", exc)
            return None

        selected_custom_profile_id = self._resolve_profile_from_custom_formats(folder, profiles)
        if selected_custom_profile_id is not None:
            return selected_custom_profile_id

        return self._resolve_profile_from_quality_map(folder, profiles)

    def _canonical_name_from_movie(self, movie: dict, fallback_folder: Path) -> str:
        del movie
        return canonical_name_from_folder(safe_path_component(fallback_folder.name))

    def auto_add_movie_for_folder(self, folder: Path, shadow_root: Path) -> dict | None:
        ref = parse_movie_ref(folder.name)
        term = f"{ref.title} {ref.year}" if ref.year is not None else ref.title

        try:
            candidates = self._radarr().lookup_movies(term)
        except requests.RequestException as exc:
            self.log.warning("Radarr lookup failed for folder=%s term=%s: %s", folder, term, exc)
            return None

        candidate = pick_lookup_candidate(folder, candidates)
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
