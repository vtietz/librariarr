from __future__ import annotations

import logging

from ..config import AppConfig
from ..radarr import RadarrClient
from .radarr_mapping import extract_id_name, format_id_name_pairs


def _log_profile_diagnostics(
    *,
    config: AppConfig,
    log: logging.Logger,
    radarr: RadarrClient,
    auto_add_unmatched: bool,
) -> None:
    try:
        profiles = radarr.get_quality_profiles()
        profile_pairs = format_id_name_pairs(profiles)
        if profile_pairs:
            log.info("Radarr quality profiles (id:name): %s", profile_pairs)

        profile_ids = {
            profile_id
            for profile_id in (profile.get("id") for profile in profiles)
            if isinstance(profile_id, int)
        }
        configured_profile_id = config.radarr.auto_add_quality_profile_id
        if configured_profile_id is not None and configured_profile_id not in profile_ids:
            log.warning(
                "radarr.auto_add_quality_profile_id is not present in Radarr profiles: "
                "configured_profile_id=%s available_profile_ids=%s",
                configured_profile_id,
                sorted(profile_ids),
            )
        if auto_add_unmatched:
            log.info(
                "Auto-add unmatched is enabled: quality_profile_id=%s "
                "(null=auto-map from parse/custom_format_map/quality_map), "
                "monitored=%s search_on_add=%s",
                config.radarr.auto_add_quality_profile_id,
                config.radarr.auto_add_monitored,
                config.radarr.auto_add_search_on_add,
            )
    except Exception as exc:
        log.warning("Unable to fetch Radarr quality profiles: %s", exc)


def _log_quality_definition_diagnostics(
    *,
    rule_ids: list[int],
    log: logging.Logger,
    radarr: RadarrClient,
) -> None:
    if not rule_ids:
        return

    try:
        definitions = radarr.get_quality_definitions()
        definition_pairs = format_id_name_pairs(definitions)
        if definition_pairs:
            log.info("Radarr quality definitions (id:name): %s", definition_pairs)

        definition_ids = {
            definition_id
            for definition_id, _ in (extract_id_name(item) for item in definitions)
            if definition_id is not None
        }
        missing_ids = [rule_id for rule_id in rule_ids if rule_id not in definition_ids]
        if missing_ids:
            log.warning(
                "quality_map target_id values not found in Radarr quality definitions: "
                "configured_ids=%s missing_ids=%s",
                rule_ids,
                missing_ids,
            )
        else:
            log.info(
                "quality_map target_id values validated against Radarr quality definitions: %s",
                rule_ids,
            )
    except Exception as exc:
        log.warning("Unable to fetch Radarr quality definitions: %s", exc)


def _log_custom_format_diagnostics(
    *,
    custom_format_ids: list[int],
    log: logging.Logger,
    radarr: RadarrClient,
) -> None:
    if not custom_format_ids:
        return

    try:
        custom_formats = radarr.get_custom_formats()
        custom_format_pairs = format_id_name_pairs(custom_formats)
        if custom_format_pairs:
            log.info("Radarr custom formats (id:name): %s", custom_format_pairs)

        known_custom_format_ids = {
            format_id
            for format_id, _ in (extract_id_name(item) for item in custom_formats)
            if format_id is not None
        }
        missing_format_ids = [
            format_id for format_id in custom_format_ids if format_id not in known_custom_format_ids
        ]
        if missing_format_ids:
            log.warning(
                "custom_format_map format_id values not found in Radarr custom formats: "
                "configured_ids=%s missing_ids=%s",
                custom_format_ids,
                missing_format_ids,
            )
        else:
            log.info(
                "custom_format_map format_id values validated against Radarr custom formats: %s",
                custom_format_ids,
            )
    except Exception as exc:
        log.warning("Unable to fetch Radarr custom formats: %s", exc)


def log_quality_mapping_diagnostics(
    *,
    config: AppConfig,
    log: logging.Logger,
    radarr: RadarrClient,
    auto_add_unmatched: bool,
) -> None:
    rule_ids = sorted({rule.target_id for rule in config.quality_map})
    custom_format_ids = sorted({rule.format_id for rule in config.custom_format_map})
    if not rule_ids:
        log.info("quality_map is empty; no quality-id override will be applied.")
    if custom_format_ids:
        log.info(
            "custom_format_map contains format ids for local analysis fallback: %s",
            custom_format_ids,
        )
    else:
        log.info("custom_format_map is empty; only Radarr parse/profile metadata is used.")

    _log_profile_diagnostics(
        config=config,
        log=log,
        radarr=radarr,
        auto_add_unmatched=auto_add_unmatched,
    )
    _log_quality_definition_diagnostics(
        rule_ids=rule_ids,
        log=log,
        radarr=radarr,
    )
    _log_custom_format_diagnostics(
        custom_format_ids=custom_format_ids,
        log=log,
        radarr=radarr,
    )
