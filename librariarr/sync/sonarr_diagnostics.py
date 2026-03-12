from __future__ import annotations

import logging

from ..clients.sonarr import SonarrClient
from ..config import AppConfig
from .radarr_mapping import format_id_name_pairs


def _log_quality_profile_diagnostics(
    *,
    config: AppConfig,
    log: logging.Logger,
    sonarr: SonarrClient,
    auto_add_unmatched: bool,
) -> None:
    try:
        profiles = sonarr.get_quality_profiles()
        profile_pairs = format_id_name_pairs(profiles)
        if profile_pairs:
            log.info("Sonarr quality profiles (id:name): %s", profile_pairs)

        available_profile_ids = {
            profile_id
            for profile_id in (profile.get("id") for profile in profiles)
            if isinstance(profile_id, int)
        }

        configured_profile_id = config.sonarr.auto_add_quality_profile_id
        if configured_profile_id is not None and configured_profile_id not in available_profile_ids:
            log.warning(
                "sonarr.auto_add_quality_profile_id is not present in Sonarr quality profiles: "
                "configured_profile_id=%s available_profile_ids=%s",
                configured_profile_id,
                sorted(available_profile_ids),
            )

        mapped_profile_ids = sorted(
            {
                rule.profile_id
                for rule in config.sonarr.mapping.quality_profile_map
                if isinstance(rule.profile_id, int)
            }
        )
        if mapped_profile_ids:
            missing_profile_ids = [
                profile_id
                for profile_id in mapped_profile_ids
                if profile_id not in available_profile_ids
            ]
            if missing_profile_ids:
                log.warning(
                    "sonarr.mapping.quality_profile_map profile_id values not found in "
                    "Sonarr quality profiles: configured_ids=%s missing_ids=%s",
                    mapped_profile_ids,
                    missing_profile_ids,
                )
            else:
                log.info(
                    "sonarr.mapping.quality_profile_map profile_id values validated against "
                    "Sonarr quality profiles: %s",
                    mapped_profile_ids,
                )

        if auto_add_unmatched:
            log.info(
                "Sonarr auto-add unmatched is enabled: quality_profile_id=%s "
                "(null=map via sonarr.mapping.quality_profile_map then fallback to lowest id), "
                "monitored=%s search_on_add=%s season_folder=%s",
                config.sonarr.auto_add_quality_profile_id,
                config.sonarr.auto_add_monitored,
                config.sonarr.auto_add_search_on_add,
                config.sonarr.auto_add_season_folder,
            )
    except Exception as exc:
        log.warning("Unable to fetch Sonarr quality profiles: %s", exc)


def _log_language_profile_diagnostics(
    *,
    config: AppConfig,
    log: logging.Logger,
    sonarr: SonarrClient,
) -> None:
    try:
        profiles = sonarr.get_language_profiles()
        profile_pairs = format_id_name_pairs(profiles)
        if profile_pairs:
            log.info("Sonarr language profiles (id:name): %s", profile_pairs)

        available_profile_ids = {
            profile_id
            for profile_id in (profile.get("id") for profile in profiles)
            if isinstance(profile_id, int)
        }

        configured_profile_id = config.sonarr.auto_add_language_profile_id
        if configured_profile_id is not None and configured_profile_id not in available_profile_ids:
            log.warning(
                "sonarr.auto_add_language_profile_id is not present in Sonarr language profiles: "
                "configured_profile_id=%s available_profile_ids=%s",
                configured_profile_id,
                sorted(available_profile_ids),
            )

        mapped_profile_ids = sorted(
            {
                rule.profile_id
                for rule in config.sonarr.mapping.language_profile_map
                if isinstance(rule.profile_id, int)
            }
        )
        if mapped_profile_ids:
            missing_profile_ids = [
                profile_id
                for profile_id in mapped_profile_ids
                if profile_id not in available_profile_ids
            ]
            if missing_profile_ids:
                log.warning(
                    "sonarr.mapping.language_profile_map profile_id values not found in "
                    "Sonarr language profiles: configured_ids=%s missing_ids=%s",
                    mapped_profile_ids,
                    missing_profile_ids,
                )
            else:
                log.info(
                    "sonarr.mapping.language_profile_map profile_id values validated against "
                    "Sonarr language profiles: %s",
                    mapped_profile_ids,
                )
    except Exception as exc:
        log.warning("Unable to fetch Sonarr language profiles: %s", exc)


def log_profile_mapping_diagnostics(
    *,
    config: AppConfig,
    log: logging.Logger,
    sonarr: SonarrClient,
    auto_add_unmatched: bool,
) -> None:
    quality_map_ids = sorted(
        {
            rule.profile_id
            for rule in config.sonarr.mapping.quality_profile_map
            if isinstance(rule.profile_id, int)
        }
    )
    language_map_ids = sorted(
        {
            rule.profile_id
            for rule in config.sonarr.mapping.language_profile_map
            if isinstance(rule.profile_id, int)
        }
    )

    if quality_map_ids:
        log.info(
            "sonarr.mapping.quality_profile_map contains profile ids for local analysis: %s",
            quality_map_ids,
        )
    else:
        log.info(
            "sonarr.mapping.quality_profile_map is empty; Sonarr uses configured "
            "auto_add_quality_profile_id or lowest available id."
        )

    if language_map_ids:
        log.info(
            "sonarr.mapping.language_profile_map contains profile ids for local analysis: %s",
            language_map_ids,
        )
    else:
        log.info(
            "sonarr.mapping.language_profile_map is empty; Sonarr uses configured "
            "auto_add_language_profile_id or lowest available id."
        )

    _log_quality_profile_diagnostics(
        config=config,
        log=log,
        sonarr=sonarr,
        auto_add_unmatched=auto_add_unmatched,
    )
    _log_language_profile_diagnostics(
        config=config,
        log=log,
        sonarr=sonarr,
    )
