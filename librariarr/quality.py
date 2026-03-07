from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .config import QualityRule

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m2ts", ".mov", ".wmv", ".ts"}


def collect_movie_text(movie_dir: Path) -> str:
    parts = [movie_dir.name.lower()]
    for child in movie_dir.iterdir():
        if child.is_file() and child.suffix.lower() in VIDEO_EXTENSIONS:
            parts.append(child.name.lower())
    return " ".join(parts)


def collect_nfo_text(movie_dir: Path) -> str:
    parts: list[str] = []
    for child in sorted(movie_dir.iterdir()):
        if not child.is_file() or child.suffix.lower() != ".nfo":
            continue
        try:
            parts.append(child.read_text(encoding="utf-8", errors="ignore").lower())
        except OSError:
            continue
    return " ".join(parts)


def _first_video_file(movie_dir: Path) -> Path | None:
    candidates = []
    for child in sorted(movie_dir.iterdir()):
        if child.is_file() and child.suffix.lower() in VIDEO_EXTENSIONS:
            candidates.append(child)
    return candidates[0] if candidates else None


def collect_media_probe_text(movie_dir: Path, probe_bin: str = "ffprobe") -> str:
    file_path = _first_video_file(movie_dir)
    if file_path is None:
        return ""

    cmd = [
        probe_bin,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,codec_name",
        "-of",
        "json",
        str(file_path),
    ]

    try:
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, timeout=5)
        data = json.loads(output)
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""

    stream = (data.get("streams") or [{}])[0]
    tokens: list[str] = []

    height = int(stream.get("height") or 0)
    if height >= 2000:
        tokens.append("2160p")
    elif height >= 1000:
        tokens.append("1080p")
    elif height >= 700:
        tokens.append("720p")

    codec = str(stream.get("codec_name") or "").lower()
    if codec in {"hevc", "h265"}:
        tokens.append("x265")
    elif codec in {"h264", "avc"}:
        tokens.append("x264")

    return " ".join(tokens)


def _match_quality_id(haystack: str, rules: list[QualityRule]) -> int | None:
    for rule in rules:
        if not rule.match:
            continue
        if all(keyword.lower() in haystack for keyword in rule.match):
            return rule.target_id
    return None


def map_quality_id(
    movie_dir: Path,
    rules: list[QualityRule],
    default_id: int = 4,
    use_nfo: bool = False,
    use_media_probe: bool = False,
    media_probe_bin: str = "ffprobe",
) -> int:
    filename_match = _match_quality_id(collect_movie_text(movie_dir), rules)
    if filename_match is not None:
        return filename_match

    if use_nfo:
        nfo_match = _match_quality_id(collect_nfo_text(movie_dir), rules)
        if nfo_match is not None:
            return nfo_match

    if use_media_probe:
        probe_match = _match_quality_id(collect_media_probe_text(movie_dir, media_probe_bin), rules)
        if probe_match is not None:
            return probe_match

    return default_id
