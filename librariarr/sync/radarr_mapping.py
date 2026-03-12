from __future__ import annotations

import re
from pathlib import Path

from .naming import parse_movie_ref


def normalize_title_token(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.strip().lower())


def extract_id_name(item: dict) -> tuple[int | None, str]:
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


def format_id_name_pairs(items: list[dict]) -> str:
    pairs: list[str] = []
    for item in items:
        item_id, item_name = extract_id_name(item)
        if item_id is not None:
            pairs.append(f"{item_id}:{item_name}")
    return ", ".join(pairs)


def format_id_name_multiline(items: list[dict], indent: str = "  - ") -> str:
    pairs: list[str] = []
    for item in items:
        item_id, item_name = extract_id_name(item)
        if item_id is not None:
            pairs.append(f"{item_id}:{item_name}")
    return "\n".join(f"{indent}{pair}" for pair in pairs)


def extract_parse_custom_format_ids(parse_result: dict) -> set[int]:
    custom_formats = parse_result.get("customFormats")
    if not isinstance(custom_formats, list):
        return set()

    ids: set[int] = set()
    for item in custom_formats:
        if not isinstance(item, dict):
            continue
        format_id = item.get("id")
        if isinstance(format_id, int):
            ids.add(format_id)
    return ids


def _extract_quality_definition_id(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        nested_quality = value.get("quality")
        if isinstance(nested_quality, dict):
            nested_quality_id = nested_quality.get("id")
            if isinstance(nested_quality_id, int):
                return nested_quality_id
        quality_id = value.get("id")
        if isinstance(quality_id, int):
            return quality_id
    return None


def extract_parse_quality_definition_id(parse_result: dict) -> int | None:
    direct_quality_id = _extract_quality_definition_id(parse_result.get("quality"))
    if direct_quality_id is not None:
        return direct_quality_id

    parsed_movie_info = parse_result.get("parsedMovieInfo")
    if isinstance(parsed_movie_info, dict):
        parsed_quality_id = _extract_quality_definition_id(parsed_movie_info.get("quality"))
        if parsed_quality_id is not None:
            return parsed_quality_id

        parsed_definition_id = _extract_quality_definition_id(
            parsed_movie_info.get("qualityDefinition")
        )
        if parsed_definition_id is not None:
            return parsed_definition_id

    return None


def parse_candidates_for_folder(folder: Path, video_extensions: set[str]) -> list[str]:
    candidates = [folder.name]
    for child in sorted(folder.iterdir()):
        if child.is_file() and child.suffix.lower() in video_extensions:
            candidates.append(child.stem)
            candidates.append(child.name)
            break
    return candidates


def pick_lookup_candidate(folder: Path, candidates: list[dict]) -> dict | None:
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

    ref_norm = normalize_title_token(ref.title)
    best_score = -1
    best: dict | None = None

    for item in candidates:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        candidate_norm = normalize_title_token(title)
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
