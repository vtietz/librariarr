from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from .common import (
    IMDB_ID_RE,
    IMDB_NEAR_TOKEN_RE,
    IMDB_UNIQUE_ID_RE,
    TMDB_ID_RE,
    TMDB_UNIQUE_ID_RE,
    TVDB_ID_RE,
    TVDB_UNIQUE_ID_RE,
)


def _parse_int_id(value: str | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _extract_external_ids_from_nfo_xml(
    root: ET.Element,
) -> tuple[int | None, str | None, int | None]:
    tmdb_id = _parse_int_id(root.findtext("tmdbid", default=""))
    tvdb_id = _parse_int_id(root.findtext("tvdbid", default=""))

    imdb_text = str(root.findtext("imdbid", default="")).strip().lower()
    imdb_id = imdb_text if imdb_text.startswith("tt") else None

    for uniqueid_node in root.findall("uniqueid"):
        kind = str(uniqueid_node.attrib.get("type") or "").strip().lower()
        uniqueid_value = (uniqueid_node.text or "").strip()

        if kind == "tmdb" and tmdb_id is None:
            tmdb_id = _parse_int_id(uniqueid_value)
            continue

        if kind == "imdb" and imdb_id is None:
            normalized_imdb = uniqueid_value.lower()
            if normalized_imdb.startswith("tt"):
                imdb_id = normalized_imdb
            continue

        if kind == "tvdb" and tvdb_id is None:
            tvdb_id = _parse_int_id(uniqueid_value)

    return tmdb_id, imdb_id, tvdb_id


def extract_external_ids_from_text(text: str) -> tuple[int | None, str | None]:
    tmdb_id: int | None = None
    imdb_id: str | None = None

    tmdb_match = TMDB_UNIQUE_ID_RE.search(text) or TMDB_ID_RE.search(text)
    if tmdb_match is not None:
        try:
            tmdb_id = int(tmdb_match.group(1))
        except (TypeError, ValueError):
            tmdb_id = None

    imdb_match = (
        IMDB_UNIQUE_ID_RE.search(text) or IMDB_NEAR_TOKEN_RE.search(text) or IMDB_ID_RE.search(text)
    )
    if imdb_match is not None:
        imdb_id = (
            imdb_match.group(1).lower() if imdb_match.lastindex else imdb_match.group(0).lower()
        )

    return tmdb_id, imdb_id


def extract_tvdb_id_from_text(text: str) -> int | None:
    tvdb_match = TVDB_UNIQUE_ID_RE.search(text) or TVDB_ID_RE.search(text)
    if tvdb_match is None:
        return None
    try:
        return int(tvdb_match.group(1))
    except (TypeError, ValueError):
        return None


def extract_external_ids_from_nfo(
    nfo_path: Path,
) -> tuple[int | None, str | None, int | None]:
    try:
        text = nfo_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None, None, None

    fallback_tmdb_id, fallback_imdb_id = extract_external_ids_from_text(text)
    fallback_tvdb_id = extract_tvdb_id_from_text(text)

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return fallback_tmdb_id, fallback_imdb_id, fallback_tvdb_id

    tmdb_id, imdb_id, tvdb_id = _extract_external_ids_from_nfo_xml(root)
    if tmdb_id is None:
        tmdb_id = fallback_tmdb_id
    if imdb_id is None:
        imdb_id = fallback_imdb_id
    if tvdb_id is None:
        tvdb_id = fallback_tvdb_id

    return tmdb_id, imdb_id, tvdb_id
