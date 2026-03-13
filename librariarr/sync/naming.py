from __future__ import annotations

import re
from dataclasses import dataclass

TITLE_YEAR_RE = re.compile(r"^(?P<title>.+?)\s*\((?P<year>\d{4})\)(?:\s+.*)?$")
PATH_SEPARATOR_TRANSLATION = str.maketrans({"/": "-", "\\": "-"})


@dataclass(frozen=True)
class MovieRef:
    title: str
    year: int | None


def extract_title_year(name: str) -> tuple[str, int] | None:
    match = TITLE_YEAR_RE.match(name.strip())
    if not match:
        return None
    return (match.group("title").strip(), int(match.group("year")))


def canonical_name_from_folder(name: str) -> str:
    parsed = extract_title_year(name)
    if parsed is None:
        return name.strip()
    title, year = parsed
    return f"{title} ({year})"


def safe_path_component(name: str) -> str:
    return name.translate(PATH_SEPARATOR_TRANSLATION).strip()


def parse_movie_ref(name: str) -> MovieRef:
    parsed = extract_title_year(name)
    if parsed is None:
        return MovieRef(title=name.strip().lower(), year=None)
    title, year = parsed
    return MovieRef(title=title.lower(), year=year)
