from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .config import CustomFormatRule, ProfileRule, QualityRule

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m2ts", ".mov", ".wmv", ".ts"}
SAMPLE_HINTS = {"sample", "trailer", "extras", "featurette", "behindthescenes"}
TOKEN_EQUIVALENTS = (
    frozenset({"x265", "h265", "hevc"}),
    frozenset({"x264", "h264", "avc"}),
)


LANGUAGE_TOKEN_MAP: dict[str, tuple[str, str]] = {
    "de": ("german", "lang-de"),
    "deu": ("german", "lang-de"),
    "ger": ("german", "lang-de"),
    "german": ("german", "lang-de"),
    "deutsch": ("german", "lang-de"),
    "en": ("english", "lang-en"),
    "eng": ("english", "lang-en"),
    "english": ("english", "lang-en"),
    "fr": ("french", "lang-fr"),
    "fra": ("french", "lang-fr"),
    "fre": ("french", "lang-fr"),
    "french": ("french", "lang-fr"),
    "es": ("spanish", "lang-es"),
    "spa": ("spanish", "lang-es"),
    "spanish": ("spanish", "lang-es"),
    "it": ("italian", "lang-it"),
    "ita": ("italian", "lang-it"),
    "italian": ("italian", "lang-it"),
    "ja": ("japanese", "lang-ja"),
    "jpn": ("japanese", "lang-ja"),
    "japanese": ("japanese", "lang-ja"),
    "nl": ("dutch", "lang-nl"),
    "nld": ("dutch", "lang-nl"),
    "dut": ("dutch", "lang-nl"),
    "dutch": ("dutch", "lang-nl"),
    "pt": ("portuguese", "lang-pt"),
    "por": ("portuguese", "lang-pt"),
    "portuguese": ("portuguese", "lang-pt"),
    "ru": ("russian", "lang-ru"),
    "rus": ("russian", "lang-ru"),
    "russian": ("russian", "lang-ru"),
    "pl": ("polish", "lang-pl"),
    "pol": ("polish", "lang-pl"),
    "polish": ("polish", "lang-pl"),
    "tr": ("turkish", "lang-tr"),
    "tur": ("turkish", "lang-tr"),
    "turkish": ("turkish", "lang-tr"),
    "uk": ("ukrainian", "lang-uk"),
    "ukr": ("ukrainian", "lang-uk"),
    "ukrainian": ("ukrainian", "lang-uk"),
    "cs": ("czech", "lang-cs"),
    "ces": ("czech", "lang-cs"),
    "cze": ("czech", "lang-cs"),
    "czech": ("czech", "lang-cs"),
}


def _language_alias_candidates(tag: str) -> set[str]:
    normalized = tag.strip().lower()
    if not normalized:
        return set()

    aliases = {token for token in re.split(r"[^a-z0-9]+", normalized) if token}
    if not aliases:
        return set()

    # Compact tags like "gereng" or "deen" appear in some NFO/metadata sources.
    compact = "".join(sorted(aliases, key=len, reverse=True)[:1])
    if compact.isalpha() and len(compact) >= 4:
        if len(compact) % 3 == 0:
            aliases.update(compact[index : index + 3] for index in range(0, len(compact), 3))
        if len(compact) % 2 == 0:
            aliases.update(compact[index : index + 2] for index in range(0, len(compact), 2))

    return aliases


def _normalize_audio_language(tag: str) -> list[tuple[str, str]]:
    normalized_pairs: set[tuple[str, str]] = set()
    for alias in _language_alias_candidates(tag):
        pair = LANGUAGE_TOKEN_MAP.get(alias)
        if pair is not None:
            normalized_pairs.add(pair)

    return sorted(normalized_pairs)


def collect_movie_text(movie_dir: Path) -> str:
    parts = [movie_dir.name.lower()]
    try:
        for child in movie_dir.rglob("*"):
            if child.is_file() and child.suffix.lower() in VIDEO_EXTENSIONS:
                parts.append(child.name.lower())
    except OSError:
        return " ".join(parts)
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


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _first_video_file(movie_dir: Path) -> Path | None:
    candidates: list[tuple[int, int, str, Path]] = []
    for child in sorted(movie_dir.iterdir()):
        if child.is_file() and child.suffix.lower() in VIDEO_EXTENSIONS:
            name = child.stem.lower()
            penalty = 0 if any(hint in name for hint in SAMPLE_HINTS) else 1
            try:
                size = child.stat().st_size
            except OSError:
                size = 0
            candidates.append((penalty, size, child.name.lower(), child))

    if not candidates:
        return None

    # Prefer non-sample files, then larger files, then a stable lexical tie-break.
    _, _, _, selected = max(candidates)
    return selected


def _video_probe_tokens(video_stream: dict) -> list[str]:
    tokens: list[str] = []

    height = _safe_int(video_stream.get("height"))
    if height >= 2000:
        tokens.append("2160p")
    elif height >= 1000:
        tokens.append("1080p")
    elif height >= 700:
        tokens.append("720p")

    codec = str(video_stream.get("codec_name") or "").lower()
    if codec in {"hevc", "h265"}:
        tokens.extend(["x265", "hevc"])
    elif codec in {"h264", "avc"}:
        tokens.extend(["x264", "h264"])

    transfer = str(video_stream.get("color_transfer") or "").lower()
    if transfer in {"smpte2084", "pq"}:
        tokens.append("hdr10")
    elif transfer in {"arib-std-b67", "hlg"}:
        tokens.append("hlg")

    bit_rate = _safe_int(video_stream.get("bit_rate"))
    if bit_rate >= 25_000_000:
        tokens.extend(["remux-bitrate", "very-high-bitrate"])
    elif bit_rate >= 10_000_000:
        tokens.append("high-bitrate")
    elif bit_rate >= 4_000_000:
        tokens.append("medium-bitrate")

    return tokens


def _audio_probe_tokens(audio_streams: list[dict]) -> list[str]:
    tokens: list[str] = []
    detected_languages: set[str] = set()

    for audio_stream in audio_streams:
        audio_codec = str(audio_stream.get("codec_name") or "").lower()
        if audio_codec:
            tokens.append(audio_codec)

        channels = _safe_int(audio_stream.get("channels"))
        if channels >= 8:
            tokens.append("7.1")
        elif channels >= 6:
            tokens.append("5.1")

        tags = audio_stream.get("tags")
        if not isinstance(tags, dict):
            continue

        raw_language = str(tags.get("language") or tags.get("LANGUAGE") or "")
        language_tokens = _normalize_audio_language(raw_language)
        if not language_tokens:
            continue

        for spoken_language, language_code in language_tokens:
            detected_languages.add(spoken_language)
            tokens.append(spoken_language)
            tokens.append(language_code)

    if len(detected_languages) >= 2:
        tokens.extend(["multi-language", "dual-language"])

    return tokens


def _pick_probe_streams(streams: list[dict]) -> tuple[dict, list[dict]]:
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video_stream is None:
        video_stream = streams[0] if streams else {}
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    return video_stream, audio_streams


def collect_media_probe_text(movie_dir: Path, probe_bin: str = "ffprobe") -> str:
    file_path = _first_video_file(movie_dir)
    if file_path is None:
        return ""

    cmd = [
        probe_bin,
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,width,height,codec_name,bit_rate,pix_fmt,color_transfer,"
        "color_primaries,profile,channels:stream_tags=language",
        "-of",
        "json",
        str(file_path),
    ]

    try:
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, timeout=5)
        data = json.loads(output)
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""

    streams = data.get("streams") or []
    video_stream, audio_streams = _pick_probe_streams(streams)
    tokens = _video_probe_tokens(video_stream)
    tokens.extend(_audio_probe_tokens(audio_streams))

    return " ".join(tokens)


def _match_quality_id(haystack: str, rules: list[QualityRule]) -> int | None:
    tokens = {token for token in re.split(r"[^a-z0-9]+", haystack.lower()) if token}

    def _keyword_matches(keyword: str) -> bool:
        if keyword in tokens:
            return True

        for equivalent_group in TOKEN_EQUIVALENTS:
            if keyword in equivalent_group and tokens.intersection(equivalent_group):
                return True

        return False

    for rule in rules:
        if not rule.match:
            continue
        if all(_keyword_matches(keyword.lower()) for keyword in rule.match):
            return rule.target_id
    return None


def _match_custom_format_ids(haystack: str, rules: list[CustomFormatRule]) -> set[int]:
    tokens = {token for token in re.split(r"[^a-z0-9]+", haystack.lower()) if token}

    def _keyword_matches(keyword: str) -> bool:
        if keyword in tokens:
            return True

        for equivalent_group in TOKEN_EQUIVALENTS:
            if keyword in equivalent_group and tokens.intersection(equivalent_group):
                return True

        return False

    matched_ids: set[int] = set()
    for rule in rules:
        if not rule.match:
            continue
        if all(_keyword_matches(keyword.lower()) for keyword in rule.match):
            matched_ids.add(rule.format_id)

    return matched_ids


def _match_profile_id(haystack: str, rules: list[ProfileRule]) -> int | None:
    tokens = {token for token in re.split(r"[^a-z0-9]+", haystack.lower()) if token}

    def _keyword_matches(keyword: str) -> bool:
        if keyword in tokens:
            return True

        for equivalent_group in TOKEN_EQUIVALENTS:
            if keyword in equivalent_group and tokens.intersection(equivalent_group):
                return True

        return False

    for rule in rules:
        if not rule.match:
            continue
        if all(_keyword_matches(keyword.lower()) for keyword in rule.match):
            return rule.profile_id

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


def map_custom_format_ids(
    movie_dir: Path,
    rules: list[CustomFormatRule],
    use_nfo: bool = False,
    use_media_probe: bool = False,
    media_probe_bin: str = "ffprobe",
) -> set[int]:
    if not rules:
        return set()

    haystacks = [collect_movie_text(movie_dir)]
    if use_nfo:
        haystacks.append(collect_nfo_text(movie_dir))
    if use_media_probe:
        haystacks.append(collect_media_probe_text(movie_dir, media_probe_bin))

    matched_ids: set[int] = set()
    for haystack in haystacks:
        if haystack:
            matched_ids.update(_match_custom_format_ids(haystack, rules))

    return matched_ids


def map_profile_id(
    movie_dir: Path,
    rules: list[ProfileRule],
    default_id: int | None = None,
    use_nfo: bool = False,
    use_media_probe: bool = False,
    media_probe_bin: str = "ffprobe",
) -> int | None:
    filename_match = _match_profile_id(collect_movie_text(movie_dir), rules)
    if filename_match is not None:
        return filename_match

    if use_nfo:
        nfo_match = _match_profile_id(collect_nfo_text(movie_dir), rules)
        if nfo_match is not None:
            return nfo_match

    if use_media_probe:
        probe_match = _match_profile_id(collect_media_probe_text(movie_dir, media_probe_bin), rules)
        if probe_match is not None:
            return probe_match

    return default_id
