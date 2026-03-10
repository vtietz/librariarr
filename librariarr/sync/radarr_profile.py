from __future__ import annotations

import re


def profile_is_generic(profile: dict) -> bool:
    name = str(profile.get("name") or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "", name)
    return normalized in {"any", "all", "default"}


def extract_profile_quality_definition_ids(profile: dict) -> set[int]:
    items = profile.get("items")
    if not isinstance(items, list):
        return set()

    ids: set[int] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        if not bool(item.get("allowed", True)):
            continue
        quality = item.get("quality")
        if isinstance(quality, dict):
            quality_id = quality.get("id")
            if isinstance(quality_id, int):
                ids.add(quality_id)
    return ids


def extract_profile_cutoff_quality_definition_id(profile: dict) -> int | None:
    cutoff = profile.get("cutoff")
    if isinstance(cutoff, int):
        return cutoff
    if isinstance(cutoff, dict):
        cutoff_id = cutoff.get("id")
        if isinstance(cutoff_id, int):
            return cutoff_id
    return None


def quality_rank(quality_definition_id: int, rank_map: dict[int, int]) -> int:
    return rank_map.get(quality_definition_id, quality_definition_id)


def score_profile_for_quality(
    profile: dict,
    desired_quality_id: int,
    rank_map: dict[int, int],
) -> tuple[tuple[int, int, int, int, int, int], str] | None:
    profile_id = profile.get("id")
    if not isinstance(profile_id, int):
        return None

    allowed_quality_ids = extract_profile_quality_definition_ids(profile)
    if desired_quality_id not in allowed_quality_ids:
        return None

    generic_penalty = 1 if profile_is_generic(profile) else 0
    allowed_count = len(allowed_quality_ids)

    cutoff_quality_id = extract_profile_cutoff_quality_definition_id(profile)
    if cutoff_quality_id == desired_quality_id:
        return (0, 0, 0, generic_penalty, allowed_count, profile_id), "cutoff_exact"

    if cutoff_quality_id is None:
        return (2, 1, 1_000_000, generic_penalty, allowed_count, profile_id), "allowed_only"

    desired_rank = quality_rank(desired_quality_id, rank_map)
    cutoff_rank = quality_rank(cutoff_quality_id, rank_map)
    cutoff_below_desired = 0 if cutoff_rank >= desired_rank else 1
    cutoff_distance = abs(cutoff_rank - desired_rank)
    return (
        1,
        cutoff_below_desired,
        cutoff_distance,
        generic_penalty,
        allowed_count,
        profile_id,
    ), "nearest_cutoff"


def score_profile_for_custom_formats(
    profile: dict,
    custom_format_ids: set[int],
) -> tuple[tuple[int, int, int, int], str] | None:
    profile_id = profile.get("id")
    if not isinstance(profile_id, int):
        return None

    format_items = profile.get("formatItems")
    if not isinstance(format_items, list) or not format_items:
        return None

    score = 0
    matched_count = 0
    for item in format_items:
        if not isinstance(item, dict):
            continue
        format_id = item.get("format")
        if not isinstance(format_id, int) or format_id not in custom_format_ids:
            continue
        item_score = item.get("score")
        score += item_score if isinstance(item_score, int) else 0
        matched_count += 1

    if matched_count == 0:
        return None

    min_format_score_raw = profile.get("minFormatScore")
    min_format_score = min_format_score_raw if isinstance(min_format_score_raw, int) else 0
    min_not_met = 0 if score >= min_format_score else 1
    generic_penalty = 1 if profile_is_generic(profile) else 0

    return (min_not_met, -score, generic_penalty, profile_id), "custom_formats"


def sorted_profile_ids(profiles: list[dict]) -> list[int]:
    return sorted(
        profile_id
        for profile_id in (profile.get("id") for profile in profiles)
        if isinstance(profile_id, int)
    )
