from __future__ import annotations

from pathlib import Path

from .config import QualityRule


VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m2ts", ".mov", ".wmv", ".ts"}


def collect_movie_text(movie_dir: Path) -> str:
    parts = [movie_dir.name.lower()]
    for child in movie_dir.iterdir():
        if child.is_file() and child.suffix.lower() in VIDEO_EXTENSIONS:
            parts.append(child.name.lower())
    return " ".join(parts)


def map_quality_id(movie_dir: Path, rules: list[QualityRule], default_id: int = 4) -> int:
    haystack = collect_movie_text(movie_dir)
    for rule in rules:
        if not rule.match:
            continue
        if all(keyword.lower() in haystack for keyword in rule.match):
            return rule.target_id
    return default_id
