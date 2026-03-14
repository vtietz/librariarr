from __future__ import annotations

import re
from pathlib import Path

from .naming import parse_movie_ref

TITLE_WORD_RE = re.compile(r"[a-z0-9]+")
TITLE_STOPWORDS = {
    "a",
    "an",
    "the",
    "der",
    "die",
    "das",
    "ein",
    "eine",
    "le",
    "la",
    "les",
    "el",
    "los",
    "las",
    "un",
    "une",
}


def normalize_title_token(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.strip().lower())


def _normalized_title_words(title: str) -> set[str]:
    words = [word for word in TITLE_WORD_RE.findall(title.strip().lower()) if word]
    if not words:
        return set()

    filtered = [word for word in words if word not in TITLE_STOPWORDS]
    if filtered:
        return set(filtered)
    return set(words)


def _candidate_title_variants(item: dict) -> list[str]:
    titles = _candidate_primary_titles(item)
    titles.extend(_candidate_alternate_titles(item))
    return _unique_titles(titles)


def _candidate_primary_titles(item: dict) -> list[str]:
    titles: list[str] = []
    for key in ("title", "sortTitle", "originalTitle"):
        raw = item.get(key)
        if isinstance(raw, str):
            value = raw.strip()
            if value:
                titles.append(value)
    return titles


def _candidate_alternate_titles(item: dict) -> list[str]:
    alt_titles = item.get("alternateTitles")
    if not isinstance(alt_titles, list):
        return []

    titles: list[str] = []
    for alt in alt_titles:
        if isinstance(alt, str):
            value = alt.strip()
            if value:
                titles.append(value)
            continue

        if not isinstance(alt, dict):
            continue

        for key in ("title", "name"):
            raw = alt.get(key)
            if isinstance(raw, str):
                value = raw.strip()
                if value:
                    titles.append(value)
    return titles


def _unique_titles(titles: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_titles: list[str] = []
    for title in titles:
        marker = title.lower()
        if marker in seen:
            continue
        seen.add(marker)
        unique_titles.append(title)
    return unique_titles


def _best_direct_title_score(item: dict, ref_norm: str) -> int:
    score = -1
    for title in _candidate_title_variants(item):
        candidate_norm = normalize_title_token(title)
        next_score = 0
        if candidate_norm == ref_norm:
            next_score += 100
        elif candidate_norm and (candidate_norm in ref_norm or ref_norm in candidate_norm):
            next_score += 50
        score = max(score, next_score)
    return score


def _word_overlap_score(ref_words: set[str], candidate_words: set[str]) -> int:
    overlap_count = len(ref_words & candidate_words)
    if overlap_count == 0:
        return -1

    extra_count = max(0, len(candidate_words) - overlap_count)
    score = overlap_count * 40 - extra_count * 10
    if candidate_words == ref_words:
        score += 50
    if ref_words.issubset(candidate_words):
        score += 20
    return score


def _best_fallback_word_score(item: dict, ref_words: set[str]) -> int:
    best_score = -1
    for title in _candidate_title_variants(item):
        candidate_words = _normalized_title_words(title)
        if not candidate_words:
            continue
        best_score = max(best_score, _word_overlap_score(ref_words, candidate_words))
    return best_score


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


def _candidates_filtered_by_year(candidates: list[dict], year: int | None) -> list[dict]:
    if year is None:
        return candidates

    return [
        item
        for item in candidates
        if isinstance(item.get("year"), int) and item.get("year") == year
    ]


def _with_optional_year_bonus(score: int, item: dict, year: int | None) -> int:
    if year is not None and item.get("year") == year:
        return score + 20
    return score


def _pick_best_direct_match(candidates: list[dict], ref_norm: str, year: int | None) -> dict | None:
    best_score = -1
    best: dict | None = None
    for item in candidates:
        score = _best_direct_title_score(item, ref_norm)
        if score < 0:
            continue

        score = _with_optional_year_bonus(score, item, year)
        if score > best_score:
            best_score = score
            best = item

    return best if best_score > 0 else None


def _pick_best_fallback_match(
    candidates: list[dict],
    ref_words: set[str],
    year: int | None,
) -> dict | None:
    best_score = -1
    best: dict | None = None
    for item in candidates:
        score = _best_fallback_word_score(item, ref_words)
        if score < 0:
            continue

        score = _with_optional_year_bonus(score, item, year)
        if score > best_score:
            best_score = score
            best = item

    return best if best_score > 0 else None


def pick_lookup_candidate(folder: Path, candidates: list[dict]) -> dict | None:
    if not candidates:
        return None

    ref = parse_movie_ref(folder.name)
    filtered_candidates = _candidates_filtered_by_year(candidates, ref.year)
    if ref.year is not None and not filtered_candidates:
        return None

    ref_norm = normalize_title_token(ref.title)
    direct_match = _pick_best_direct_match(filtered_candidates, ref_norm, ref.year)
    if direct_match is not None:
        return direct_match

    # Fallback path for localized naming differences (e.g. "Die Simpsons" vs "The Simpsons").
    ref_words = _normalized_title_words(ref.title)
    if not ref_words:
        return None

    return _pick_best_fallback_match(filtered_candidates, ref_words, ref.year)
